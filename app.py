from pypdf import PdfReader
import docx
import streamlit as st
from openai import OpenAI
import pandas as pd
import datetime
import json
from supabase import create_client, Client
import time
import hashlib

# ================= 1. 核心配置区 =================
DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ================= 2. 系统提示词 =================
SYSTEM_PROMPT =""" 您是一个名为"全栈式教育研究学术助理"的高级AI。您的目标是深度辅助教育学领域的研究生完成真实、复杂的学术研究任务，而非简单地给出敷衍的现成答案。您需要展现出教育研究的专业性、批判性和逻辑性。
核心能力与任务模块：
1. 选题与文献发现：辅助梳理文献脉络，对比不同教育理论（如建构主义与行为主义），精准分析研究空白。
2. 研究规划与设计：从教育心理学、课程论等多重视角构建分析框架，对比个案研究、行动研究等方法的适用性。
3. 实施与数据采集：协助开发访谈提纲等收集工具，指出并规避表述偏差及伦理风险。
4. 数据分析与阐释：提供Python/R等统计脚本编写指引，深度解读统计结果与理论模型的深层逻辑，接受用户的逻辑纠错。
5. 论文撰写与润色：辅助母语润色，检查专业术语一致性，并模拟"严苛审稿人"视角提出批判性修改意见。
6. 传播、评估与伦理：辅助提炼实践建议，主动规避文化/性别等偏见，模拟同行质疑进行答辩演练。
互动规则：
- 拒绝单次终结：面对用户的宽泛问题，不要一次性给出全套方案，通过反问或追问引导用户思考。
- 启发大于代劳：当用户索要直接答案时，先给出框架和思路，鼓励用户多轮探讨。"""

# 初始欢迎语
INITIAL_GREETING = "您好！我是您的教育研究全栈助理 ICFER。我们将围绕 \"人工智能时代的教师教育与教师专业发展研究\" 这一主题，结合您的学科专长，一起完成一份实证研究设计方案。请告诉我，您想从哪个具体的研究切入点开始？"

# ================= 3. 状态持久化函数 =================
def load_participant_state(pid):
    """
    从数据库加载被试状态：
    - 从 research_logs 按时间戳顺序重建完整消息列表
    - 与 participant_state 存储的消息对比，若一致则直接使用，否则重建并更新
    - 始终返回 (messages, round_count)
    """
    messages = get_initial_messages()
    round_count = 0

    try:
        # 1. 从 research_logs 获取所有有效日志（按时间戳升序）
        log_resp = supabase.table("research_logs")\
            .select("*")\
            .eq("participant_id", pid)\
            .order("timestamp", desc=False)\
            .execute()
        log_data = log_resp.data if log_resp.data else []

        # 统计有效轮数（有效行为 + 非空输入）
        valid_behaviors = ["获取基础信息", "规范语言/格式", "微调研究逻辑", "重构研究方案", "拓展研究思路"]
        round_count = sum(1 for log in log_data
                          if log.get("behavior_button") in valid_behaviors
                          and log.get("user_prompt")
                          and log.get("user_prompt").strip() != "")

        # 2. 重建消息列表（系统消息 + 所有有效日志的 user/assistant 对）
        rebuilt = [{"role": "system", "content": SYSTEM_PROMPT}]
        for log in log_data:
            if log.get("behavior_button") in valid_behaviors and log.get("user_prompt") and log.get("user_prompt").strip() != "":
                user_content = log["user_prompt"]
                ai_content = log.get("ai_response", "")
                rebuilt.append({"role": "user", "content": user_content})
                if ai_content:
                    rebuilt.append({"role": "assistant", "content": ai_content})
                else:
                    rebuilt.append({"role": "assistant", "content": "(AI响应缺失，请检查日志)"})
        if len(rebuilt) == 1:
            messages = get_initial_messages()
        else:
            messages = rebuilt

        # 3. 尝试从 participant_state 加载存储的消息，并比较是否一致
        state_resp = supabase.table("participant_state").select("*").eq("participant_id", pid).execute()
        if state_resp.data:
            raw = json.loads(state_resp.data[0]["messages"]) if state_resp.data[0]["messages"] else []
            if raw:
                stored_user_msgs = [msg for msg in raw if msg["role"] == "user"]
                if len(stored_user_msgs) == round_count:
                    if raw[0].get("role") != "system":
                        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + raw
                    else:
                        messages = raw
                else:
                    save_participant_state(pid, messages, round_count)
            else:
                save_participant_state(pid, messages, round_count)
        else:
            save_participant_state(pid, messages, round_count)

    except Exception as e:
        st.error(f"⚠️ 加载被试 {pid} 数据失败，请检查网络或刷新重试。错误详情：{e}")
        messages = get_initial_messages()
        round_count = 0

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
        {"role": "assistant", "content": INITIAL_GREETING}
    ]

# ================= 新增：知情同意保存函数（含哈希） =================
# 同意书正文（用于生成 SHA-256 哈希）
CONSENT_TEXT = """研究主题：人工智能辅助教育研究的特征与机制研究

您已完成本研究的问卷阶段。本页为研究第二阶段的补充知情说明，请您阅读后决定是否继续参与人机交互任务。

尊敬的参与者，您好！我们是陕西师范大学教育学部的科研团队，诚挚地邀请您参与我们的研究项目。在您点击"同意"按钮之前，请务必仔细阅读以下内容，以确保您充分了解本研究的目的、流程、潜在风险与收益，以及您的各项权利。如有任何疑问，欢迎随时与我们联系。

一、这项研究是关于什么的？
本研究致力于探索教育学及相关专业的硕士、博士研究生在实际科研工作中如何与生成式人工智能（AI）协同工作。我们将通过观察您与 AI 共同完成一项研究设计任务的过程，来分析您的行为模式、思维过程及主观感受。最终，本研究的成果将有助于制定更负责任、更可解释的 AI 使用指南，为高校和相关机构的科研培训提供依据。
本次实验的具体任务：您将与我们的智能研究助理 ICFER 进行大约 100 分钟 的深度对话。
在对话中，您将围绕统一主题 "人工智能时代的教师教育与教师专业发展研究" ，结合您自身的学科专长（如学科教学、教育技术、教育管理等），从中选定一个具体的研究切入点，并在 ICFER 的辅助下构思并完成一份完整的实证研究设计方案。
特别说明：这项设计任务是实验环节中的一次模拟任务，您所完成的设计方案仅用于本研究分析，不会用于课程评价、科研考核、职称评定或真实学术成果提交。

二、参与过程会发生什么？
深度人机对话、方案构思与生成、数据自动记录。

三、我的数据会被怎么处理？
用途限定、匿名化处理（去标识化）、安全存储、信息保密与销毁、学术诚信保护、对话内容的编码分析、与前期数据的关联。

四、参与这项研究有什么风险或收益吗？
最低风险的社会科学研究；心理风险、信息安全风险、身体风险；潜在收益。

五、我可以随时退出吗？
当然可以。参与本研究完全基于您的自愿原则。

六、研究成果会分享给我吗？
会的。研究结束后，我们承诺在不泄露个人隐私的前提下，向有需要的参与者分享总体研究发现摘要。

七、如有疑问可以联系谁？
研究负责人：周榕 副教授（陕西师范大学教育学部）
联系邮箱：rzhou@snnu.edu.cn
联系电话：13309296061"""

def save_consent_record(pid):
    """
    将知情同意记录写入 consent_records 表（含同意书正文哈希）
    """
    if not pid or pid.strip() == "":
        return False
    try:
        # 生成同意书正文的 SHA-256 哈希
        consent_hash = hashlib.sha256(CONSENT_TEXT.encode("utf-8")).hexdigest()

        data = {
            "participant_id": pid.strip(),
            "consent_timestamp": datetime.datetime.now().isoformat(),
            "consent_version": "v1.0_ICFER_2026",
            "consent_hash": consent_hash
        }
        supabase.table("consent_records").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"⚠️ 保存同意记录失败：{e}")
        return False

# ================= 4. 方案数据函数（6个子任务） =================
def load_plan(pid):
    try:
        response = supabase.table("research_plans").select("*").eq("participant_id", pid).execute()
        if response.data:
            plan = response.data[0]
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
st.set_page_config(page_title="教育实证研究全周期智能协同框架", page_icon="📘", layout="wide")

# 强制初始化所有 session_state 变量
if "participant_id" not in st.session_state:
    st.session_state.participant_id = ""
if "messages" not in st.session_state:
    st.session_state.messages = None  # 修改为 None，确保第一次加载
if "round_count" not in st.session_state:
    st.session_state.round_count = 0
if "prompt_input" not in st.session_state:
    st.session_state.prompt_input = ""
if "show_exit_dialog" not in st.session_state:
    st.session_state.show_exit_dialog = False
if "consent_given" not in st.session_state:
    st.session_state.consent_given = False
if "experiment_completed" not in st.session_state:
    st.session_state.experiment_completed = False
if "user_role" not in st.session_state:
    st.session_state.user_role = None
if "export_authorized" not in st.session_state:
    st.session_state.export_authorized = False

# ================= 角色判断（使用 URL 参数控制） =================
query_params = st.query_params
if "mode" in query_params and query_params["mode"] == "admin":
    st.session_state.user_role = "研究者"
else:
    # 如果已经选择过角色，则保留，否则默认被试
    if st.session_state.user_role is None:
        st.session_state.user_role = "被试"

# ================= 6. CSS =================
st.markdown(
    """
    <style>
        /* 顶部固定栏 */
        .top-fixed {
            position: sticky;
            top: 0;
            background-color: white;
            z-index: 100;
            padding: 0.2rem 1rem 0.2rem 0.5rem;
            border-bottom: none !important;
            box-shadow: none !important;
        }
        .top-fixed .stColumn {
            border-right: none !important;
        }

        /* 主布局 */
        [data-testid="stHorizontalBlock"] {
            gap: 6 !important;
        }
        [data-testid="stHorizontalBlock"] .stColumn {
            border-left: none !important;
            border-right: none !important;
            box-shadow: none !important;
            background: transparent !important;
            padding: 0 1px !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: flex-start !important;
            align-items: stretch !important;
        }
        [data-testid="stHorizontalBlock"] .stColumn::before,
        [data-testid="stHorizontalBlock"] .stColumn::after {
            content: none !important;
            display: none !important;
        }
        [data-testid="stHorizontalBlock"] .stColumn .stButton {
            border: none !important;
        }

        /* 按钮样式 */
        .stButton button,
        .stButton button p,
        .stButton button div,
        .stButton button span,
        .stForm button[type="submit"],
        .stForm button[type="submit"] p,
        .stForm button[type="submit"] div,
        .stForm button[type="submit"] span {
            font-size: 14px !important;
            line-height: 1.2 !important;
            white-space: nowrap !important;
        }
        .stButton button,
        .stForm button[type="submit"] {
            height: 38px !important;
            min-height: 38px !important;
            max-height: 38px !important;
            width: 100% !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            padding: 0 4px !important;
            text-align: center !important;
        }
        .stButton {
            height: 38px !important;
            display: flex !important;
            align-items: center !important;
        }

        /* ========== 左右两栏标题颜色 ========== */
        /* 左栏标题：研究人机交互区 */
        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn:first-child h3 {
            color: #1565c0 !important;
        }
        /* 右栏标题：研究方案填写区 */
        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn:last-child h3 {
            color: #2e7d32 !important;
        }

        /* 知情同意书卡片样式 */
        .consent-card {
            background: linear-gradient(145deg, #ffffff, #f5f7fa);
            padding: 30px 35px;
            border-radius: 16px;
            border: 1px solid #e0e5ec;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            margin: 10px 0;
            max-width: 1000px;
            margin-left: auto;
            margin-right: auto;
            text-align: left;
        }
        .consent-card h2 {
            text-align: center;
            color: #1a2a3a;
            font-size: 26px;
            font-weight: 600;
            margin-top: 0;
            margin-bottom: 20px;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 12px;
        }
        .consent-card p {
            font-size: 15.5px;
            line-height: 1.7;
            color: #2d3748;
            margin: 8px 0;
        }
        .consent-card ul {
            padding-left: 22px;
            font-size: 15.5px;
            line-height: 1.7;
            color: #2d3748;
        }
        .consent-card .highlight {
            background-color: #f0f8ff;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 500;
            color: #1a5276;
        }
        .consent-card .contact-box {
            background-color: #eaf4eb;
            padding: 10px 16px;
            border-radius: 8px;
            border-left: 4px solid #4CAF50;
            margin: 12px 0 8px 0;
        }
        .consent-card .footer-note {
            text-align: center;
            font-size: 15px;
            font-weight: 500;
            color: #1a3a5a;
            margin-top: 20px;
            padding-top: 16px;
            border-top: 1px dashed #b0c4de;
        }

        /* 分隔线样式 */
        .stDivider hr {
            margin-top: 1px !important;
            margin-bottom: 1px !important;
        }
        hr {
            margin-top: 4px !important;
            margin-bottom: 4px !important;
        }

        /* 子任务区域样式 */
        [data-testid="stVerticalBlock"] > .stMarkdown {
            margin-bottom: 2px !important;
        }
        [data-testid="stTextArea"] {
            margin-bottom: 2px !important;
        }
        .task-odd, .task-even {
            padding: 8px 16px !important;
            margin-bottom: 4px !important;
        }
        .task-odd .stTextArea, .task-even .stTextArea {
            margin-bottom: 0 !important;
        }

        /* 输入框内嵌上传图标 */
        .st-key-input_wrapper {
            position: relative;
        }
        .st-key-input_wrapper textarea {
            padding-right: 46px !important;
            padding-bottom: 42px !important;
        }
        .st-key-input_wrapper [data-testid="stFileUploader"] {
            position: absolute;
            right: 10px;
            bottom: 18px;
            width: 34px;
            height: 34px;
            z-index: 30;
            overflow: hidden;
        }
        .st-key-input_wrapper [data-testid="stFileUploader"] label,
        .st-key-input_wrapper [data-testid="stFileUploader"] [data-testid="stTooltipIcon"] {
            display: none !important;
        }
        .st-key-input_wrapper [data-testid="stFileUploaderDropzone"] {
            background: transparent !important;
            border: none !important;
            padding: 0 !important;
            margin: 0 !important;
            min-height: 34px !important;
            height: 34px !important;
            width: 34px !important;
        }
        .st-key-input_wrapper [data-testid="stFileUploaderDropzone"] > div:first-child {
            display: none !important;
        }
        .st-key-input_wrapper [data-testid="stFileUploaderDropzone"] button {
            width: 34px !important;
            height: 34px !important;
            min-height: 34px !important;
            padding: 0 !important;
            border-radius: 50% !important;
            background-color: transparent !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: transparent !important;
            position: relative;
        }
        .st-key-input_wrapper [data-testid="stFileUploaderDropzone"] button:hover {
            background-color: rgba(0, 0, 0, 0.06) !important;
        }
        .st-key-input_wrapper [data-testid="stFileUploaderDropzone"] button::after {
            content: "📎";
            font-size: 15px;
            color: #333;
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
        }
        [data-testid="InputInstructions"] {
            visibility: hidden !important;
            color: transparent !important;
            opacity: 0 !important;
        }

        /* ========== 左侧聊天区域样式 ========== */
        .chat-container {
            display: flex;
            flex-direction: column;
            height: calc(100vh - 200px);
            position: relative;
        }

        .messages-container {
            flex-grow: 1;
            overflow-y: auto;
            padding-right: 8px;
            margin-bottom: 10px;
        }

        .input-container {
            position: sticky;
            bottom: 0;
            background-color: white;
            padding-top: 10px;
            border-top: 1px solid #e2e5ea;
            z-index: 10;
        }

        .st-key-unified_chat_box {
            border: 1px solid #e2e5ea;
            border-radius: 14px;
            background-color: #fafbfc;
            padding: 16px 18px;
            margin-bottom: 4px;
            height: 100%;
            display: flex;
            flex-direction: column;
        }

        .st-key-unified_chat_box [data-testid="stChatMessage"] {
            margin-bottom: 6px !important;
        }

        /* 左右两栏高度控制 */
        .st-key-main_row [data-testid="stHorizontalBlock"] {
            align-items: flex-start !important;
            height: auto !important;
            overflow: visible !important;
        }
        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn {
            max-height: calc(100vh - 180px) !important;
            overflow-y: auto !important;
            padding: 10px !important;
        }
        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn:first-child {
            padding-right: 14px !important;
        }
        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn:last-child {
            border-left: 1px solid #ddd;
            padding-left: 14px !important;
            background-color: transparent !important;
        }
        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn::-webkit-scrollbar {
            width: 6px;
        }
        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 5px;
        }
        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn::-webkit-scrollbar-thumb {
            background: #888;
            border-radius: 5px;
        }
        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn::-webkit-scrollbar-thumb:hover {
            background: #555;
        }

        /* 滚动条样式 */
        ::-webkit-scrollbar {
            width: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb {
            background: #888;
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #555;
        }
        /* 右侧方案区：输入框 label 与输入内容字号 */
        [data-testid="stTextArea"] label p {
            font-size: 16px !important;
            font-weight: 600 !important;
        }
        [data-testid="stTextArea"] textarea {
            font-size: 16px !important;
        }
        /* 右侧方案区：markdown 小标题字号 */
        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn:last-child [data-testid="stMarkdownContainer"] p {
            font-size: 16px !important;
        }

        /* ========== 子任务输入框背景色（按 key 定位） ========== */
        .st-key-task1_text textarea { background-color: #e6f3ff; }
        .st-key-task2_text textarea { background-color: #f5e6ff; }
        .st-key-task3_text textarea { background-color: #e6f3ff; }
        .st-key-task4_text textarea { background-color: #f5e6ff; }
        .st-key-task5_text textarea { background-color: #e6f3ff; }
        .st-key-task6_text textarea { background-color: #f5e6ff; }
    </style>
    """,
    unsafe_allow_html=True
)

# ================= 7. 固定顶部栏（标题） =================
st.markdown('<div class="top-fixed">', unsafe_allow_html=True)
st.markdown(
    """
    <div style="text-align: center;">
        <h1 style="font-size: 36px; margin-bottom: 0;">🎓 教育实证研究全周期智能协同框架</h1>
        <p style="font-size: 20px; color: #555; margin-top: 4px;">Intelligent Collaborative Framework for Empirical Research in Education (ICFER)</p>
    </div>
    """,
    unsafe_allow_html=True
)
st.markdown('</div>', unsafe_allow_html=True)

# ================= 8. 根据角色显示内容 =================
if st.session_state.user_role == "研究者":
    # ---------- 研究者模式 ----------
    col_space1, col_center, col_space2 = st.columns([1, 2, 1])
    with col_center:
        st.markdown("<h3 style='text-align: center;'>📊 研究者数据导出</h3>", unsafe_allow_html=True)
        st.markdown(
            "<p style='text-align: center;'>请输入研究者密码以查看并下载数据</p>",
            unsafe_allow_html=True
        )
        if not st.session_state.export_authorized:
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                export_pass = st.text_input(
                    "密码",
                    type="password",
                    key="export_pass",
                    label_visibility="collapsed",
                    placeholder="请输入密码"
                )
            col_btn1, col_btn2, col_btn3 = st.columns([2, 1, 2])
            with col_btn2:
                if st.button("验证", key="verify_export", use_container_width=True):
                    if export_pass == st.secrets.get("RESEARCHER_PASSWORD", "MyPassword123"):
                        st.session_state.export_authorized = True
                        st.rerun()
                    else:
                        st.error("密码错误")
        else:
            st.success("✅ 已授权，可下载数据")
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
                        key="dl_logs",
                        use_container_width=True
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
                        key="dl_plans",
                        use_container_width=True
                    )
            except Exception as e:
                st.error(f"读取方案数据失败：{e}")
            # 下载知情同意记录
            try:
                response_consent = supabase.table("consent_records").select("*").execute()
                if response_consent.data:
                    df_consent = pd.DataFrame(response_consent.data)
                    csv_consent = df_consent.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                        label="📥 下载知情同意记录",
                        data=csv_consent.encode('utf-8-sig'),
                        file_name="consent_records.csv",
                        mime="text/csv",
                        key="dl_consent",
                        use_container_width=True
                    )
            except Exception as e:
                st.warning(f"读取同意记录失败：{e}")
            if st.button("退出研究者模式", use_container_width=True):
                st.session_state.export_authorized = False
                st.query_params.clear()
                st.rerun()

else:
    # ---------- 被试模式 ----------

    # 【1】检查实验是否已完成
    if st.session_state.experiment_completed:
        st.markdown(
            """
            <div style="text-align: center; padding: 40px 20px;">
                <h2 style="color: #4CAF50;">✅ 方案已提交成功！实验已完成！</h2>
                <p style="font-size: 18px;">感谢您参与本次研究！您的数据已成功保存。</p>
                <p style="font-size: 16px; color: #666;">您现在可以关闭此页面，或点击下方按钮返回首页。</p>
                <br>
            </div>
            """,
            unsafe_allow_html=True
        )
        col_btn_left, col_btn_center, col_btn_right = st.columns([1, 1, 1])
        with col_btn_center:
            if st.button("🏠 返回首页", use_container_width=True):
                st.session_state.consent_given = False
                st.session_state.participant_id = ""
                st.session_state.messages = None
                st.session_state.round_count = 0
                st.session_state.show_exit_dialog = False
                st.session_state.experiment_completed = False
                st.rerun()
        st.stop()

    # 【2】先检查是否输入了 Participant ID
    if not st.session_state.participant_id:
        st.markdown(
            """
            <div style="text-align: center; padding: 20px 20px;">   
                <p style="font-size: 18px; color: #555; margin-bottom: 30px;">👤 欢迎参与研究！请输入研究者分配给您的编号以开始实验。输入编号后，您将阅读并签署知情同意书。</p>
            </div>
            """,
            unsafe_allow_html=True
        )
        col_space1, col_id, col_space2 = st.columns([3, 1, 3])
        with col_id:
            pid_input = st.text_input(
                "研究编号",
                key="pid_input_start",
                label_visibility="collapsed",
                placeholder="例如：P001"
            )
            if pid_input and pid_input.strip():
                st.session_state.participant_id = pid_input.strip()
                # 立即加载历史数据
                st.session_state.messages, st.session_state.round_count = load_participant_state(st.session_state.participant_id)
                st.rerun()
        st.stop()

    # 【3】再检查是否已同意
    if not st.session_state.consent_given:
        # 显示当前参与者编号
        st.markdown(
            "<p style='text-align: center; font-size: 16px; color: #555;'>"
            f"当前参与者编号：<strong>{st.session_state.participant_id}</strong>"
            "</p>",
            unsafe_allow_html=True
        )

        st.markdown(
            """
            <div class="consent-card">
                <h2>📋 知情同意书</h2>
                <p style="text-align:center; color:#888; font-size:13px; margin-top:-10px;">版本号：v1.0_ICFER_2026　|　生效日期：2026-09-20</p>
                <p><strong>研究主题：人工智能辅助教育研究的特征与机制研究</strong></p>
                 <p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;您已完成本研究的问卷阶段。本页为研究第二阶段的补充知情说明，请您阅读后决定是否继续参与人机交互任务。</p>
<p><strong></strong><br</p>
                <p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;尊敬的参与者，您好！我们是陕西师范大学教育学部的科研团队，诚挚地邀请您参与我们的研究项目。在您点击"同意"按钮之前，请务必仔细阅读以下内容，以确保您充分了解本研究的目的、流程、潜在风险与收益，以及您的各项权利。如有任何疑问，欢迎随时与我们联系。</p>
<p><strong></strong><br</p>
                <p><strong>一、这项研究是关于什么的
