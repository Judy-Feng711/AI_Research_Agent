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

INITIAL_GREETING = "您好！我是您的教育研究全栈助理 ICFER。我们将围绕 \"人工智能时代的教师教育与教师专业发展研究\" 这一主题，结合您的学科专长，一起完成一份实证研究设计方案。请告诉我，您想从哪个具体的研究切入点开始？"

# ================= 3. 状态持久化函数 =================
def load_participant_state(pid):
    messages = get_initial_messages()
    round_count = 0
    try:
        log_resp = supabase.table("research_logs")\
            .select("*")\
            .eq("participant_id", pid)\
            .order("timestamp", desc=False)\
            .execute()
        log_data = log_resp.data if log_resp.data else []
        valid_behaviors = ["获取基础信息", "规范语言/格式", "微调研究逻辑", "重构研究方案", "拓展研究思路"]
        round_count = sum(1 for log in log_data
                          if log.get("behavior_button") in valid_behaviors
                          and log.get("user_prompt")
                          and log.get("user_prompt").strip() != "")
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
    if not pid or pid.strip() == "":
        return False
    try:
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

st.set_page_config(page_title="教育实证研究全周期智能协同框架", page_icon="📘", layout="wide")

if "participant_id" not in st.session_state:
    st.session_state.participant_id = ""
if "messages" not in st.session_state:
    st.session_state.messages = None
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

query_params = st.query_params
if "mode" in query_params and query_params["mode"] == "admin":
    st.session_state.user_role = "研究者"
else:
    if st.session_state.user_role is None:
        st.session_state.user_role = "被试"

st.markdown(
    """
    <style>
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

        .stButton button,
        .stButton button p,
        .stButton button div,
        .stButton button span,
        .stForm button[type="submit"],
        .stForm button[type="submit"] p,
        .stForm button[type="submit"] div,
        .stForm button[type="submit"] span {
            font-size: 16px !important;
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

        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn:first-child h3 {
            color: #1565c0 !important;
        }
        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn:last-child h3 {
            color: #2e7d32 !important;
        }

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

        .stDivider hr {
            margin-top: 1px !important;
            margin-bottom: 1px !important;
        }
        hr {
            margin-top: 4px !important;
            margin-bottom: 4px !important;
        }

        [data-testid="stVerticalBlock"] > .stMarkdown {
            margin-bottom: 2px !important;
        }
        [data-testid="stTextArea"] {
            margin-bottom: 2px !important;
        }

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

        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3) {
            align-items: flex-start !important;
            height: auto !important;
            overflow: visible !important;
        }
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn {
            max-height: calc(100vh - 180px) !important;
            overflow-y: auto !important;
            padding: 10px !important;
            border: none !important;
            border-radius: 12px !important;
            box-sizing: border-box !important;
        }
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn:first-child {
            padding-right: 14px !important;
            background-color: #f8fbff !important;
            box-shadow: 0 2px 8px rgba(21, 101, 192, 0.04) !important;
        }
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn:last-child {
            padding-left: 14px !important;
            background-color: #f9fdf9 !important;
            border-left: none !important;
            box-shadow: 0 2px 8px rgba(46, 125, 50, 0.04) !important;
        }
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn::-webkit-scrollbar {
            width: 6px;
        }
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn::-webkit-scrollbar-track {
            background: transparent;
            border-radius: 5px;
        }
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn::-webkit-scrollbar-thumb {
            background: #aab2bd;
            border-radius: 5px;
        }
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn::-webkit-scrollbar-thumb:hover {
            background: #7b8794;
        }

        .st-key-main_row
        [data-testid="stHorizontalBlock"]
        [data-testid="stHorizontalBlock"]
        > div.stColumn {
            max-height: none !important;
            overflow: visible !important;
            padding: 0 1px !important;
            background: transparent !important;
            border: none !important;
            border-radius: 0 !important;
            box-shadow: none !important;
        }

        .st-key-main_row .stForm button[type="submit"] {
            min-width: 0 !important;
            width: 100% !important;
            height: 38px !important;
            font-size: 13px !important;
            line-height: 1.2 !important;
            padding-left: 2px !important;
            padding-right: 2px !important;
            white-space: nowrap !important;
            overflow: visible !important;
            text-overflow: clip !important;
        }
        .st-key-main_row .stForm button[type="submit"] p,
        .st-key-main_row .stForm button[type="submit"] span,
        .st-key-main_row .stForm button[type="submit"] div {
            font-size: 13px !important;
            max-width: none !important;
            overflow: visible !important;
            text-overflow: clip !important;
            white-space: nowrap !important;
            word-break: keep-all !important;
        }

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
        [data-testid="stTextArea"] label p {
            font-size: 16px !important;
            font-weight: 600 !important;
        }
        [data-testid="stTextArea"] textarea {
            font-size: 16px !important;
        }
        .st-key-main_row [data-testid="stHorizontalBlock"] > div.stColumn:last-child [data-testid="stMarkdownContainer"] p {
            font-size: 16px !important;
        }
        .st-key-task1_text textarea { background-color: #e6f3ff; }
        .st-key-task2_text textarea { background-color: #f5e6ff; }
        .st-key-task3_text textarea { background-color: #e6f3ff; }
        .st-key-task4_text textarea { background-color: #f5e6ff; }
        .st-key-task5_text textarea { background-color: #e6f3ff; }
        .st-key-task6_text textarea { background-color: #f5e6ff; }
        /* 五个行为按钮的文字样式完全统一 */
        /* 强制第4、第5个行为按钮文字样式一致 */
        .st-key-btn_rebuild_plan button,
        .st-key-btn_expand_idea button,
        .st-key-btn_rebuild_plan button p,
        .st-key-btn_expand_idea button p,
        .st-key-btn_rebuild_plan button span,
        .st-key-btn_expand_idea button span,
        .st-key-btn_rebuild_plan button div,
        .st-key-btn_expand_idea button div {
            font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif !important;
            font-size: 14px !important;
            font-weight: 400 !important;
            line-height: 1.2 !important;
            letter-spacing: 0 !important;
            white-space: nowrap !important;
        }
    </style>
    """,
    unsafe_allow_html=True
)

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

if st.session_state.user_role == "研究者":
    col_space1, col_center, col_space2 = st.columns([1, 2, 1])
    with col_center:
        st.markdown("<h3 style='text-align: center;'>📊 研究者数据导出</h3>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center;'>请输入研究者密码以查看并下载数据</p>", unsafe_allow_html=True)
        if not st.session_state.export_authorized:
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                export_pass = st.text_input("密码", type="password", key="export_pass", label_visibility="collapsed", placeholder="请输入密码")
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
                    c1, c2, c3 = st.columns([7, 4, 7])
                    with c2:
                        st.download_button(label="📥 下载交互日志", data=csv_data.encode('utf-8-sig'), file_name="research_logs.csv", mime="text/csv", key="dl_logs", use_container_width=True)
            except Exception as e:
                st.error(f"读取交互数据失败：{e}")
            try:
                response_plan = supabase.table("research_plans").select("*").execute()
                if response_plan.data:
                    df_plan = pd.DataFrame(response_plan.data)
                    csv_plan = df_plan.to_csv(index=False, encoding='utf-8-sig')
                    c1, c2, c3 = st.columns([7, 4, 7])
                    with c2:
                        st.download_button(label="📥 下载方案数据", data=csv_plan.encode('utf-8-sig'), file_name="research_plans.csv", mime="text/csv", key="dl_plans", use_container_width=True)
            except Exception as e:
                st.error(f"读取方案数据失败：{e}")
            try:
                response_consent = supabase.table("consent_records").select("*").execute()
                if response_consent.data:
                    df_consent = pd.DataFrame(response_consent.data)
                    csv_consent = df_consent.to_csv(index=False, encoding='utf-8-sig')
                    c1, c2, c3 = st.columns([7, 4, 7])
                    with c2:
                        st.download_button(label="📥 下载知情同意记录", data=csv_consent.encode('utf-8-sig'), file_name="consent_records.csv", mime="text/csv", key="dl_consent", use_container_width=True)
            except Exception as e:
                st.warning(f"读取同意记录失败：{e}")
            c1, c2, c3 = st.columns([7, 4, 7])
            with c2:
                if st.button("退出研究者模式", use_container_width=True):
                    st.session_state.export_authorized = False
                    st.query_params.clear()
                    st.rerun()
else:
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
            pid_input = st.text_input("研究编号", key="pid_input_start", label_visibility="collapsed", placeholder="例如：P001")
            if pid_input and pid_input.strip():
                st.session_state.participant_id = pid_input.strip()
                st.session_state.messages, st.session_state.round_count = load_participant_state(st.session_state.participant_id)
                st.rerun()
        st.stop()

    if not st.session_state.consent_given:
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
                <p><strong>一、这项研究是关于什么的？</strong></p>
                <p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;本研究致力于探索教育学及相关专业的硕士、博士研究生在实际科研工作中如何与生成式人工智能（AI）协同工作。我们将通过观察您与 AI 共同完成一项研究设计任务的过程，来分析您的行为模式、思维过程及主观感受。最终，本研究的成果将有助于制定更负责任、更可解释的 AI 使用指南，为高校和相关机构的科研培训提供依据。</p>
                <p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<strong>本次实验的具体任务</strong>：您将与我们的智能研究助理 <strong>ICFER（教育实证研究全周期智能协同框架，Intelligent Collaborative Framework for Empirical Research in Education）</strong> 进行大约 <strong>100 分钟</strong> 的深度对话。</p>
                <p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;在对话中，您将围绕统一主题 <strong>"人工智能时代的教师教育与教师专业发展研究"</strong> ，结合您自身的学科专长（如学科教学、教育技术、教育管理等），从中选定一个具体的研究切入点，并在 ICFER 的辅助下构思并完成一份完整的实证研究设计方案。</p>
                <p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<em>特别说明</em>：这项设计任务是实验环节中的一次模拟任务，您所完成的设计方案仅用于本研究分析，不会用于课程评价、科研考核、职称评定或真实学术成果提交。实验中使用的材料均为统一编撰并经过脱敏处理，不要求您提交个人真实论文、未公开数据、评审材料或其他涉及个人、单位及科研保密的信息。</p>
<p><strong></strong><br</p>
                <p><strong>二、参与过程会发生什么？</strong></p>
                <ul>
                    <li><strong>深度人机对话</strong>：您将与 ICFER 围绕上述统一主题下您所聚焦的具体研究问题进行自由、深入的探讨。ICFER 会尝试辅助您梳理思路、提供建议、完善研究设计。</li>
                    <li><strong>方案构思与生成</strong>：在 ICFER 的辅助下，您需要在系统中逐步填写研究设计的关键要素（如研究问题、研究方法、数据收集与分析计划等），最终形成一份属于您自己的研究方案初稿。</li>
                    <li><strong>数据自动记录</strong>：为了科学研究，您与 ICFER 的<strong>完整对话日志</strong>，以及您在各阶段填写的研究要点将被系统自动记录，这些信息共同构成您的研究方案记录。</li>
                </ul>
<p><strong></strong><br</p>
                <p><strong>三、我的数据会被怎么处理？安全吗？</strong></p>
                <p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;我们深知您学术成果与个人隐私的重要性，并承诺采取最高标准的保护措施。所有数据将严格遵循科研伦理规范进行处理：</p>
                <ul>
                    <li><strong>用途限定</strong>：所有收集的数据<strong>仅用于本项目的学术分析</strong>，不会用于任何商业目的，也不会被用于训练 AI 模型。</li>
                    <li><strong>匿名化处理（去标识化）</strong>：在分析前，所有数据（包括对话日志）都将进行严格的匿名化处理，即删除您的姓名、联系方式、单位等可直接识别您身份的信息。最终公开发表的研究成果中，仅会呈现无法识别个体的引语或任务示例。</li>
                    <li><strong>安全存储</strong>：原始电子数据将加密存储于受权限控制的学校服务器或加密存储设备中。</li>
                    <li><strong>信息保密与销毁</strong>：我们承诺，未经您的单独同意，绝不会向任何合作单位、AI 平台供应商或无关第三方提供可识别您的数据。所有原始数据将在研究完成后（预计<strong>3 年内</strong>）进行彻底销毁。</li>
                    <li><strong>学术诚信保护</strong>：本项目的研究结果<strong>不会</strong>用于任何形式的个人能力排名、心理诊断、学术不端判定、导师评价或职称考核。</li>
                    <li><strong>对话内容的编码分析</strong>：您与 ICFER 的对话文本，将在数据收集完成后，由研究人员依据国际通用认知框架进行编码分析，用于识别对话的认知层次与协同模式。编码仅针对对话内容本身，不针对您个人做任何能力评价。</li>
                    <li><strong>与前期数据的关联</strong>：您在本阶段获得的编号，将用于将您的对话数据与您此前参与研究时产生的数据进行关联分析。您报名时留下的联系方式仅用于研究协调与邀请，不会与您的对话数据一并存储。在数据分析开始前，联系方式将被删除，仅保留随机编号。</li>
                </ul>
<p><strong></strong><br</p>
                <p><strong>四、参与这项研究有什么风险或收益吗？</strong></p>
                <ul>
                    <li><strong>风险评估（我们如何保障您的权益）</strong>：
                        <ul>
                            <li>本项目属于最低风险的社会科学研究，不涉及任何药物、侵入性操作或身体伤害。</li>
                            <li><strong>心理风险</strong>：您可能会在接触 AI 不完美的回答、或反思自身对 AI 的依赖时，产生短暂的紧张、挫败或疲劳感。研究团队的任务设计采用中性、非评判性表述，研究人员不会对您的表现做任何负面评价。若您出现明显不适，我们将立即提供休息和解释。</li>
                            <li><strong>信息安全风险</strong>：为保障您的科研信息安全，请<strong>勿</strong>在研究过程中向 AI 输入您未发表的论文正文、未公开数据、评审材料或带有单位信息的保密内容。确需使用 AI 平台时，请避免输入真实姓名、联系方式、未公开研究成果、个人敏感信息、保密数据或具有识别性的他人资料。</li>
                            <li><strong>身体风险</strong>：主要为长时间使用电脑带来的常规用眼疲劳或久坐不适，建议您适时休息。</li>
                        </ul>
                    </li>
                    <li><strong>您的潜在收益</strong>：
                        <ul>
                            <li>您将获得一次深度的、前沿的 AI 辅助科研体验。</li>
                            <li>您将免费获得一份由您与 ICFER 共同完成的、<strong>为您量身定制的研究设计方案初稿</strong>，这对您未来的研究可能具有参考价值。</li>
                        </ul>
                    </li>
                </ul>
<p><strong></strong><br</p>
                <p><strong>五、我可以随时退出吗？</strong></p>
                <p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<strong>当然可以。</strong> 参与本研究完全基于您的自愿原则。</p>
                <ul>
                    <li>在实验过程中，如果您感到任何不适或希望终止，可随时点击界面正下方的 <strong>"退出实验"</strong> 按钮。</li>
                    <li>退出后，系统将立即停止数据记录。您已产生的对话日志将不再纳入后续数据分析。若您希望删除已记录的数据，可通过研究负责人邮箱提出，我们将在数据匿名化前为您删除。退出不会对您产生任何不利影响。</li>
                    <li>如果数据已完成匿名化并进入汇总分析，届时删除可能受限，这一点我们会在研究中提前说明。</li>
                </ul>
<p><strong></strong><br</p>
                <p><strong>六、研究成果会分享给我吗？</strong></p>
                <p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<strong>会的。</strong> 研究结束后，我们承诺在不泄露个人隐私的前提下，通过电子邮件等方式向有需要的参与者分享一份总体研究发现摘要，以及负责任使用 AI 的实践建议。如您希望接收，可通过研究负责人邮箱与我们联系。</p>
<p><strong></strong><br</p>
                <p><strong>七、如有疑问可以联系谁？</strong></p>
                <div class="contact-box">
                    <p>如果您对本次研究有任何疑问、顾虑，或在参与过程中遇到任何问题，欢迎随时联系我们的研究负责人：</p>
                    <ul>
                        <li><strong>研究负责人</strong>：周榕 副教授（陕西师范大学教育学部）</li>
                        <li><strong>联系邮箱</strong>：rzhou@snnu.edu.cn</li>
                        <li><strong>联系电话</strong>：13309296061</li>
                    </ul>
                </div>
<p><strong></strong><br</p>
                <div class="footer-note">点击下方"同意"即表示您已阅读并理解上述内容，自愿参与本研究。<br>系统将在您点击同意后自动记录同意时间戳。</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        col_center_btn = st.columns([3, 1, 3])[1]
        with col_center_btn:
            if st.button("✅ 我同意并参与实验", use_container_width=True):
                st.session_state.consent_given = True
                save_consent_record(st.session_state.participant_id)
                st.rerun()
        st.stop()

    if st.session_state.show_exit_dialog:
        w1, w2, w3 = st.columns([1, 2, 1])
        with w2:
            st.warning("您确定要退出实验吗？退出后，您本次实验的所有数据将不会被纳入最终数据分析。")
        col_l, col_yes, col_no, col_r = st.columns([4, 1, 1, 4])
        with col_yes:
            if st.button("确认退出", key="confirm_exit_yes", use_container_width=True):
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
                    st.toast("✅ 已记录退出实验，您的数据将不会被纳入分析。", icon="")
                except Exception as e:
                    st.error(f"记录退出失败：{e}")
                st.session_state.consent_given = False
                st.session_state.participant_id = ""
                st.session_state.messages = None
                st.session_state.round_count = 0
                st.session_state.show_exit_dialog = False
                st.session_state.experiment_completed = False
                st.rerun()
        with col_no:
            if st.button("取消", key="confirm_exit_no", use_container_width=True):
                st.session_state.show_exit_dialog = False
                st.rerun()
        st.stop()

    if st.session_state.participant_id:
        if st.session_state.messages is None:
            loaded_msgs, loaded_round = load_participant_state(st.session_state.participant_id)
            st.session_state.messages = loaded_msgs
            st.session_state.round_count = loaded_round

        with st.container(key="main_row"):
            col_left, col_right = st.columns([50, 50], gap="large")
            with col_left:
                st.subheader("💬 研究人机交互区")
                st.markdown("**AI 学术助手对话**")
                st.caption(INITIAL_GREETING)
                with st.container():
                    with st.container(height=500, border=False):
                        has_dialogue = False
                        for msg in st.session_state.messages:
                            if msg["role"] == "system":
                                continue
                            if msg["role"] == "assistant" and msg["content"] == INITIAL_GREETING:
                                continue
                            has_dialogue = True
                            with st.chat_message(msg["role"]):
                                st.markdown(msg["content"])
                        if not has_dialogue:
                            st.caption("暂无对话记录，请在下方输入框开始您的第一轮提问～")
                    with st.container():
                        with st.form(key="prompt_form", clear_on_submit=True):
                            with st.container(key="input_wrapper"):
                                user_input = st.text_area(
                                    "在这里输入您的提示词 (Prompt)：",
                                    height=150,
                                    key="prompt_input",
                                    label_visibility="collapsed",
                                    placeholder="请输入您的提示词，可点击右下角 📎 上传 PDF / Word 文档"
                                )
                                uploaded_file = st.file_uploader(
                                    "上传文档",
                                    type=["pdf", "docx"],
                                    key="file_uploader_simple",
                                    label_visibility="collapsed"
                                )
                            if uploaded_file is not None:
                                st.caption(f"📎 已附加文档：{uploaded_file.name}")
                            st.markdown("👇 **请点击以下按钮提交您的提示词（请选择最符合您当前意图的行为）：**")
                            col_b1, col_b2, col_b3, col_b4, col_b5 = st.columns(5)
                            clicked_behavior = None
                            if col_b1.form_submit_button("获取基础信息", use_container_width=True):
                                clicked_behavior = "获取基础信息"
                            elif col_b2.form_submit_button("规范语言/格式", use_container_width=True):
                                clicked_behavior = "规范语言/格式"
                            elif col_b3.form_submit_button("微调研究逻辑", use_container_width=True):
                                clicked_behavior = "微调研究逻辑"
                            elif col_b4.form_submit_button("重构研究方案", use_container_width=True):
                                clicked_behavior = "重构研究方案"
                            elif col_b5.form_submit_button("拓展研究思路", use_container_width=True):
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

            with col_right:
                st.subheader("📝 研究方案填写区")
                existing_plan = load_plan(st.session_state.participant_id)
                st.markdown("**AI协同研究方案撰写**")
                st.caption("任务共分为 6 个递进环节，请根据您与AI的完整对话，将各环节的核心成果填入下方对应模块。您可以在交互过程中随时记录，或最后集中整理。")
                with st.form(key="plan_form"):
                    st.markdown("**子任务1：选题与文献发现**")
                    st.markdown("可围绕后面内容进行填写：1.选题依据（现实痛点与文献空白）；2.核心研究问题；3.拟借鉴的核心理论视角。（建议150字左右）")
                    task1_text = st.text_area("填写区", value=existing_plan["task1_text"] if existing_plan else "", height=160, key="task1_text", label_visibility="collapsed")
                    st.divider()
                    st.markdown("**子任务2：研究规划与设计**")
                    st.markdown("可围绕后面内容进行填写：1.研究类型（量化/实验/质性/混合等）；2.具体的研究实施步骤及研究方法。（建议150字左右）")
                    task2_text = st.text_area("填写区", value=existing_plan["task2_text"] if existing_plan else "", height=160, key="task2_text", label_visibility="collapsed")
                    st.divider()
                    st.markdown("**子任务3：实施与数据采集**")
                    st.markdown("可围绕后面内容进行填写：1.研究对象与选取策略；2.数据收集工具（如问卷维度、访谈提纲、观察指标等）及采集过程。（建议150字左右）")
                    task3_text = st.text_area("填写区", value=existing_plan["task3_text"] if existing_plan else "", height=160, key="task3_text", label_visibility="collapsed")
                    st.divider()
                    st.markdown("**子任务4：数据分析与阐释**")
                    st.markdown("可围绕后面内容进行填写：1.数据分析工具或方法；2.各项数据分析的具体目的（即每一项分析分别用于说明或解决什么问题）。（建议150字左右）")
                    task4_text = st.text_area("填写区", value=existing_plan["task4_text"] if existing_plan else "", height=160, key="task4_text", label_visibility="collapsed")
                    st.divider()
                    st.markdown("**子任务5：论文撰写与润色**")
                    st.markdown("可围绕后面内容进行填写：1.研究的创新点（2-3项）；2.研究存在的不足（2-3项）。（建议300-500字左右）")
                    task5_text = st.text_area("填写区", value=existing_plan["task5_text"] if existing_plan else "", height=300, key="task5_text", label_visibility="collapsed")
                    st.divider()
                    st.markdown("**子任务6：传播、评估与伦理**")
                    st.markdown("可围绕后面内容进行填写：1.成果发表与传播的计划（如学术期刊投稿计划、学术会议汇报、转化为教学实践指南等）；2.研究的伦理考量及其应对措施（如数据隐私、AI使用披露等）。（建议150字左右）")
                    task6_text = st.text_area("填写区", value=existing_plan["task6_text"] if existing_plan else "", height=160, key="task6_text", label_visibility="collapsed")
                    col_submit_btn_left, col_submit_btn_right = st.columns([3, 1])
                    with col_submit_btn_right:
                        submitted = st.form_submit_button("📤 提交方案", use_container_width=True)
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
                            st.session_state.experiment_completed = True
                            st.rerun()
                        else:
                            st.toast("❌ 提交失败，请检查数据库字段。", icon="❌")

        st.divider()
        col_exit1, col_exit_center, col_exit2 = st.columns([4, 1, 4])
        with col_exit_center:
            if st.button("🚪 退出实验", key="exit_button_bottom", use_container_width=True):
                st.session_state.show_exit_dialog = True
                st.rerun()
