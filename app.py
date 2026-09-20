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
SYSTEM_PROMPT = """您是一个名为"全栈式教育研究学术助理"的高级AI。您的目标是深度辅助教育学领域的研究生完成真实、复杂的学术研究任务，而非简单地给出敷衍的现成答案。您需要展现出教育研究的专业性、批判性和逻辑性。
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
INITIAL_GREETING = "您好！我是您的教育研究全栈助理。无论您目前正卡在寻找文献的理论Gap，还是纠结数据分析的逻辑推演，亦或是需要模拟审稿人为您挑刺，我都在这里。请详细告诉我您的要求。"

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

# ================= 新增：知情同意保存函数 =================
def save_consent_record(pid):
    """
    将知情同意记录写入 consent_records 表
    """
    if not pid or pid.strip() == "":
        return False
    try:
        data = {
            "participant_id": pid.strip(),
            "consent_timestamp": datetime.datetime.now().isoformat(),
            "consent_version": "v1.0_ICFER_2026"
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
        /* 移除页面默认的padding和margin */
        .main > div {
            padding-top: 0rem !important;
            padding-bottom: 0rem !important;
            max-width: 100% !important;
        }

        /* 顶部固定栏 */
        .top-fixed {
            position: sticky;
            top: 0;
            background-color: white;
            z-index: 100;
            padding: 0.5rem 1rem !important;
            border-bottom: 1px solid #e2e5ea !important;
            margin-bottom: 0 !important;
        }

        /* 主布局容器 */
        .main-container {
            display: flex;
            flex-direction: column;
            height: calc(100vh - 60px) !important;
            margin-top: 0 !important;
        }

        /* 两栏布局 */
        .two-column-layout {
            display: flex;
            flex: 1;
            gap: 1rem;
            padding: 0.5rem 1rem !important;
            height: calc(100vh - 120px) !important;
        }

        /* 左右两栏 */
        .left-column, .right-column {
            flex: 1;
            display: flex;
            flex-direction: column;
            height: 100%;
            overflow: hidden;
        }

        /* 聊天区域容器 */
        .chat-container {
            display: flex;
            flex-direction: column;
            height: 100%;
            border: 1px solid #e2e5ea;
            border-radius: 12px;
            background-color: #fafbfc;
            padding: 12px;
        }

        /* 聊天消息区域 */
        .messages-container {
            flex-grow: 1;
            overflow-y: auto;
            padding-right: 4px;
            margin-bottom: 10px;
        }

        /* 输入区域 */
        .input-container {
            background-color: white;
            padding-top: 8px;
            border-top: 1px solid #e2e5ea;
        }

        /* 消息样式 */
        [data-testid="stChatMessage"] {
            margin-bottom: 8px !important;
        }

        /* 按钮样式 */
        .stButton button {
            height: 36px !important;
            min-height: 36px !important;
            font-size: 14px !important;
        }

        /* 方案填写区域 */
        .plan-container {
            height: 100%;
            border: 1px solid #e2e5ea;
            border-radius: 12px;
            background-color: #fafbfc;
            padding: 12px;
            overflow-y: auto;
        }

        /* 文本区域样式 */
        [data-testid="stTextArea"] {
            margin-bottom: 8px !important;
        }

        /* 分隔线样式 */
        .stDivider {
            margin: 6px 0 !important;
        }

        /* 退出按钮区域 */
        .exit-button-container {
            padding: 0.5rem 1rem !important;
            text-align: center;
            margin-top: 0 !important;
            margin-bottom: 0 !important;
        }

        /* 知情同意书样式 */
        .consent-card {
            background: linear-gradient(145deg, #ffffff, #f5f7fa);
            padding: 20px 25px !important;
            border-radius: 12px;
            border: 1px solid #e0e5ec;
            box-shadow: 0 2px 8px rgba(0,0,0,0.03);
            margin: 10px auto !important;
            max-width: 800px;
            text-align: left;
        }

        /* 滚动条样式 */
        ::-webkit-scrollbar {
            width: 6px;
        }
        ::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 3px;
        }
        ::-webkit-scrollbar-thumb {
            background: #888;
            border-radius: 3px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #555;
        }

        /* 标题样式 */
        .stHeadingContainer h1 {
            font-size: 28px !important;
            margin-bottom: 2px !important;
        }
        .stHeadingContainer p {
            font-size: 16px !important;
            margin-top: 2px !important;
        }

        /* 子任务标题样式 */
        .stMarkdown h3 {
            font-size: 18px !important;
            margin-bottom: 6px !important;
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
    </style>
    """,
    unsafe_allow_html=True
)

# ================= 7. 固定顶部栏（标题） =================
st.markdown('<div class="top-fixed">', unsafe_allow_html=True)
st.markdown(
    """
    <div style="text-align: center;">
        <h1 style="font-size: 28px; margin-bottom: 0;">🎓 教育实证研究全周期智能协同框架</h1>
        <p style="font-size: 16px; color: #555; margin-top: 2px;">Intelligent Collaborative Framework for Empirical Research in Education (ICFER)</p>
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
            <div style="text-align: center; padding: 20px 20px 10px 20px;">
                <h2 style="color: #4CAF50;">✅ 方案已提交成功！实验已完成！</h2>
                <p style="font-size: 16px;">感谢您参与本次研究！您的数据已成功保存。</p>
                <p style="font-size: 14px; color: #666;">您现在可以关闭此页面，或点击下方按钮返回首页。</p>
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
            <div style="text-align: center; padding: 30px 20px 20px 20px;">
                <h2 style="color: #1a3a5a; margin-bottom: 10px;">👤 欢迎参与研究</h2>
                <p style="font-size: 16px; color: #555; margin-bottom: 20px;">
                    请输入研究者分配给您的编号以开始实验。<br>
                    输入编号后，您将阅读并签署知情同意书。
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )
        col_space1, col_id, col_space2 = st.columns([1, 2, 1])
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
            "<p style='text-align: center; font-size: 14px; color: #555;'>"
            f"当前参与者编号：<strong>{st.session_state.participant_id}</strong>"
            "</p>",
            unsafe_allow_html=True
        )

        st.markdown(
            """
            <div class="consent-card">
                <h2>📋 知情同意书</h2>
                <p style="text-align:center; color:#888; font-size:12px; margin-top:-8px;">版本号：v1.0_ICFER_2026　|　生效日期：2026-09-20</p>
                <p><strong>研究主题：人工智能辅助教育研究的特征与机制研究</strong></p>
                <p>尊敬的参与者，您好！我们是陕西师范大学教育学部的科研团队，诚挚地邀请您参与我们的研究项目。在您点击"同意"按钮之前，请务必仔细阅读以下内容。</p>

                <p><strong>一、研究目的</strong></p>
                <p>本研究旨在探索教育研究者如何与生成式人工智能（AI）协同工作，分析您与AI共同完成研究设计任务的过程。</p>

                <p><strong>二、参与过程</strong></p>
                <p>您将与我们的智能研究助理ICFER进行约100分钟的对话，围绕"人工智能时代的教师教育与教师专业发展研究"主题完成研究设计方案。</p>

                <p><strong>三、数据处理</strong></p>
                <p>所有数据将匿名化处理，仅用于学术分析，并在研究完成后3年内销毁。</p>

                <p><strong>四、风险与收益</strong></p>
                <p>本研究无身体风险，可能的心理不适可随时退出。您将获得AI协同完成的研究方案初稿。</p>

                <p><strong>五、自愿参与</strong></p>
                <p>您可随时退出实验，退出后数据将不被纳入分析。</p>

                <p><strong>六、联系方式</strong></p>
                <p>研究负责人：周榕 副教授（rzhou@snnu.edu.cn，13309296061）</p>

                <div class="footer-note">点击下方"同意"即表示您已阅读并理解上述内容，自愿参与本研究。</div>
            </div>
            """,
            unsafe_allow_html=True
        )

        col_center_btn = st.columns([3, 1, 3])[1]
        with col_center_btn:
            if st.button("✅ 我同意并参与实验", use_container_width=True):
                st.session_state.consent_given = True
                save_consent_record(st.session_state.participant_id)  # 保存同意记录
                st.rerun()
        st.stop()

    # 【4】退出确认对话框
    if st.session_state.show_exit_dialog:
        st.warning("您确定要退出实验吗？退出后，您本次实验的所有数据将不会被纳入最终数据分析。")
        col_confirm1, col_confirm2 = st.columns(2)
        with col_confirm1:
            if st.button("确认退出", key="confirm_exit_yes"):
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
                    st.toast("✅ 已记录退出实验，您的数据将不会被纳入分析。", icon="✅")
                except Exception as e:
                    st.error(f"记录退出失败：{e}")
                st.session_state.consent_given = False
                st.session_state.participant_id = ""
                st.session_state.messages = None
                st.session_state.round_count = 0
                st.session_state.show_exit_dialog = False
                st.session_state.experiment_completed = False
                st.rerun()
        with col_confirm2:
            if st.button("取消", key="confirm_exit_no"):
                st.session_state.show_exit_dialog = False
                st.rerun()
        st.stop()

    # 【5】主实验界面
    if st.session_state.participant_id:
        if st.session_state.messages is None:
            loaded_msgs, loaded_round = load_participant_state(st.session_state.participant_id)
            st.session_state.messages = loaded_msgs
            st.session_state.round_count = loaded_round

        # 主容器
        st.markdown('<div class="main-container">', unsafe_allow_html=True)

        # 两栏布局
        st.markdown('<div class="two-column-layout">', unsafe_allow_html=True)

        # 左栏 - 聊天区域
        with st.container():
            st.markdown('<div class="left-column">', unsafe_allow_html=True)

            with st.container():
                st.subheader("💬 研究人机交互区")
                st.caption(INITIAL_GREETING)

                with st.container():
                    st.markdown('<div class="chat-container">', unsafe_allow_html=True)

                    # 聊天消息区域
                    with st.container():
                        st.markdown('<div class="messages-container">', unsafe_allow_html=True)
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
                        st.markdown('</div>', unsafe_allow_html=True)

                    # 输入区域
                    with st.container():
                        st.markdown('<div class="input-container">', unsafe_allow_html=True)
                        with st.form(key="prompt_form", clear_on_submit=True):
                            with st.container(key="input_wrapper"):
                                user_input = st.text_area(
                                    "在这里输入您的提示词 (Prompt)：",
                                    height=120,
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

                            st.markdown("👇 **请点击以下按钮提交您的提示词：**")
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
                        st.markdown('</div>', unsafe_allow_html=True)
                    st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # 右栏 - 方案填写区域
        with st.container():
            st.markdown('<div class="right-column">', unsafe_allow_html=True)

            with st.container():
                st.subheader("📝 研究方案填写区")
                st.caption("请根据与AI的对话，填写以下6个环节的核心成果")

                with st.container():
                    st.markdown('<div class="plan-container">', unsafe_allow_html=True)
                    existing_plan = load_plan(st.session_state.participant_id)
                    with st.form(key="plan_form"):
                        st.markdown("**子任务1：选题与文献发现**")
                        task1_text = st.text_area(
                            "1.选题依据；2.核心研究问题；3.理论视角。（建议150字）",
                            value=existing_plan["task1_text"] if existing_plan else "",
                            height=120,
                            key="task1_text"
                        )
                        st.divider()

                        st.markdown("**子任务2：研究规划与设计**")
                        task2_text = st.text_area(
                            "1.研究类型；2.实施步骤与方法。（建议150字）",
                            value=existing_plan["task2_text"] if existing_plan else "",
                            height=120,
                            key="task2_text"
                        )
                        st.divider()

                        st.markdown("**子任务3：实施与数据采集**")
                        task3_text = st.text_area(
                            "1.研究对象与选取策略；2.数据收集工具。（建议150字）",
                            value=existing_plan["task3_text"] if existing_plan else "",
                            height=120,
                            key="task3_text"
                        )
                        st.divider()

                        st.markdown("**子任务4：数据分析与阐释**")
                        task4_text = st.text_area(
                            "1.分析工具或方法；2.分析目的。（建议150字）",
                            value=existing_plan["task4_text"] if existing_plan else "",
                            height=120,
                            key="task4_text"
                        )
                        st.divider()

                        st.markdown("**子任务5：论文撰写与润色**")
                        task5_text = st.text_area(
                            "1.研究创新点；2.研究不足。（建议300-500字）",
                            value=existing_plan["task5_text"] if existing_plan else "",
                            height=180,
                            key="task5_text"
                        )
                        st.divider()

                        st.markdown("**子任务6：传播、评估与伦理**")
                        task6_text = st.text_area(
                            "1.成果发表计划；2.伦理考量。（建议150字）",
                            value=existing_plan["task6_text"] if existing_plan else "",
                            height=120,
                            key="task6_text"
                        )

                        col_submit_btn_left, col_submit_btn_right = st.columns([3, 1])
                        with col_submit_btn_right:
                            submitted = st.form_submit_button("📤 提交方案", use_container_width=True)
                        if submitted:
                            if not all([task1_text.strip(), task2_text.strip(), task3_text.strip(),
                                        task4_text.strip(), task5_text.strip(), task6_text.strip()]):
                                st.warning("建议填写所有子任务以完善方案。")
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
                    st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # 关闭两栏布局
        st.markdown('</div>', unsafe_allow_html=True)

        # 退出按钮
        st.markdown('<div class="exit-button-container">', unsafe_allow_html=True)
        col_exit1, col_exit_center, col_exit2 = st.columns([4, 1, 4])
        with col_exit_center:
            if st.button("🚪 退出实验", key="exit_button_bottom", use_container_width=True):
                st.session_state.show_exit_dialog = True
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # 关闭主容器
        st.markdown('</div>', unsafe_allow_html=True)
