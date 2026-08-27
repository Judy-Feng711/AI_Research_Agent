from pypdf import PdfReader
import docx
import streamlit as st
from openai import OpenAI
import pandas as pd
import datetime
import json
from supabase import create_client, Client
import time

# ================= 1. 核心配置区 =================
DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ================= 2. 系统提示词 =================
SYSTEM_PROMPT = """您是一个名为“全栈式教育研究学术助理”的高级AI。您的目标是深度辅助教育学领域的研究生完成真实、复杂的学术研究任务，而非简单地给出敷衍的现成答案。您需要展现出教育研究的专业性、批判性和逻辑性。
核心能力与任务模块：
1. 选题与文献发现： 辅助梳理文献脉络，对比不同教育理论（如建构主义与行为主义），精准分析研究空白。
2. 研究规划与设计： 从教育心理学、课程论等多重视角构建分析框架，对比个案研究、行动研究等方法的适用性。
3. 实施与数据采集： 协助开发访谈提纲等收集工具，指出并规避表述偏差及伦理风险。
4. 数据分析与阐释： 提供Python/R等统计脚本编写指引，深度解读统计结果与理论模型的深层逻辑，接受用户的逻辑纠错。
5. 论文撰写与润色： 辅助母语润色，检查专业术语一致性，并模拟“严苛审稿人”视角提出批判性修改意见。
6. 传播、评估与伦理： 辅助提炼实践建议，主动规避文化/性别等偏见，模拟同行质疑进行答辩演练。
互动规则：
- 拒绝单次终结：面对用户的宽泛问题，不要一次性给出全套方案，通过反问或追问引导用户思考。
- 启发大于代劳：当用户索要直接答案时，先给出框架和思路，鼓励用户多轮探讨。"""

# ================= 3. 状态持久化函数（轮次取最大round，保持不变） =================
def load_participant_state(pid):
    """
    从数据库实时加载被试状态：
    - 轮数从 research_logs 表统计，取最大 round 值（有效按钮+非空输入）
    - 消息列表从 participant_state 表加载
    - 始终返回 (messages, round_count)
    """
    messages = get_initial_messages()
    round_count = 0

    try:
        # 1. 统计有效轮数（取最大round）
        log_resp = supabase.table("research_logs")\
            .select("*")\
            .eq("participant_id", pid)\
            .execute()
        if log_resp.data:
            valid_behaviors = ["获取基础信息", "规范语言/格式", "微调研究逻辑", "重构研究方案", "拓展研究思路"]
            max_round = 0
            for log in log_resp.data:
                if log.get("behavior_button") in valid_behaviors and log.get("user_prompt") and log.get("user_prompt").strip() != "":
                    r = log.get("round", 0)
                    if r > max_round:
                        max_round = r
            round_count = max_round

        # 2. 加载历史消息
        state_resp = supabase.table("participant_state").select("*").eq("participant_id", pid).execute()
        if state_resp.data:
            raw_messages = json.loads(state_resp.data[0]["messages"]) if state_resp.data[0]["messages"] else []
            if raw_messages:
                if raw_messages[0].get("role") != "system":
                    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + raw_messages
                else:
                    messages = raw_messages
    except Exception as e:
        st.error(f"⚠️ 加载被试 {pid} 数据失败，请检查网络或刷新重试。错误详情：{e}")
    return messages, round_count

def save_participant_state(pid, messages, round_count):
    data = {
        "participant_id": pid,
        "current_round": round_count,
        "messages": json.dumps(messages, ensure_ascii=False),
        "updated_at": datetime.datetime.now().isoformat()
    }
    try:
        supabase.table("participant_state").upsert(data, on_conflict="participant_id").execute()
        return True
    except Exception as e:
        st.error(f"状态保存失败：{e}")
        return False

def get_initial_messages():
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": "您好！我是您的教育研究全栈助理。无论您目前正卡在寻找文献的理论Gap，还是纠结数据分析的逻辑推演，亦或是需要模拟审稿人为您挑刺，我都在这里。请详细告诉我您的要求。"}
    ]

# ================= 4. 方案数据函数（扩展为6个子任务，并容错处理缺失字段） =================
def load_plan(pid):
    try:
        response = supabase.table("research_plans").select("*").eq("participant_id", pid).execute()
        if response.data:
            plan = response.data[0]
            # 确保6个字段都存在，缺失则补空字符串（防止KeyError）
            for key in ["task4_text", "task5_text", "task6_text"]:
                if key not in plan:
                    plan[key] = ""
            return plan
    except Exception as e:
        st.warning(f"加载方案数据失败：{e}")
    return None

def save_plan(pid, task1_text, task2_text, task3_text, task4_text, task5_text, task6_text):
    data = {
        "participant_id": pid,
        "task1_text": task1_text,
        "task2_text": task2_text,
        "task3_text": task3_text,
        "task4_text": task4_text,
        "task5_text": task5_text,
        "task6_text": task6_text,
        "task1_button": "",
        "task2_button": "",
        "task3_button": "",
        "updated_at": datetime.datetime.now().isoformat()
    }
    try:
        supabase.table("research_plans").upsert(data, on_conflict="participant_id").execute()
        return True
    except Exception as e:
        st.error(f"方案保存失败：{e} 请确保数据库表已添加 task4_text, task5_text, task6_text 列。")
        return False

# ================= 5. 页面初始化 =================
st.set_page_config(page_title="EduResearch Copilot", page_icon="🎓", layout="wide")

if "participant_id" not in st.session_state:
    st.session_state.participant_id = ""
if "messages" not in st.session_state:
    st.session_state.messages = get_initial_messages()
if "round_count" not in st.session_state:
    st.session_state.round_count = 0
if "prompt_input" not in st.session_state:
    st.session_state.prompt_input = ""

# ================= 6. CSS（移除右侧灰色背景） =================
st.markdown(
    """
    <style>
        .top-fixed {
            position: sticky;
            top: 0;
            background-color: white;
            z-index: 100;
            padding: 0.5rem 1rem 0rem 1rem;
            border-bottom: 2px solid #ddd;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        .top-fixed .stExpander {
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
        }
        .top-fixed .stExpander .stExpanderContent {
            padding-bottom: 0.2rem !important;
        }
        [data-testid="stHorizontalBlock"] > div:first-child {
            overflow: visible !important;
            height: auto !important;
        }
        [data-testid="stHorizontalBlock"] > div:last-child {
            position: sticky !important;
            top: 120px !important;
            align-self: flex-start !important;
            height: auto !important;
            max-height: calc(100vh - 120px) !important;
            overflow-y: auto !important;
            /* 移除灰色背景，改为白色或透明 */
            background-color: transparent !important;
            padding: 10px !important;
            border-left: 1px solid #ddd;
        }
        [data-testid="stHorizontalBlock"] > div:last-child::-webkit-scrollbar {
            width: 6px;
        }
        [data-testid="stHorizontalBlock"] > div:last-child::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 5px;
        }
        [data-testid="stHorizontalBlock"] > div:last-child::-webkit-scrollbar-thumb {
            background: #888;
            border-radius: 5px;
        }
        [data-testid="stHorizontalBlock"] > div:last-child::-webkit-scrollbar-thumb:hover {
            background: #555;
        }
        [data-testid="stHorizontalBlock"] {
            height: auto !important;
            min-height: 0 !important;
            overflow: visible !important;
            align-items: flex-start !important;
        }
    </style>
    """,
    unsafe_allow_html=True
)

# ================= 7. 顶部信息栏（含退出按钮） =================
st.markdown('<div class="top-fixed">', unsafe_allow_html=True)

# 创建两列：标题占大部分，右上角放退出按钮
col_title, col_exit = st.columns([5, 1])
with col_title:
    st.title("🎓 EduResearch Copilot (教育研究全栈助理)")
with col_exit:
    # 如果当前有被试编号，显示退出按钮
    if st.session_state.participant_id:
        exit_clicked = st.button("🚪 退出实验", key="exit_button", use_container_width=True)
        if exit_clicked:
            # 记录退出事件到 research_logs
            exit_log = {
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "participant_id": st.session_state.participant_id,
                "round": st.session_state.round_count,
                "user_prompt": "退出实验",
                "behavior_button": "退出实验",
                "ai_response": ""
            }
            try:
                supabase.table("research_logs").insert(exit_log).execute()
                st.success("✅ 已记录退出实验，您的研究数据将不会被纳入最终分析。")
                # 清空状态
                st.session_state.participant_id = ""
                st.session_state.messages = get_initial_messages()
                st.session_state.round_count = 0
                st.rerun()
            except Exception as e:
                st.error(f"记录退出失败：{e}")
    else:
        # 无被试时显示占位
        st.write("")  # 占位保持布局

st.info(
    "您好！我是您的教育研究全栈助理。无论您目前正卡在寻找文献的理论Gap，"
    "还是纠结数据分析的逻辑推演，亦或是需要模拟审稿人为您挑刺，我都在这里。"
    "请在上方输入您的被试编号并开始对话。"
)

with st.expander("📋 被试信息与数据管理", expanded=True):
    col_id, col_progress, col_export = st.columns([1, 1, 1.5])
    
    with col_id:
        st.markdown("**👤 被试身份**")
        pid_input = st.text_input(
            "请输入您的被试编号（如 P001）：",
            value=st.session_state.participant_id,
            key="pid_input_top"
        )
        if pid_input and pid_input.strip() != st.session_state.participant_id:
            st.session_state.participant_id = pid_input.strip()
            st.rerun()

        if st.session_state.participant_id:
            st.success(f"当前被试：{st.session_state.participant_id}")
        else:
            st.info("请在上方输入编号")

    with col_progress:
        st.markdown("**📊 对话进度**")
        if st.session_state.participant_id:
            loaded_msgs, loaded_round = load_participant_state(st.session_state.participant_id)
            st.session_state.messages = loaded_msgs
            st.session_state.round_count = loaded_round

            st.metric(label="已完成的对话轮数", value=st.session_state.round_count)
            if st.session_state.round_count >= 10:
                st.success("✅ 已达成建议轮数（10轮）")
            elif st.session_state.round_count >= 8:
                st.info("💡 接近建议轮数（8-12轮）")
            else:
                st.caption("建议完成 8-12 轮对话")
        else:
            st.caption("请先输入被试编号")

    with col_export:
        st.markdown("**🔐 研究者数据导出**")
        password = st.text_input("请输入数据导出密码", type="password")
        RESEARCHER_PASSWORD = st.secrets.get("RESEARCHER_PASSWORD", "MyPassword123")
        if password:
            if password == RESEARCHER_PASSWORD:
                st.success("密码正确")
                try:
                    response = supabase.table("research_logs").select("*").execute()
                    if response.data:
                        df = pd.DataFrame(response.data)
                        csv_data = df.to_csv(index=False, encoding='utf-8-sig')
                        st.download_button(
                            label="📥 下载交互日志",
                            data=csv_data.encode('utf-8-sig'),
                            file_name="research_logs.csv",
                            mime="text/csv",
                            key="dl_logs"
                        )
                except Exception as e:
                    st.error(f"读取交互数据失败：{e}")
                try:
                    response_plan = supabase.table("research_plans").select("*").execute()
                    if response_plan.data:
                        df_plan = pd.DataFrame(response_plan.data)
                        csv_plan = df_plan.to_csv(index=False, encoding='utf-8-sig')
                        st.download_button(
                            label="📥 下载方案数据",
                            data=csv_plan.encode('utf-8-sig'),
                            file_name="research_plans.csv",
                            mime="text/csv",
                            key="dl_plans"
                        )
                except Exception as e:
                    st.error(f"读取方案数据失败：{e}")
            else:
                st.error("密码错误")
        else:
            st.info("请输入密码以导出数据")

st.markdown('</div>', unsafe_allow_html=True)

# ================= 8. 主体内容（左右列比例改为6:4） =================
if not st.session_state.participant_id:
    st.warning("⚠️ 请先在顶部输入您的被试编号！")
else:
    if not st.session_state.messages or st.session_state.messages[0].get("role") != "system":
        loaded_msgs, loaded_round = load_participant_state(st.session_state.participant_id)
        st.session_state.messages = loaded_msgs
        st.session_state.round_count = loaded_round

    col_left, col_right = st.columns([6, 4], gap="large")

    with col_left:
        st.subheader("💬 AI 学术助手对话")
        for msg in st.session_state.messages:
            if msg["role"] != "system":
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        with st.form(key="prompt_form", clear_on_submit=True):
            user_input = st.text_area(
                "在这里输入您的提示词 (Prompt)：",
                height=100,
                key="prompt_input",
                label_visibility="collapsed"
            )
            uploaded_file = st.file_uploader(
                "上传文档",
                type=["pdf", "docx"],
                help="快速模式下，仅识别图片与文件中的文字最多50个，每个100 MB",
                key="file_uploader_simple"
            )
            if uploaded_file is not None:
                st.caption(f"已选择：{uploaded_file.name}")

            st.markdown("👇 **请点击以下按钮提交您的提示词（请选择最符合您当前意图的行为）：**")
            col_b1, col_b2, col_b3, col_b4, col_b5 = st.columns(5)
            clicked_behavior = None
            if col_b1.form_submit_button("获取基础信息"):
                clicked_behavior = "获取基础信息"
            elif col_b2.form_submit_button("规范语言/格式"):
                clicked_behavior = "规范语言/格式"
            elif col_b3.form_submit_button("微调研究逻辑"):
                clicked_behavior = "微调研究逻辑"
            elif col_b4.form_submit_button("重构研究方案"):
                clicked_behavior = "重构研究方案"
            elif col_b5.form_submit_button("拓展研究思路"):
                clicked_behavior = "拓展研究思路"

            if clicked_behavior:
                if not user_input or user_input.strip() == "":
                    st.warning("⚠️ 请先输入提示词！")
                    st.stop()

                file_content = ""
                if uploaded_file is not None:
                    file_name = uploaded_file.name
                    if file_name.endswith(".pdf"):
                        try:
                            reader = PdfReader(uploaded_file)
                            for page in reader.pages:
                                text = page.extract_text()
                                if text:
                                    file_content += text + "\n"
                        except Exception as e:
                            st.error(f"PDF 解析失败：{e}")
                    elif file_name.endswith(".docx"):
                        try:
                            doc = docx.Document(uploaded_file)
                            for para in doc.paragraphs:
                                file_content += para.text + "\n"
                        except Exception as e:
                            st.error(f"Word 解析失败：{e}")
                    if file_content and len(file_content) > 5000:
                        file_content = file_content[:5000] + "\n...[内容已截断]"

                full_user_message = f"【上传文档内容】\n{file_content}\n\n【我的问题】\n{user_input}" if file_content else user_input

                with st.chat_message("user"):
                    if file_content:
                        st.markdown(f"📎 **已附加文档**，提问：{user_input}")
                    else:
                        st.markdown(f"**[{clicked_behavior}]** {user_input}")

                st.session_state.messages.append({"role": "user", "content": full_user_message})

                with st.chat_message("assistant"):
                    with st.spinner("思考中..."):
                        try:
                            response = client.chat.completions.create(
                                model="deepseek-v4-pro",
                                messages=st.session_state.messages
                            )
                            ai_reply = response.choices[0].message.content
                            st.markdown(ai_reply)
                        except Exception as e:
                            st.error(f"AI 调用失败：{e}")
                            st.stop()
                st.session_state.messages.append({"role": "assistant", "content": ai_reply})
                st.session_state.round_count += 1

                log_data = {
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "participant_id": st.session_state.participant_id,
                    "round": st.session_state.round_count,
                    "user_prompt": user_input,
                    "behavior_button": clicked_behavior,
                    "ai_response": ai_reply
                }
                try:
                    supabase.table("research_logs").insert(log_data).execute()
                except Exception as e:
                    st.error(f"日志保存失败：{e}")

                save_participant_state(
                    st.session_state.participant_id,
                    st.session_state.messages,
                    st.session_state.round_count
                )
                st.rerun()

    # ================= 右侧：研究方案填写（6个子任务，无按钮，所有输入框默认为空） =================
    with col_right:
        st.subheader("📝 研究方案填写")
        existing_plan = load_plan(st.session_state.participant_id)
        
        st.markdown("**AI协同研究方案生成记录表（被试填写版）**")
        st.caption("说明：请在与AI多轮交互完成每个子任务后，提炼产出并填写。")
        
        with st.form(key="plan_form"):
            st.markdown("**子任务1：选题与文献发现**")
            task1_text = st.text_area(
                "提炼“选题核心与理论视角”（限150字）：",
                value="",
                height=80,
                max_chars=150,
                key="task1_text"
            )
            st.divider()
            
            st.markdown("**子任务2：研究规划与设计**")
            task2_text = st.text_area(
                "提炼“研究设计框架”（限150字）：",
                value="",
                height=80,
                max_chars=150,
                key="task2_text"
            )
            st.divider()
            
            st.markdown("**子任务3：实施与数据采集**")
            task3_text = st.text_area(
                "提炼“实施步骤及工具”（限150字）：",
                value="",
                height=80,
                max_chars=150,
                key="task3_text"
            )
            st.divider()
            
            st.markdown("**子任务4：数据分析与阐释**")
            task4_text = st.text_area(
                "提炼“数据分析方法及结果解读”（限150字）：",
                value="",
                height=80,
                max_chars=150,
                key="task4_text"
            )
            st.divider()
            
            st.markdown("**子任务5：论文撰写与润色**")
            task5_text = st.text_area(
                "提炼“论文结构及润色要点”（限150字）：",
                value="",
                height=80,
                max_chars=150,
                key="task5_text"
            )
            st.divider()
            
            st.markdown("**子任务6：传播、评估与伦理**")
            task6_text = st.text_area(
                "提炼“实践建议与伦理考量”（限150字）：",
                value="",
                height=80,
                max_chars=150,
                key="task6_text"
            )
            
            submitted = st.form_submit_button("📤 提交方案")
            if submitted:
                if not all([task1_text.strip(), task2_text.strip(), task3_text.strip(),
                            task4_text.strip(), task5_text.strip(), task6_text.strip()]):
                    st.warning("建议填写所有子任务，以完善研究方案。")
                success = save_plan(
                    st.session_state.participant_id,
                    task1_text.strip(),
                    task2_text.strip(),
                    task3_text.strip(),
                    task4_text.strip(),
                    task5_text.strip(),
                    task6_text.strip()
                )
                if success:
                    st.success("✅ 方案已提交/更新！")
                    st.rerun()
                else:
                    st.error("❌ 提交失败，请检查数据库是否已添加所需字段。")
