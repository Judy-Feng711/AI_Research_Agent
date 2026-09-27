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
SYSTEM_PROMPT =""" 您是一个名为"ICFER（教育实证研究全周期智能协同框架）"的教育研究设计助理。您的目标是协助教育学领域的研究生完成一项教育研究设计方案，围绕统一主题提供专业、具体的支持。您需要展现出教育研究的专业性、批判性和逻辑性。
核心能力与任务模块：
1. 选题与文献发现：辅助梳理文献脉络，对比不同教育理论（如建构主义与行为主义），精准分析研究空白。
2. 研究规划与设计：从教育心理学、课程论等多重视角构建分析框架，对比个案研究、行动研究等方法的适用性。
3. 实施与数据采集：协助开发访谈提纲等收集工具，指出并规避表述偏差及伦理风险。
4. 数据分析与阐释：提供Python/R等统计脚本编写指引，深度解读统计结果与理论模型的深层逻辑，接受用户的逻辑纠错。
5. 论文撰写与润色：辅助梳理写作思路，检查专业术语一致性，提出修改建议。
6. 传播、评估与伦理：辅助提炼实践建议，提示伦理考量与传播路径。
互动规则：
- 直接回应用户的请求，提供所需信息或建议。
- 不要主动改变话题，不要反复追问。"""

INITIAL_GREETING = '您好！我是您的教育研究全栈助理 ICFER。接下来，我们将围绕 "人工智能时代的教师教育与教师专业发展研究" 这一主题，共同完成一份实证研究设计方案。您可以在下方输入框写下您的提示词，然后点击最符合您意图的按钮提交。'

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
    if st.session_state.get("experiment_start_time"):
        data["experiment_start_time"] = st.session_state.experiment_start_time
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

def load_experiment_start_time(pid):
    try:
        resp = supabase.table("participant_state").select("experiment_start_time").eq("participant_id", pid).execute()
        if resp.data and resp.data[0].get("experiment_start_time"):
            return resp.data[0]["experiment_start_time"]
    except Exception:
        pass
    return None

def save_experiment_start_time(pid, start_time_iso):
    try:
        supabase.table("participant_state").upsert(
            {"participant_id": pid, "experiment_start_time": start_time_iso},
            on_conflict="participant_id"
        ).execute()
        return True
    except Exception as e:
        st.error(f"开始时间保存失败：{e}")
        return False

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
if "experiment_start_time" not in st.session_state:
    st.session_state.experiment_start_time = None
if "time_reminder_shown" not in st.session_state:
    st.session_state.time_reminder_shown = False
if "time_reminder_dismissed" not in st.session_state:
    st.session_state.time_reminder_dismissed = False

query_params = st.query_params
if "mode" in query_params and query_params["mode"] == "admin":
    st.session_state.user_role = "研究者"
else:
    if st.session_state.user_role is None:
        st.session_state.user_role = "被试"

st.markdown(
    """
    <style>
        /* ===== 1. 压缩浏览器上下留白 ===== */
        [data-testid="stHeader"] {
            height: 0 !important;
            min-height: 0 !important;
        }
        .block-container, [data-testid="stMainBlockContainer"] {
            padding-top: 0.4rem !important;
            padding-bottom: 0.3rem !important;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
        }

        .top-fixed {
            position: sticky;
            top: 0;
            background-color: white;
            z-index: 100;
            padding: 0.05rem 1rem 0.05rem 0.5rem;
            border-bottom: none !important;
            box-shadow: none !important;
        }
        .top-fixed h1 {
            margin-top: 0 !important;
            margin-bottom: 0 !important;
            line-height: 1.15 !important;
        }
        .top-fixed p {
            margin-top: 2px !important;
            margin-bottom: 2px !important;
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

        /* ===== 2. 左右大块：边框加深 + 强制等高，底边到灰线距离一致 ===== */
        .st-key-main_row {
            padding-bottom: 0 !important;
            margin-bottom: 0 !important;
        }
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3) {
            align-items: stretch !important;
            height: auto !important;
            overflow: visible !important;
        }
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn {
            height: calc(100vh - 155px) !important;
            max-height: calc(100vh - 155px) !important;
            min-height: calc(100vh - 155px) !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            padding: 10px 14px 6px 14px !important;
            border: 1px solid #64748b !important;
            border-radius: 12px !important;
            box-sizing: border-box !important;
            margin-bottom: 0 !important;
            align-self: stretch !important;
        }
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn:first-child {
            background-color: #f8fbff !important;
            box-shadow: 0 2px 10px rgba(21, 101, 192, 0.07) !important;
        }
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn:last-child {
            background-color: #f9fdf9 !important;
            box-shadow: 0 2px 10px rgba(46, 125, 50, 0.07) !important;
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
            min-height: 0 !important;
            height: auto !important;
            overflow: visible !important;
            padding: 0 1px !important;
            background: transparent !important;
            border: none !important;
            border-radius: 0 !important;
            box-shadow: none !important;
            align-self: auto !important;
        }

        /* ===== 左列内部flex：输入表单贴底，消除表单下方留白 ===== */
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn:first-child > div[data-testid="stVerticalBlock"] {
            height: 100% !important;
            display: flex !important;
            flex-direction: column !important;
            flex: 1 !important;
        }
        .st-key-left_chat_wrap {
            display: flex !important;
            flex-direction: column !important;
            flex: 1 !important;
            min-height: 0 !important;
        }
        .st-key-left_form_wrap {
            margin-top: auto !important;
            padding-bottom: 0 !important;
            margin-bottom: 0 !important;
        }
        .st-key-main_row .stForm {
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
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

        /* 左侧五个行为按钮统一字号 */
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn:first-child .stForm button[type="submit"],
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn:first-child .stForm button[type="submit"] p,
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn:first-child .stForm button[type="submit"] span,
        .st-key-main_row
        [data-testid="stHorizontalBlock"]:has(> div.stColumn:first-child h3):has(> div.stColumn:last-child h3)
        > div.stColumn:first-child .stForm button[type="submit"] div {
            font-size: 14px !important;
            font-weight: 500 !important;
            white-space: nowrap !important;
            word-break: keep-all !important;
        }

        /* ===== 3. 右下三按钮依次加深 ===== */
        .st-key-btn_exit_bottom button {
            background: #f1f3f5 !important;
            color: #495057 !important;
            border: 1px solid #adb5bd !important;
            font-weight: 500 !important;
        }
        .st-key-btn_exit_bottom button:hover {
            background: #e9ecef !important;
            border-color: #868e96 !important;
        }
        .st-key-btn_temp_save button {
            background: #e7f1ff !important;
            color: #1565c0 !important;
            border: 1px solid #74a9e6 !important;
            font-weight: 600 !important;
        }
        .st-key-btn_temp_save button:hover {
            background: #d0e4ff !important;
        }
        .st-key-btn_submit_final button {
            background: #2e7d32 !important;
            color: #ffffff !important;
            border: 1px solid #2e7d32 !important;
            font-weight: 700 !important;
        }
        .st-key-btn_submit_final button:hover {
            background: #1b5e20 !important;
            border-color: #1b5e20 !important;
        }
        .st-key-btn_exit_bottom button p, .st-key-btn_exit_bottom button span,
        .st-key-btn_temp_save button p, .st-key-btn_temp_save button span,
        .st-key-btn_submit_final button p, .st-key-btn_submit_final button span {
            font-size: 14px !important;
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
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p {
            font-size: 16px !important;
            line-height: 1.6 !important;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h1 {
            font-size: 20px !important;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h2 {
            font-size: 18px !important;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] h3 {
            font-size: 16px !important;
        }

        .time-reminder-banner {
            background-color: #fff4e5;
            border: 2px solid #ff9800;
            border-radius: 12px;
            padding: 10px 24px;
            margin: 4px auto 8px auto;
            max-width: 1100px;
            text-align: center;
            box-shadow: 0 4px 12px rgba(255, 152, 0, 0.15);
        }
        .time-reminder-banner .banner-text {
            font-size: 18px;
            font-weight: 600;
            color: #b45309;
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
        <p style="font-size: 
