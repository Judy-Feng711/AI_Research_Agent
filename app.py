import streamlit as st
from openai import OpenAI
import pandas as pd
import datetime
import os

# ================= 1. 核心配置区 =================
# 替换为你刚刚在DeepSeek官网生成的 API Key (sk-开头)
DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]

# 初始化 DeepSeek 客户端 (调用格式与OpenAI完全一致)
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

# 定义保存数据的文件名
CSV_FILE = r"D:\AI_Research_Agent\research_interaction_logs.csv"

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
st.title("🎓 EduResearch Copilot (教育研究全栈助理)")
st.markdown("欢迎！请输入你的科研提示词，并**选择最符合你当前行为意图的按钮**提交。")

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

# ================= 4. 核心交互与数据记录模块 =================
# 使用文本框接收用户输入
user_input = st.text_area("在这里输入你的提示词 (Prompt)：", height=100)

st.markdown("👇 **请点击以下按钮提交你的提示词（请选择最符合你当前意图的行为）：**")

# 将你问卷中的5个行为分类做成5个并排的按钮
col1, col2, col3, col4, col5 = st.columns(5)
behavior_clicked = None

if col1.button("直接获取"): behavior_clicked = "直接获取"
if col2.button("语病排版"): behavior_clicked = "语病排版"
if col3.button("微调逻辑"): behavior_clicked = "微调逻辑"
if col4.button("大幅改写"): behavior_clicked = "大幅改写"
if col5.button("深层追问"): behavior_clicked = "深层追问"

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
        "User_Prompt": user_input,
        "Behavior_Button": behavior_clicked,
        "AI_Response": ai_reply
    }])
    
    # 如果文件不存在则写入表头，存在则追加写入
    if not os.path.isfile(CSV_FILE):
        new_data.to_csv(CSV_FILE, index=False, encoding='utf-8-sig')
    else:
        new_data.to_csv(CSV_FILE, mode='a', header=False, index=False, encoding='utf-8-sig')
    
    # 刷新页面以清空输入框
    st.rerun()

elif behavior_clicked and not user_input:
    st.warning("请先输入提示词，再点击行为按钮哦！")