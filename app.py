import streamlit as st
from openai import OpenAI
import pandas as pd
import datetime
import os

# ================= 1. 核心配置区 =================
# 替换为你刚刚在DeepSeek官网生成的 API Key (sk-开头)
DEEPSEEK_API_KEY = "sk-a51cfbe73d4a4fbb80db49277df9f0e2"

# 初始化 DeepSeek 客户端 (调用格式与OpenAI完全一致)
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# 定义保存数据的文件名
CSV_FILE = "research_interaction_logs.csv"

# ================= 2. 智能体系统提示词 (System Prompt) =================
SYSTEM_PROMPT = """你是一个名为“全栈式教育研究学术助理”的高级AI。你的目标是深度辅助教育学领域的研究生完成真实、复杂的学术研究任务，而非简单地给出敷衍的现成答案。你需要展现出教育研究的专业性、批判性和逻辑性。
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

# ================= 3. 页面初始化与状态管理 =================
st.set_page_config(page_title="EduResearch Copilot", page_icon="🎓", layout="centered")
# 初始化提示词的值
if "prompt_value" not in st.session_state:
    st.session_state.prompt_value = ""
st.title("🎓 EduResearch Copilot (教育研究全栈助理)")
st.markdown("欢迎！请输入你的科研提示词，并**选择最符合你当前行为意图的按钮**提交。")

if "participant_id" not in st.session_state:
    st.session_state.participant_id = ""

# 显示当前被试编号（如果已设置）
if st.session_state.participant_id:
    st.caption(f"👤 当前被试：{st.session_state.participant_id}")



# 初始化对话历史记录
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": "你好！我是你的教育研究全栈助理。无论你目前正卡在寻找文献的理论Gap，还是纠结数据分析的逻辑推演，亦或是需要模拟审稿人为你挑刺，我都在这里。请详细告诉我：你目前正在推进哪一项具体的教育学研究任务？"}
    ]

# 展示历史对话 (隐藏系统提示词)
for msg in st.session_state.messages:
    if msg["role"] != "system":
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# 初始化被试编号
if "participant_id" not in st.session_state:
    st.session_state.participant_id = ""
    
# ================= 4. 核心交互与数据记录模块 =================
# 使用文本框接收用户输入
user_input = st.text_area(
    "在这里输入你的提示词 (Prompt)：",
    height=100,
    value=st.session_state.prompt_value
)

st.markdown("👇 **请点击以下按钮提交你的提示词（请选择最符合你当前意图的行为）：**")

# 将你问卷中的5个行为分类做成5个并排的按钮
col1, col2, col3, col4, col5 = st.columns(5)
behavior_clicked = None

if col1.button("获取基础信息"): behavior_clicked = "获取基础信息"
if col2.button("规范语言/格式"): behavior_clicked = "规范语言/格式"
if col3.button("微调研究逻辑"): behavior_clicked = "微调研究逻辑"
if col4.button("重构研究方案"): behavior_clicked = "重构研究方案"
if col5.button("拓展研究思路"): behavior_clicked = "拓展研究思路"

# 检查编号是否已填写
if st.session_state.participant_id == "":
    st.warning("⚠️ 请先在左侧边栏输入你的被试编号！")
    # 阻止后续执行，可以使用 st.stop()
    st.stop()

# 如果用户输入了文字，并且点击了任意一个行为按钮
if user_input and behavior_clicked:
    # 1. 在界面上显示用户消息
    with st.chat_message("user"):
        st.markdown(f"**[{behavior_clicked}]** {user_input}")
    
    # 将用户消息加入上下文
    st.session_state.messages.append({"role": "user", "content": user_input})
    
    # 2. 调用 DeepSeek 大模型获取回复
    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=st.session_state.messages
            )
            ai_reply = response.choices[0].message.content
            st.markdown(ai_reply)
    
    # 将AI消息加入上下文
    st.session_state.messages.append({"role": "assistant", "content": ai_reply})
    
    # 3. 核心：将交互数据偷偷存入本地 CSV 文件！
    new_data = pd.DataFrame([{
        "Timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Participant_ID": st.session_state.participant_id,  # 新增
        "User_Prompt": user_input,
        "Behavior_Button": behavior_clicked,
        "AI_Response": ai_reply
    }])
    
    # 如果文件不存在则写入表头，存在则追加写入
    if not os.path.isfile(CSV_FILE):
        new_data.to_csv(CSV_FILE, index=False, encoding='utf-8-sig')
    else:
        new_data.to_csv(CSV_FILE, mode='a', header=False, index=False, encoding='utf-8-sig')
    
    # 清空输入框的值
    st.session_state.prompt_value = ""
    # 刷新页面以显示新消息并清空输入框
    st.rerun()

elif behavior_clicked and not user_input:
    st.warning("请先输入提示词，再点击行为按钮哦！")



# 数据下载功能
# ================= 5. 研究员专用数据下载（侧边栏密码保护） =================


with st.sidebar:
    st.markdown("### 🔐 研究者数据导出")
    password = st.text_input("请输入数据导出密码", type="password")
    
    # 设置一个只有你知道的密码（建议稍后改用 st.secrets 管理）
    RESEARCHER_PASSWORD = "MyPassword123"  # 请修改为你自己的密码
    
    if password:
        if password == RESEARCHER_PASSWORD:
            st.success("密码正确，可以下载数据")
            if os.path.exists(CSV_FILE):
                with open(CSV_FILE, "rb") as f:
                    st.download_button(
                        label="📥 下载全部交互数据",
                        data=f,
                        file_name="research_logs.csv",
                        mime="text/csv"
                    )
            else:
                st.info("暂无数据文件，请等待被试完成交互。")
        else:
            st.error("密码错误，无权限下载")
    else:
        st.info("请输入密码以导出数据")
# ================= 6. 被试身份识别（侧边栏） =================
with st.sidebar:
    st.markdown("### 👤 被试身份")
    # 如果尚未输入编号，显示输入框；否则显示已确认的编号
    if st.session_state.participant_id == "":
        pid_input = st.text_input("请输入你的被试编号（如 P001）：", key="pid_input")
        if pid_input:
            # 编号非空时，保存到 session_state
            st.session_state.participant_id = pid_input.strip()
            st.success(f"编号已记录：{st.session_state.participant_id}")
            st.rerun()  # 刷新页面以清除输入框并显示确认信息
    else:
        st.success(f"当前被试：{st.session_state.participant_id}")
        # 提供一个“重置”按钮，方便测试（但正式实验建议隐藏或删除）
        if st.button("重新输入编号（仅测试用）"):
            st.session_state.participant_id = ""
            st.rerun()
