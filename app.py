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

# 初始欢迎语（提取为常量，供 get_initial_messages 与页面展示复用，避免重复维护）
INITIAL_GREETING = "您好！我是您的教育研究全栈助理。无论您目前正卡在寻找文献的理论Gap，还是纠结数据分析的逻辑推演，亦或是需要模拟审稿人为您挑刺，我都在这里。请详细告诉我您的要求。"

# ================= 3. 状态持久化函数（修复版：按时间戳重建消息） =================
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
    st.session_state.messages = get_initial_messages()
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
        .top-fixed {
            position: sticky;
            top: 0;
            background-color: white;
            z-index: 100;
            padding: 0.5rem 1rem 0.2rem 1rem;
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

        [data-testid="stHorizontalBlock"] .stColumn:nth-child(5) {
            justify-content: flex-start !important;
            align-items: stretch !important;
            padding-top: 0 !important;
            margin-top: 0 !important;
        }
        [data-testid="stHorizontalBlock"] .stColumn:nth-child(5) .stButton {
            margin-top: 0 !important;
            padding-top: 0 !important;
        }

        .stButton button,
        .stForm button[type="submit"] {
            height: 38px !important;
            min-height: 38px !important;
            max-height: 38px !important;
            width: 100% !important;
            white-space: nowrap !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            line-height: 1.2 !important;
            font-size: 14px !important;
            text-align: center !important;
        }
        .stButton {
            height: 38px !important;
            display: flex !important;
            align-items: center !important;
        }

        [data-testid="stHorizontalBlock"] > div:first-child {
            overflow: visible !important;
            height: auto !important;
        }

        /* 说明：此前这里对“最后一列”（右侧研究方案填写区）单独设置了
           position: sticky + max-height + overflow-y，会导致两列高度增长逻辑不同，
           左右出现明显的错位。现已移除吸顶与高度限制，让两列按正常文档流对齐生长。 */
        [data-testid="stHorizontalBlock"] > div:last-child {
            align-self: flex-start !important;
            background-color: transparent !important;
            padding: 10px !important;
            border-left: 1px solid #ddd;
        }

        [data-testid="stHorizontalBlock"] {
            height: auto !important;
            min-height: 0 !important;
            overflow: visible !important;
            align-items: flex-start !important;
        }

        .role-btn-container {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-top: 0.2rem;
        }
        .role-btn-container .stButton {
            width: auto !important;
        }
        .role-btn-container .stButton button {
            width: 120px !important;
            height: 34px !important;
            min-height: 34px !important;
            max-height: 34px !important;
            font-size: 14px !important;
            padding: 0 12px !important;
        }
        .selected-badge {
            text-align: center;
            color: #4CAF50;
            font-weight: bold;
            font-size: 14px;
            margin-top: 4px;
        }

        /* 知情同意书卡片样式 - 纯HTML方案 */
        .consent-card {
            background: linear-gradient(145deg, #ffffff, #f5f7fa);
            padding: 30px 35px;
            border-radius: 16px;
            border: 1px solid #e0e5ec;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            margin: 10px 0;
            max-width: 800px;
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
        /* 减小分隔线的上下间距 */
        .stDivider hr {
            margin-top: 1px !important;
            margin-bottom: 1px !important;
        }
        /* 减小分隔线的上下间距 */
        hr {
            margin-top: 4px !important;
            margin-bottom: 4px !important;
        }
        
        /* 减小每个子任务外部容器的下边距 */
        [data-testid="stVerticalBlock"] > .stMarkdown {
            margin-bottom: 2px !important;
        }
        
        /* 减小 text_area 容器的下边距 */
        [data-testid="stTextArea"] {
            margin-bottom: 2px !important;
        }
        
        /* 减小子任务标题的边距 */
        .task-odd, .task-even {
            padding: 8px 16px !important;  /* 原来 12px 减小 */
            margin-bottom: 4px !important;
        }
        
        /* 确保子任务内的 text_area 也没有额外边距 */
        .task-odd .stTextArea, .task-even .stTextArea {
            margin-bottom: 0 !important;
        }

        /* ========== 输入框内嵌上传图标 ========== */

        /* 容器设为相对定位，作为图标的定位基准 */
        .st-key-input_wrapper {
            position: relative;
        }

        /* 给文本域右下角预留空间，避免文字被图标遮挡 */
        .st-key-input_wrapper textarea {
            padding-right: 46px !important;
            padding-bottom: 42px !important;
        }

        /* 文件上传组件整体：绝对定位到文本框右下角，尺寸缩小
           bottom 值调大 => 图标位置相应上移 */
        .st-key-input_wrapper [data-testid="stFileUploader"] {
            position: absolute;
            right: 10px;
            bottom: 18px;
            width: 34px;
            height: 34px;
            z-index: 30;
            overflow: hidden;
        }

        /* 隐藏 file_uploader 的 label 文字与帮助小图标 */
        .st-key-input_wrapper [data-testid="stFileUploader"] label,
        .st-key-input_wrapper [data-testid="stFileUploader"] [data-testid="stTooltipIcon"] {
            display: none !important;
        }

        /* 拖拽区域整体缩小、去除边框和内边距 */
        .st-key-input_wrapper [data-testid="stFileUploaderDropzone"] {
            background: transparent !important;
            border: none !important;
            padding: 0 !important;
            margin: 0 !important;
            min-height: 34px !important;
            height: 34px !important;
            width: 34px !important;
        }

        /* 隐藏“Drag and drop file here / Limit 200MB...”提示文字及默认图标 */
        .st-key-input_wrapper [data-testid="stFileUploaderDropzone"] > div:first-child {
            display: none !important;
        }

        /* 把“Browse files”按钮改造成透明底的回形针图标按钮（去除灰色背景与边框） */
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

        /* 隐藏所有输入框（text_area/text_input）右下角的 "Press Ctrl+Enter to submit" 提示 */
        [data-testid="InputInstructions"] {
            visibility: hidden !important;
            color: transparent !important;
            opacity: 0 !important;
        }

        /* ========== 左侧「研究人机交互区」：统一的灰色圆角矩形卡片样式 ==========
           聊天记录框（chat_display_box）与输入区域框（input_display_box）
           共用同一套外观（边框、圆角、底色、内边距），保持视觉一致 */
        .st-key-chat_display_box,
        .st-key-input_display_box {
            border: 1px solid #e2e5ea;
            border-radius: 14px;
            background-color: #fafbfc;
            padding: 16px 18px;
            margin-bottom: 12px;
        }

        /* 聊天记录框：允许滚动，限制最大高度 */
        .st-key-chat_display_box {
            max-height: 560px;
            overflow-y: auto;
        }
        .st-key-chat_display_box::-webkit-scrollbar {
            width: 6px;
        }
        .st-key-chat_display_box::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 5px;
        }
        .st-key-chat_display_box::-webkit-scrollbar-thumb {
            background: #c1c1c1;
            border-radius: 5px;
        }
        .st-key-chat_display_box::-webkit-scrollbar-thumb:hover {
            background: #a8a8a8;
        }
        /* 圆角框内的聊天气泡容器不需要再额外加下边距 */
        .st-key-chat_display_box [data-testid="stChatMessage"] {
            margin-bottom: 6px !important;
        }

        /* 输入区域框：不限制高度，完整显示文本框+图标+按钮 */
        .st-key-input_display_box {
            margin-top: 4px;
            margin-bottom: 0 !important;
        }

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
    # ---------- 研究者模式（居中，密码框缩小，验证在下方） ----------
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
            if st.button("退出研究者模式", use_container_width=True):
                st.session_state.export_authorized = False
                st.query_params.clear()
                st.rerun()

else:
    # ---------- 被试模式 ----------
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
                st.session_state.messages 
