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

# ================= 3. 状态持久化函数 =================
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

# ================= 4. 页面初始化 =================
st.set_page_config(page_title="EduResearch Copilot", page_icon="🎓", layout="centered")

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

# ================= 5. 侧边栏 =================
with st.sidebar:
    st.markdown("### 👤 被试身份")
    
    if st.session_state.participant_id and not st.session_state.state_loaded:
        loaded_msgs, loaded_round = load_participant_state(st.session_state.participant_id)
        if loaded_msgs is not None:
            if loaded_msgs and loaded_msgs[0].get("role") == "system":
                st.session_state.messages = loaded_msgs
            else:
                st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}] + loaded_msgs
            st.session_state.round_count = loaded_round
            st.session_state.state_loaded = True
            st.success(f"✅ 已恢复历史进度（第 {st.session_state.round_count} 轮）")
        else:
            st.session_state.messages = get_initial_messages()
            st.session_state.round_count = 0
            st.session_state.state_loaded = True
            save_participant_state(st.session_state.participant_id, st.session_state.messages, st.session_state.round_count)
            st.info("🆕 新被试，已初始化状态")
    
    pid_input = st.text_input(
        "请输入您的被试编号（如 P001）：",
        value=st.session_state.participant_id if st.session_state.participant_id else "",
        key="pid_input"
    )
    
    if pid_input and pid_input.strip() != st.session_state.participant_id:
        new_pid = pid_input.strip()
        st.session_state.participant_id = new_pid
        st.session_state.state_loaded = False
        st.rerun()
    
    if st.session_state.participant_id:
        st.success(f"当前被试：{st.session_state.participant_id}")

    st.divider()

    st.markdown("### 📊 对话进度")
    st.metric(label="已完成的对话轮数", value=st.session_state.round_count)
    if st.session_state.round_count >= 10:
        st.success("✅ 已达成建议轮数（10轮），如仍有新问题可继续深入。")
    elif st.session_state.round_count >= 8:
        st.info("💡 已接近建议轮数（8-12轮），可以继续深入或总结。")
    else:
        st.caption("建议完成 8-12 轮对话")

    st.divider()

    st.markdown("### 🔐 研究者数据导出")
    password = st.text_input("请输入数据导出密码", type="password")
    RESEARCHER_PASSWORD = st.secrets.get("RESEARCHER_PASSWORD", "MyPassword123")

    if password:
        if password == RESEARCHER_PASSWORD:
            st.success("密码正确，可以下载数据")
            try:
                response = supabase.table("research_logs").select("*").execute()
                if response.data:
                    df = pd.DataFrame(response.data)
                    csv_data = df.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                        label="📥 下载全部交互数据",
                        data=csv_data.encode('utf-8-sig'),
                        file_name="research_logs.csv",
                        mime="text/csv"
                    )
                else:
                    st.info("暂无数据，请等待被试完成交互。")
            except Exception as e:
                st.error(f"读取数据失败：{e}")
        else:
            st.error("密码错误，无权限下载")
    else:
        st.info("请输入密码以导出数据")

# ================= 6. 主页面 =================
st.title("🎓 EduResearch Copilot (教育研究全栈助理)")
st.markdown("欢迎！请输入您的科研提示词，并**选择最符合您当前行为意图的按钮**提交。")

if st.session_state.participant_id:
    st.caption(f"👤 当前被试：{st.session_state.participant_id}")

for msg in st.session_state.messages:
    if msg["role"] != "system":
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# ================= 7. 核心交互模块 =================
if not st.session_state.participant_id:
    st.warning("⚠️ 请先在左侧边栏输入您的被试编号！")
else:
    with st.form(key="prompt_form", clear_on_submit=True):
        # ---- 输入框与附件按钮并排（优化布局） ----
        col_input, col_upload = st.columns([6, 1])  # 6:1 比例
        
        with col_input:
            user_input = st.text_area(
                "在这里输入您的提示词 (Prompt)：",
                height=100,
                key="prompt_input",
                label_visibility="collapsed"  # 隐藏标签，节省空间
            )
        
        with col_upload:
            # 使用空元素把上传器推到底部（与输入框底部对齐）
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)  # 占位高度
            uploaded_file = st.file_uploader(
                label="📎",  # 只显示图标，更简洁
                type=["pdf", "docx"],
                label_visibility="visible",  # 必须可见，help 才会显示
                help="快速模式下，仅识别图片与文件中的文字最多50个，每个100 MB",
                key="file_uploader_in_form"
            )
            if uploaded_file is not None:
                st.caption(uploaded_file.name[:10] + "..." if len(uploaded_file.name) > 10 else uploaded_file.name)

        st.markdown("👇 **请点击以下按钮提交您的提示词（请选择最符合您当前意图的行为）：**")
        col1, col2, col3, col4, col5 = st.columns(5)
        clicked_behavior = None
        if col1.form_submit_button("获取基础信息"):
            clicked_behavior = "获取基础信息"
        elif col2.form_submit_button("规范语言/格式"):
            clicked_behavior = "规范语言/格式"
        elif col3.form_submit_button("微调研究逻辑"):
            clicked_behavior = "微调研究逻辑"
        elif col4.form_submit_button("重构研究方案"):
            clicked_behavior = "重构研究方案"
        elif col5.form_submit_button("拓展研究思路"):
            clicked_behavior = "拓展研究思路"

        if clicked_behavior:
            if not user_input or user_input.strip() == "":
                st.warning("⚠️ 请先输入提示词！")
                st.stop()

            # ---- 处理附件 ----
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
                        file_content = ""
                elif file_name.endswith(".docx"):
                    try:
                        doc = docx.Document(uploaded_file)
                        for para in doc.paragraphs:
                            file_content += para.text + "\n"
                    except Exception as e:
                        st.error(f"Word 解析失败：{e}")
                        file_content = ""

                if file_content and len(file_content) > 5000:
                    file_content = file_content[:5000] + "\n...[内容已截断]"

            # ---- 构建完整用户消息 ----
            if file_content:
                full_user_message = f"【上传文档内容】\n{file_content}\n\n【我的问题】\n{user_input}"
            else:
                full_user_message = user_input

            # ---- 显示用户消息 ----
            with st.chat_message("user"):
                if file_content:
                    st.markdown(f"📎 **已附加文档**，提问：{user_input}")
                else:
                    st.markdown(f"**[{clicked_behavior}]** {user_input}")

            st.session_state.messages.append({"role": "user", "content": full_user_message})

            # ---- 调用 AI ----
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

            # ---- 持久化 ----
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

            save_success = save_participant_state(
                st.session_state.participant_id,
                st.session_state.messages,
                st.session_state.round_count
            )
            if not save_success:
                st.warning("⚠️ 状态保存失败，但对话已生成。请截图保存本轮内容。")
            
            st.rerun()
