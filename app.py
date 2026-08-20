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

# ================= 6. CSS 紧凑布局 =================
st.markdown(
    """
    <style>
        /* 移除默认边距，占满视口 */
        .main .block-container {
            padding: 0 !important;
            max-width: 100% !important;
            height: 100vh !important;
        }
        .main .block-container > div {
            display: flex !important;
            flex-direction: column !important;
            height: 100vh !important;
        }
        /* 上块：20% 高度，无滚动，紧凑内边距 */
        .top-block {
            height: 20vh !important;
            flex-shrink: 0 !important;
            overflow: hidden !important;
            padding: 2px 15px !important;
            border-bottom: 2px solid #ddd;
            background-color: #f0f2f6;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .top-block h2 {
            margin: 0 0 2px 0 !important;
            font-size: 1.4rem;
        }
        .top-block p {
            margin: 0 0 2px 0 !important;
            font-size: 0.9rem;
        }
        .top-block .stColumns {
            margin-top: 2px !important;
            gap: 0.5rem !important;
        }
        .top-block .stTextInput, .top-block .stMetric, .top-block .stButton {
            margin-bottom: 0 !important;
        }
        .top-block .stTextInput > div {
            margin-bottom: 0 !important;
        }
        .top-block .stMetric {
            margin-bottom: 0 !important;
        }
        /* 下块：80% 高度，flex行 */
        .bottom-block {
            height: 80vh !important;
            flex-shrink: 0 !important;
            display: flex !important;
            flex-direction: row !important;
            overflow: hidden !important;
        }
        /* 三列 */
        .col-left {
            width: 20% !important;
            height: 100% !important;
            overflow-y: auto !important;
            padding: 2px 8px 8px 8px !important;   /* 顶部padding仅2px，紧挨边框 */
            border-right: 1px solid #ddd;
            background-color: #fafafa;
        }
        .col-mid {
            width: 45% !important;
            height: 100% !important;
            overflow-y: auto !important;
            padding: 8px !important;
            border-right: 1px solid #ddd;
            background-color: #ffffff;
        }
        .col-right {
            width: 35% !important;
            height: 100% !important;
            overflow-y: auto !important;
            padding: 8px !important;
            background-color: #fafafa;
        }
        /* 左栏标题紧贴顶部 */
        .col-left h3 {
            margin-top: 0 !important;
            margin-bottom: 4px !important;
        }
        /* 滚动条样式 */
        .col-left::-webkit-scrollbar, .col-mid::-webkit-scrollbar, .col-right::-webkit-scrollbar {
            width: 6px;
        }
        .col-left::-webkit-scrollbar-track, .col-mid::-webkit-scrollbar-track, .col-right::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 5px;
        }
        .col-left::-webkit-scrollbar-thumb, .col-mid::-webkit-scrollbar-thumb, .col-right::-webkit-scrollbar-thumb {
            background: #888;
            border-radius: 5px;
        }
        .col-left::-webkit-scrollbar-thumb:hover, .col-mid::-webkit-scrollbar-thumb:hover, .col-right::-webkit-scrollbar-thumb:hover {
            background: #555;
        }
        /* 内部通用紧凑 */
        .stTextInput, .stTextArea, .stSelectbox, .stRadio, .stMetric {
            margin-bottom: 0.2rem !important;
        }
        .stButton button {
            width: 100%;
            margin: 2px 0;
            padding: 0.2rem 0.5rem;
        }
        .stForm {
            padding: 0 !important;
        }
        h1, h2, h3, h4 {
            margin: 0.1rem 0;
        }
        .stChatMessage {
            margin: 4px 0;
        }
        .stDivider {
            margin: 0.3rem 0;
        }
    </style>
    """,
    unsafe_allow_html=True
)

# ================= 7. 页面构建 =================

# ---- 上块：20% ----
st.markdown('<div class="top-block">', unsafe_allow_html=True)
st.markdown("## 🎓 EduResearch Copilot")
st.markdown("**欢迎使用全栈式教育研究学术助理！** 请先在下方输入被试编号，然后与AI进行多轮深度对话，并填写右侧的研究方案记录表。")

with st.container():
    col_id, col_progress, col_export = st.columns([1, 0.8, 1.2])
    with col_id:
        st.markdown("**👤 被试编号**")
        pid_input = st.text_input(
            "被试编号",
            value=st.session_state.participant_id if st.session_state.participant_id else "",
            key="pid_input_top",
            placeholder="请输入编号，如P001",
            label_visibility="collapsed"
        )
        if pid_input and pid_input.strip() != st.session_state.participant_id:
            new_pid = pid_input.strip()
            st.session_state.participant_id = new_pid
            st.session_state.state_loaded = False
            st.rerun()
        if st.session_state.participant_id:
            st.success(f"当前：{st.session_state.participant_id}")
        else:
            st.info("等待输入")
    with col_progress:
        st.markdown("**📊 对话进度**")
        if st.session_state.participant_id:
            st.metric(label="已完成轮数", value=st.session_state.round_count)
            if st.session_state.round_count >= 10:
                st.success("✅ 达成建议")
            elif st.session_state.round_count >= 8:
                st.info("💡 接近建议")
            else:
                st.caption("建议 8-12 轮")
        else:
            st.caption("待输入编号")
    with col_export:
        st.markdown("**🔐 数据导出**")
        password = st.text_input(
            "密码",
            type="password",
            key="export_pwd_top",
            placeholder="请输入导出密码",
            label_visibility="collapsed"
        )
        RESEARCHER_PASSWORD = st.secrets.get("RESEARCHER_PASSWORD", "MyPassword123")
        if password:
            if password == RESEARCHER_PASSWORD:
                st.success("密码正确")
                col_dl1, col_dl2 = st.columns(2)
                with col_dl1:
                    try:
                        resp = supabase.table("research_logs").select("*").execute()
                        if resp.data:
                            df = pd.DataFrame(resp.data)
                            csv = df.to_csv(index=False, encoding='utf-8-sig')
                            st.download_button("📥 交互日志", data=csv.encode('utf-8-sig'),
                                               file_name="research_logs.csv", mime="text/csv", key="dl_logs_top")
                    except:
                        st.warning("无日志")
                with col_dl2:
                    try:
                        resp = supabase.table("research_plans").select("*").execute()
                        if resp.data:
                            df = pd.DataFrame(resp.data)
                            csv = df.to_csv(index=False, encoding='utf-8-sig')
                            st.download_button("📥 方案数据", data=csv.encode('utf-8-sig'),
                                               file_name="research_plans.csv", mime="text/csv", key="dl_plans_top")
                    except:
                        st.warning("无方案")
            else:
                st.error("密码错误")
        else:
            st.caption("请输入密码")

st.markdown('</div>', unsafe_allow_html=True)

# ---- 下块：80% ----
st.markdown('<div class="bottom-block">', unsafe_allow_html=True)

# 左栏 (20%)
st.markdown('<div class="col-left">', unsafe_allow_html=True)
st.markdown("### ℹ️ 操作指引")
st.markdown("""
- 在顶部输入被试编号后，即可开始AI对话。
- 中栏为AI交互区，您可以提问、上传文档，并选择行为按钮。
- 右栏为研究方案填写区，请根据与AI的交互成果提炼填写。
- 所有数据会自动保存至数据库。
""")
st.markdown('</div>', unsafe_allow_html=True)

# 中栏 (45%)
st.markdown('<div class="col-mid">', unsafe_allow_html=True)

if st.session_state.participant_id and not st.session_state.state_loaded:
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

st.markdown("### 💬 AI 学术助手对话")
if not st.session_state.participant_id:
    st.warning("请先在顶部输入被试编号")
else:
    for msg in st.session_state.messages:
        if msg["role"] != "system":
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    with st.form(key="prompt_form", clear_on_submit=True):
        user_input = st.text_area(
            "提示词",
            height=80,
            key="prompt_input_mid",
            label_visibility="collapsed",
            placeholder="请输入您的科研问题..."
        )
        uploaded_file = st.file_uploader(
            "上传文档",
            type=["pdf", "docx"],
            help="支持 PDF 或 Word",
            key="file_uploader_mid",
            label_visibility="collapsed"
        )
        if uploaded_file is not None:
            st.caption(f"已选：{uploaded_file.name}")

        st.markdown("👇 **行为按钮**")
        col_b1, col_b2, col_b3, col_b4, col_b5 = st.columns(5)
        clicked = None
        if col_b1.form_submit_button("获取基础信息"): clicked = "获取基础信息"
        elif col_b2.form_submit_button("规范语言/格式"): clicked = "规范语言/格式"
        elif col_b3.form_submit_button("微调研究逻辑"): clicked = "微调研究逻辑"
        elif col_b4.form_submit_button("重构研究方案"): clicked = "重构研究方案"
        elif col_b5.form_submit_button("拓展研究思路"): clicked = "拓展研究思路"

        if clicked:
            if not user_input or not user_input.strip():
                st.warning("⚠️ 请输入提示词")
                st.stop()

            file_content = ""
            if uploaded_file:
                fname = uploaded_file.name
                if fname.endswith(".pdf"):
                    try:
                        reader = PdfReader(uploaded_file)
                        for page in reader.pages:
                            text = page.extract_text()
                            if text:
                                file_content += text + "\n"
                    except Exception as e:
                        st.error(f"PDF解析失败：{e}")
                elif fname.endswith(".docx"):
                    try:
                        doc = docx.Document(uploaded_file)
                        for para in doc.paragraphs:
                            file_content += para.text + "\n"
                    except Exception as e:
                        st.error(f"Word解析失败：{e}")
                if file_content and len(file_content) > 5000:
                    file_content = file_content[:5000] + "\n...[截断]"

            full_msg = f"【文档内容】\n{file_content}\n\n【问题】\n{user_input}" if file_content else user_input

            with st.chat_message("user"):
                if file_content:
                    st.markdown(f"📎 已附加文档，提问：{user_input}")
                else:
                    st.markdown(f"**[{clicked}]** {user_input}")

            st.session_state.messages.append({"role": "user", "content": full_msg})

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
                        st.error(f"AI调用失败：{e}")
                        st.stop()
            st.session_state.messages.append({"role": "assistant", "content": ai_reply})
            st.session_state.round_count += 1

            log_data = {
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "participant_id": st.session_state.participant_id,
                "round": st.session_state.round_count,
                "user_prompt": user_input,
                "behavior_button": clicked,
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

st.markdown('</div>', unsafe_allow_html=True)

# 右栏 (35%)
st.markdown('<div class="col-right">', unsafe_allow_html=True)

st.markdown("### 📝 研究方案填写")
if not st.session_state.participant_id:
    st.warning("请先在顶部输入被试编号")
else:
    existing_plan = load_plan(st.session_state.participant_id)

    with st.form(key="plan_form"):
        st.markdown("**AI协同研究方案生成记录表**")
        st.caption("提炼成果并勾选主导行为")

        st.markdown("**1. 选题与理论切入点**")
        task1_text = st.text_area(
            "提炼（限150字）",
            value=existing_plan["task1_text"] if existing_plan else "",
            height=50,
            max_chars=150,
            key="task1_text_right",
            label_visibility="collapsed"
        )
        task1_button = st.radio(
            "行为按钮",
            options=["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"],
            index=(["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"].index(existing_plan["task1_button"]) if existing_plan and existing_plan["task1_button"] in ["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"] else 0),
            horizontal=True,
            key="task1_button_right",
            label_visibility="collapsed"
        )
        st.divider()

        st.markdown("**2. 实施步骤与工具设计**")
        task2_text = st.text_area(
            "提炼（限150字）",
            value=existing_plan["task2_text"] if existing_plan else "",
            height=50,
            max_chars=150,
            key="task2_text_right",
            label_visibility="collapsed"
        )
        task2_button = st.radio(
            "行为按钮",
            options=["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"],
            index=(["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"].index(existing_plan["task2_button"]) if existing_plan and existing_plan["task2_button"] in ["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"] else 0),
            horizontal=True,
            key="task2_button_right",
            label_visibility="collapsed"
        )
        st.divider()

        st.markdown("**3. 反思局限性与方案定稿**")
        task3_text = st.text_area(
            "提炼（限150字）",
            value=existing_plan["task3_text"] if existing_plan else "",
            height=50,
            max_chars=150,
            key="task3_text_right",
            label_visibility="collapsed"
        )
        task3_button = st.radio(
            "行为按钮",
            options=["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"],
            index=(["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"].index(existing_plan["task3_button"]) if existing_plan and existing_plan["task3_button"] in ["1.获取基础信息", "2.规范语言/格式", "3.微调逻辑", "4.重构方案", "5.拓展思路"] else 0),
            horizontal=True,
            key="task3_button_right",
            label_visibility="collapsed"
        )

        submitted = st.form_submit_button("📤 提交方案")
        if submitted:
            if not task1_text.strip() or not task2_text.strip() or not task3_text.strip():
                st.warning("请完整填写所有文本字段")
            else:
                ok = save_plan(
                    st.session_state.participant_id,
                    task1_text.strip(),
                    task1_button,
                    task2_text.strip(),
                    task2_button,
                    task3_text.strip(),
                    task3_button
                )
                if ok:
                    st.success("✅ 方案已提交/更新！")
                    st.rerun()
                else:
                    st.error("❌ 提交失败")

st.markdown('</div>', unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)
