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
        {"role": "assistant", "content": "您好！我是您的教育研究全栈助理。无论您目前正卡在寻找文献的理论Gap，还是纠结数据分析的逻辑推演，亦或是需要模拟审稿人为您挑刺，我都在这里。请详细告诉我您的要求。"}
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
st.set_page_config(page_title="EduResearch Copilot", page_icon="🎓", layout="wide")

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

# ================= 角色判断（使用 URL 参数控制） =================
query_params = st.query_params
if "mode" in query_params and query_params["mode"] == "admin":
    st.session_state.user_role = "研究者"
else:
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
            gap: 0 !important;
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

        .exit-button-container {
            display: flex !important;
            justify-content: flex-end !important;
            align-items: center !important;
            height: 100%;
        }
        .exit-button-container .stButton button {
            width: auto !important;
            padding-left: 12px !important;
            padding-right: 12px !important;
            min-width: unset !important;
        }

        [data-testid="stHorizontalBlock"] > div:first-child {
            overflow: visible !important;
            height: auto !important;
        }
        [data-testid="stHorizontalBlock"] > div:last-child {
            position: sticky !important;
            top: 110px !important;
            align-self: flex-start !important;
            height: auto !important;
            max-height: calc(100vh - 110px) !important;
            overflow-y: auto !important;
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

        /* 子任务背景色块 */
        .task-odd {
            background-color: #f0f7ff;
            padding: 12px 16px;
            border-radius: 10px;
            margin-bottom: 12px;
            border-left: 4px solid #90b9f0;
        }
        .task-even {
            background-color: #fff5f7;
            padding: 12px 16px;
            border-radius: 10px;
            margin-bottom: 12px;
            border-left: 4px solid #f0a0b0;
        }
        .task-odd .stTextArea, .task-even .stTextArea {
            background-color: transparent !important;
        }
        .task-odd label, .task-even label {
            font-weight: 500;
        }
    </style>
    """,
    unsafe_allow_html=True
)

# ================= 7. 固定顶部栏（标题） =================
st.markdown('<div class="top-fixed">', unsafe_allow_html=True)
st.markdown(
    "<h1 style='text-align: center;'>🎓 EduResearch Copilot (教育研究全栈助理)</h1>",
    unsafe_allow_html=True
)
st.markdown('</div>', unsafe_allow_html=True)

# ================= 8. 根据角色显示内容 =================
if st.session_state.user_role == "研究者":
    # ---------- 研究者模式（仅数据导出） ----------
    st.subheader("📊 研究者数据导出")
    st.markdown("请输入研究者密码以查看并下载数据。")
    if "export_authorized" not in st.session_state:
        st.session_state.export_authorized = False
    if not st.session_state.export_authorized:
        export_pass = st.text_input("请输入研究者密码", type="password", key="export_pass")
        if st.button("验证", key="verify_export"):
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
        if st.button("退出研究者模式"):
            st.session_state.export_authorized = False
            st.query_params.clear()
            st.rerun()

else:
    # ---------- 被试模式 ----------
    # 如果实验已完成，显示感谢页面
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
                st.session_state.messages = get_initial_messages()
                st.session_state.round_count = 0
                st.session_state.show_exit_dialog = False
                st.session_state.experiment_completed = False
                st.rerun()
        st.stop()

    # 显示欢迎语（仅当未同意时）
    if not st.session_state.consent_given:
        st.markdown(
            "<p style='text-align: center; font-size: 18px;'>"
            "您好！我是您的教育研究全栈助理。无论您目前正卡在寻找文献的理论Gap，"
            "还是纠结数据分析的逻辑推演，亦或是需要模拟审稿人为您挑刺，我都在这里。"
            "</p>",
            unsafe_allow_html=True
        )

        # 知情同意书 - 纯HTML，无Markdown混合
        st.markdown(
            """
            <div class="consent-card">
                <h2>📋 知情同意书</h2>
                <p>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;尊敬的参与者，您好！在点击“同意”之前，请您仔细阅读以下内容：</p>
                <p><strong>研究介绍</strong><br>
                &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;请围绕“人工智能时代的教师教育与教师专业发展研究”这一核心议题，结合您自身的学科专长，与 EduResearch Copilot  (教育研究全栈助理)进行约100分钟的深度对话，构思并完成一份实证研究设计方案。</p>
                <p><strong></strong><br</p>
                <p><strong>数据采集</strong></p>
                <ul>
                    <li>您与AI的完整对话日志将被系统自动记录；</li>
                    <li>您在各阶段填写的研究要点将共同构成您的设计方案。</li>
                </ul>
                <p><strong></strong><br</p>
                <p><strong>隐私保护</strong></p>
                <ul>
                    <li>无明显风险，但请确保您在安静环境中进行，分析阶段将进一步去标识化；</li>
                    <li>数据仅用于学术研究，不用于训练 AI，不提供给第三方，并将在采集完成之日起 3 年内销毁。</li>
                </ul>
                <p><strong></strong><br</p>
                <p><strong>自愿与退出</strong></p>
                <p>
                    &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;实验全程秉持自愿原则。如果您在过程中感到任何不适或希望终止，可随时点击界面右上角的“退出实验”按钮，退出后将立即停止记录，已产生的日志不再纳入后续数据分析。
                </p>
                <p><strong></strong><br</p>
                <p><strong>风险与收益</strong></p>
                <p>
                   &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;本实验无生理或心理风险。您将获得一次 AI 深度辅助研究体验，及一份量身定制的设计方案初稿。
                </p>
                <p><strong></strong><br</p>
                <p><strong>联系方式</strong></p>
                <p>
                   &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;如有疑问，请联系研究者：<strong>944577606@qq.com</strong>
                </p>
                <p><strong></strong><br</p>
                <div class="footer-note">点击下方“同意”即表示您已阅读并理解上述内容，自愿参与本研究。</div>
            </div>
            """,
            unsafe_allow_html=True
        )

        col_center_btn = st.columns([3, 1, 3])[1]
        with col_center_btn:
            if st.button("✅ 我同意并参与实验", use_container_width=True):
                st.session_state.consent_given = True
                st.rerun()
        st.stop()

    # 已同意，显示主界面
    # 处理退出确认对话框
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
                st.session_state.messages = get_initial_messages()
                st.session_state.round_count = 0
                st.session_state.show_exit_dialog = False
                st.session_state.experiment_completed = False
                st.rerun()
        with col_confirm2:
            if st.button("取消", key="confirm_exit_no"):
                st.session_state.show_exit_dialog = False
                st.rerun()
        st.stop()

    # 正常显示被试内容
    if not st.session_state.participant_id:
        col_space1, col_id, col_space2 = st.columns([1, 2, 1])
        with col_id:
            st.markdown(
                "<p style='text-align: center; font-size: 18px; font-weight: bold;'>👤 请输入您的编号</p>",
                unsafe_allow_html=True
            )
            pid_input = st.text_input(
                "输入编号后按回车确认",
                value="",
                key="pid_input_top",
                label_visibility="collapsed",
                placeholder="请输入编号，例如 P001"
            )
            if pid_input and pid_input.strip():
                st.session_state.participant_id = pid_input.strip()
                st.session_state.messages = None
                st.rerun()
    else:
        col_id, col_exit = st.columns([2, 1])
        with col_id:
            st.markdown(f"**当前被试：{st.session_state.participant_id}**")
        with col_exit:
            st.markdown('<div class="exit-button-container">', unsafe_allow_html=True)
            if st.button("🚪 退出实验", key="exit_button", use_container_width=False):
                st.session_state.show_exit_dialog = True
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    if st.session_state.participant_id:
        if st.session_state.messages is None or not st.session_state.messages:
            loaded_msgs, loaded_round = load_participant_state(st.session_state.participant_id)
            st.session_state.messages = loaded_msgs
            st.session_state.round_count = loaded_round

        col_left, col_right = st.columns([55, 45], gap="large")
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

        with col_right:
            st.subheader("📝 研究方案填写")
            existing_plan = load_plan(st.session_state.participant_id)
            st.markdown("**AI协同研究方案生成记录表**")
            st.caption("请根据您与AI的完整对话，将各环节的核心成果填入下方对应模块。每个模块均有最低字数要求（达标后方可提交）。您可以在交互过程中随时记录，或最后集中整理。")
            with st.form(key="plan_form"):
                # 子任务1（奇数）
                st.markdown('<div class="task-odd">', unsafe_allow_html=True)
                st.markdown("**子任务1：选题与文献发现**")
                task1_text = st.text_area(
                    "请写清您的核心研究问题、选题依据及所依据的理论视角。（限150字）",
                    value=existing_plan["task1_text"] if existing_plan else "",
                    height=140,
                    max_chars=150,
                    key="task1_text"
                )
                st.markdown('</div>', unsafe_allow_html=True)
                st.divider()

                # 子任务2（偶数）
                st.markdown('<div class="task-even">', unsafe_allow_html=True)
                st.markdown("**子任务2：研究规划与设计**")
                task2_text = st.text_area(
                    "请说明您的研究方法（量化/质性/混合）、研究框架或技术路线。（限150字）",
                    value=existing_plan["task2_text"] if existing_plan else "",
                    height=140,
                    max_chars=150,
                    key="task2_text"
                )
                st.markdown('</div>', unsafe_allow_html=True)
                st.divider()

                # 子任务3（奇数）
                st.markdown('<div class="task-odd">', unsafe_allow_html=True)
                st.markdown("**子任务3：实施与数据采集**")
                task3_text = st.text_area(
                    "请描述您的数据采集方案（如问卷维度、访谈提纲框架、样本选择等）。（限150字）",
                    value=existing_plan["task3_text"] if existing_plan else "",
                    height=140,
                    max_chars=150,
                    key="task3_text"
                )
                st.markdown('</div>', unsafe_allow_html=True)
                st.divider()

                # 子任务4（偶数）
                st.markdown('<div class="task-even">', unsafe_allow_html=True)
                st.markdown("**子任务4：数据分析与阐释**")
                task4_text = st.text_area(
                    "请写明您计划使用的数据分析方法（如SPSS、MPLUS、ENA等）及分析思路。（限150字）",
                    value=existing_plan["task4_text"] if existing_plan else "",
                    height=140,
                    max_chars=150,
                    key="task4_text"
                )
                st.markdown('</div>', unsafe_allow_html=True)
                st.divider()

                # 子任务5（奇数）
                st.markdown('<div class="task-odd">', unsafe_allow_html=True)
                st.markdown("**子任务5：论文撰写与润色**")
                task5_text = st.text_area(
                    "请粘贴您借助AI撰写或润色后的论文片段（如引言或方法部分）。（限300-500字）",
                    value=existing_plan["task5_text"] if existing_plan else "",
                    height=300,
                    max_chars=500,
                    key="task5_text"
                )
                st.markdown('</div>', unsafe_allow_html=True)
                st.divider()

                # 子任务6（偶数）
                st.markdown('<div class="task-even">', unsafe_allow_html=True)
                st.markdown("**子任务6：传播、评估与伦理**")
                task6_text = st.text_area(
                    "请列出本研究涉及的伦理考量及计划中的成果传播渠道。（限150字）",
                    value=existing_plan["task6_text"] if existing_plan else "",
                    height=140,
                    max_chars=150,
                    key="task6_text"
                )
                st.markdown('</div>', unsafe_allow_html=True)

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
                        st.session_state.experiment_completed = True
                        st.rerun()
                    else:
                        st.toast("❌ 提交失败，请检查数据库字段。", icon="❌")
