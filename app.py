from pypdf import PdfReader
import docx
import streamlit as st
from openai import OpenAI
import pandas as pd
import datetime
import json
from supabase import create_client, Client
import time

# ================= 1. 核心配置 =================
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

# ================= 3. 状态持久化 =================
def load_participant_state(pid):
    try:
        response = supabase.table("participant_state").select("*").eq("participant_id", pid).execute()
        if response.data:
            record = response.data[0]
            messages = json.loads(record["messages"]) if record["messages"] else []
            round_count = record.get("current_round", 0)
            return messages, round_count
    except Exception as e:
        st.warning(f"加载历史状态失败：{e}")
    return None, None

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
        {"role": "assistant", "content": "您好！我是您的教育研究全栈助理。无论您目前正卡在寻找文献的理论Gap，还是纠结数据分析的逻辑推演，亦或是需要模拟审稿人为您挑刺，我都在这里。请详细告诉我：您目前正在推进哪一项具体的教育学研究任务？"}
    ]

# ================= 4. 方案数据 =================
def load_plan(pid):
    try:
        response = supabase.table("research_plans").select("*").eq("participant_id", pid).execute()
        if response.data:
            return response.data[0]
    except Exception as e:
        return None
    return None

def save_plan(pid, task1_text, task1_button, task2_text, task2_button, task3_text, task3_button):
    data = {
        "participant_id": pid,
        "task1_text": task1_text,
        "task1_button": task1_button,
        "task2_text": task2_text,
        "task2_button": task2_button,
        "task3_text": task3_text,
        "task3_button": task3_button,
        "updated_at": datetime.datetime.now().isoformat()
    }
    try:
        supabase.table("research_plans").upsert(data, on_conflict="participant_id").execute()
        return True
    except Exception as e:
        st.error(f"方案保存失败：{e}")
        return False

# ================= 5. 页面初始化 =================
st.set_page_config(page_title="EduResearch Copilot", page_icon="🎓", layout="wide")

if "participant_id" not in st.session_state:
    st.session_state.participant_id = ""
if "messages" not in st.session_state:
    st.session_state.messages = get_initial_messages()
if "round_count" not in st.session_state:
    st.session_state.round_count = 0
if "state_loaded" not in st.session_state:
    st.session_state.state_loaded = False
if "prompt_input" not in st.session_state:
    st.session_state.prompt_input = ""

# ================= 6. CSS: 固定三栏高度并滚动 =================
st.markdown(
    """
    <style>
        /* 紧凑顶部 */
        .main .block-container {
            padding-top: 0.5rem;
            padding-bottom: 0.5rem;
            max-width: 100% !important;
        }
        /* 三栏父容器固定高度 */
        div[data-testid="stHorizontalBlock"] {
            height: calc(100vh - 120px) !important;
            min-height: 400px;
            align-items: stretch !important;
        }
        /* 每一列内部滚动 */
        div[data-testid="stHorizontalBlock"] > div {
            height: 100% !important;
            overflow-y: auto !important;
            padding-right: 10px;
            padding-left: 5px;
        }
        /* 滚动条美化 */
        ::-webkit-scrollbar {
            width: 6px;
        }
        ::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb {
            background: #888;
            border-radius: 10px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #555;
        }
        /* 标题边距 */
        h1, h2, h3 {
            margin-top: 0.2rem;
            margin-bottom: 0.3rem;
        }
        /* 侧边栏保留样式（我们不再用sidebar） */
    </style>
    """,
    unsafe_allow_html=True
)

# ================= 7. 主标题 =================
st.markdown("# 🎓 EduResearch Copilot")
st.divider()

# ================= 8. 三栏布局 =================
if not st.session_state.participant_id:
    st.warning("⚠️ 请先在左侧栏输入您的被试编号！")

col_left, col_mid, col_right = st.columns([1, 2, 1], gap="medium")

# ---------- 左栏：基本信息 ----------
with col_left:
    st.subheader("📋 基本信息")
    st.markdown("**👤 被试**")
    pid_input = st.text_input(
        "编号",
        value=st.session_state.participant_id if st.session_state.participant_id else "",
        key="pid_input_left",
        placeholder="如 P001",
        label_visibility="collapsed"
    )
    if pid_input and pid_input.strip() != st.session_state.participant_id:
        new_pid = pid_input.strip()
        st.session_state.participant_id = new_pid
        st.session_state.state_loaded = False
        st.rerun()
    if st.session_state.participant_id:
        st.success(f"当前被试：{st.session_state.participant_id}")
    else:
        st.info("请输入编号")

    st.divider()
    st.markdown("**📊 对话进度**")
    if st.session_state.participant_id:
        st.metric(label="已完成的对话轮数", value=st.session_state.round_count)
        if st.session_state.round_count >= 10:
            st.success("✅ 已达成建议轮数（10轮）")
        elif st.session_state.round_count >= 8:
            st.info("💡 接近建议轮数（8-12轮）")
        else:
            st.caption("建议完成 8-12 轮对话")
    else:
        st.caption("请先输入被试编号")

    st.divider()
    st.markdown("**🔐 研究者数据导出**")
    password = st.text_input("密码", type="password", placeholder="输入导出密码")
    RESEARCHER_PASSWORD = st.secrets.get("RESEARCHER_PASSWORD", "MyPassword123")
    if password:
        if password == RESEARCHER_PASSWORD:
            st.success("密码正确")
            # 交互日志下载
            try:
                response = supabase.table("research_logs").select("*").execute()
                if response.data:
                    df = pd.DataFrame(response.data)
                    csv_data = df.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                        label="📥 交互日志",
                        data=csv_data.encode('utf-8-sig'),
                        file_name="research_logs.csv",
                        mime="text/csv",
                        key="dl_logs"
                    )
            except Exception as e:
                st.warning("无日志数据")
            # 方案数据下载
            try:
                response_plan = supabase.table("research_plans").select("*").execute()
                if response_plan.data:
                    df_plan = pd.DataFrame(response_plan.data)
                    csv_plan = df_plan.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                        label="📥 方案数据",
                        data=csv_plan.encode('utf-8-sig'),
                        file_name="research_plans.csv",
                        mime="text/csv",
                        key="dl_plans"
                    )
            except Exception as e:
                st.warning("无方案数据")
        else:
            st.error("密码错误")
    else:
        st.caption("请输入密码")

# ---------- 中栏：AI交互 ----------
with col_mid:
    st.subheader("💬 AI 学术助手对话")
    
    # 如果未输入编号，显示提示
    if not st.session_state.participant_id:
        st.info("请先在左侧输入被试编号以开始对话")
    else:
        # 加载历史状态
        if not st.session_state.state_loaded:
            loaded_msgs, loaded_round = load_participant_state(st.session_state.participant_id)
            if loaded_msgs is not None:
                if loaded_msgs and loaded_msgs[0].get("role") == "system":
                    st.session_state.messages = loaded_msgs
                else:
                    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}] + loaded_msgs
                st.session_state.round_count = loaded_round
                st.session_state.state_loaded = True
            else:
                st.session_state.messages = get_initial_messages()
                st.session_state.round_count = 0
                st.session_state.state_loaded = True
                save_participant_state(st.session_state.participant_id, st.session_state.messages, st.session_state.round_count)

        # 显示历史消息
        for msg in st.session_state.messages:
            if msg["role"] != "system":
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        # 输入表单
        with st.form(key="prompt_form", clear_on_submit=True):
            user_input = st.text_area(
                "提示词",
                height=80,
                key="prompt_input",
                label_visibility="collapsed",
                placeholder="请输入您的科研问题..."
            )
            uploaded_file = st.file_uploader(
                "上传文档",
                type=["pdf", "docx"],
                help="支持 PDF 或 Word，内容将附加到提问中",
                key="file_uploader_simple",
                label_visibility="collapsed"
            )
            if uploaded_file is not None:
                st.caption(f"已选择：{uploaded_file.name}")

            st.markdown("👇 **行为按钮**")
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

                # 处理附件
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

                # 显示用户消息
                with st.chat_message("user"):
                    if file_content:
                        st.markdown(f"📎 **已附加文档**，提问：{user_input}")
                    else:
                        st.markdown(f"**[{clicked_behavior}]** {user_input}")

                st.session_state.messages.append({"role": "user", "content": full_user_message})

                # 调用 AI
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

                # 持久化日志
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

# ---------- 右栏：方案填写 ----------
with col_right:
    st.subheader("📝 研究方案填写")
    if not st.session_state.participant_id:
        st.info("请先在左侧输入被试编号")
    else:
        existing_plan = load_plan(st.session_state.participant_id)

        with st.form(key="plan_form"):
            st.markdown("**AI协同研究方案生成记录表**")
            st.caption("说明：请在与AI多轮交互后提炼填写。")

            # 子任务1
            st.markdown("**1. 选题与理论切入点**")
            task1_text = st.text_area(
                "提炼“选题核心与理论视角”（限150字）",
                value=existing_plan["task1_text"] if existing_plan else "",
                height=60,
                max_chars=150,
                key="task1_text",
                label_visibility="collapsed"
            )
            task1_button = st.radio(
                "主导行为",
                options=["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"],
                index=(["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"].index(existing_plan["task1_button"]) if existing_plan and existing_plan["task1_button"] in ["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"] else 0),
                horizontal=True,
                key="task1_button",
                label_visibility="collapsed"
            )
            st.divider()

            # 子任务2
            st.markdown("**2. 实施步骤与工具设计**")
            task2_text = st.text_area(
                "提炼“核心实施步骤或研究工具框架”（限150字）",
                value=existing_plan["task2_text"] if existing_plan else "",
                height=60,
                max_chars=150,
                key="task2_text",
                label_visibility="collapsed"
            )
            task2_button = st.radio(
                "主导行为",
                options=["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"],
                index=(["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"].index(existing_plan["task2_button"]) if existing_plan and existing_plan["task2_button"] in ["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"] else 0),
                horizontal=True,
                key="task2_button",
                label_visibility="collapsed"
            )
            st.divider()

            # 子任务3
            st.markdown("**3. 反思局限性与方案定稿**")
            task3_text = st.text_area(
                "提炼“方案局限性及最终修改决策”（限150字）",
                value=existing_plan["task3_text"] if existing_plan else "",
                height=60,
                max_chars=150,
                key="task3_text",
                label_visibility="collapsed"
            )
            task3_button = st.radio(
                "主导行为",
                options=["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"],
                index=(["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"].index(existing_plan["task3_button"]) if existing_plan and existing_plan["task3_button"] in ["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"] else 0),
                horizontal=True,
                key="task3_button",
                label_visibility="collapsed"
            )

            submitted = st.form_submit_button("📤 提交方案")
            if submitted:
                if not task1_text.strip() or not task2_text.strip() or not task3_text.strip():
                    st.warning("请完整填写所有文本字段")
                else:
                    success = save_plan(
                        st.session_state.participant_id,
                        task1_text.strip(),
                        task1_button,
                        task2_text.strip(),
                        task2_button,
                        task3_text.strip(),
                        task3_button
                    )
                    if success:
                        st.success("✅ 方案已提交/更新！")
                        st.rerun()
                    else:
                        st.error("❌ 提交失败")
