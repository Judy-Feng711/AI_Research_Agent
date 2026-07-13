import streamlit as st
from openai import OpenAI
import pandas as pd
import datetime
import os

# ================= 1. 核心配置区 =================
DEEPSEEK_API_KEY = "sk-a51cfbe73d4a4fbb80db49277df9f0e2"
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
CSV_FILE = "research_interaction_logs.csv"

# ================= 2. 智能体系统提示词 =================
SYSTEM_PROMPT = """..."""  # 保持原有内容

# ================= 3. 页面初始化 =================
st.set_page_config(page_title="EduResearch Copilot", page_icon="🎓", layout="centered")

# 初始化所有 session_state 变量（必须放在最前面）
if "prompt_value" not in st.session_state:
    st.session_state.prompt_value = ""
if "participant_id" not in st.session_state:
    st.session_state.participant_id = ""
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": "你好！我是你的教育研究全栈助理。..."}
    ]

# ================= 4. 侧边栏（必须放在 st.stop() 之前） =================
with st.sidebar:
    # ----- 被试编号输入 -----
    st.markdown("### 👤 被试身份")
    if st.session_state.participant_id == "":
        pid_input = st.text_input("请输入你的被试编号（如 P001）：", key="pid_input")
        if pid_input:
            st.session_state.participant_id = pid_input.strip()
            st.success(f"编号已记录：{st.session_state.participant_id}")
            st.rerun()
    else:
        st.success(f"当前被试：{st.session_state.participant_id}")
        if st.button("重新输入编号（仅测试用）"):
            st.session_state.participant_id = ""
            st.rerun()
    
    st.divider()
    
    # ----- 研究者数据下载（密码保护） -----
    st.markdown("### 🔐 研究者数据导出")
    password = st.text_input("请输入数据导出密码", type="password")
    RESEARCHER_PASSWORD = "MyPassword123"  # 修改为你自己的密码
    
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

# ================= 5. 主页面内容 =================
st.title("🎓 EduResearch Copilot (教育研究全栈助理)")
st.markdown("欢迎！请输入你的科研提示词，并**选择最符合你当前行为意图的按钮**提交。")

# 显示当前被试编号
if st.session_state.participant_id:
    st.caption(f"👤 当前被试：{st.session_state.participant_id}")

# 展示历史对话
for msg in st.session_state.messages:
    if msg["role"] != "system":
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# ================= 6. 核心交互模块 =================
# 检查编号是否已填写（使用条件判断，而不是 st.stop()）
if st.session_state.participant_id == "":
    st.warning("⚠️ 请先在左侧边栏输入你的被试编号！")
    # 不执行 st.stop()，而是跳过后续交互逻辑
else:
    user_input = st.text_area(
        "在这里输入你的提示词 (Prompt)：",
        height=100,
        value=st.session_state.prompt_value
    )
    
    st.markdown("👇 **请点击以下按钮提交你的提示词（请选择最符合你当前意图的行为）：**")
    col1, col2, col3, col4, col5 = st.columns(5)
    behavior_clicked = None
    
    if col1.button("获取基础信息"): behavior_clicked = "获取基础信息"
    if col2.button("规范语言/格式"): behavior_clicked = "规范语言/格式"
    if col3.button("微调研究逻辑"): behavior_clicked = "微调研究逻辑"
    if col4.button("重构研究方案"): behavior_clicked = "重构研究方案"
    if col5.button("拓展研究思路"): behavior_clicked = "拓展研究思路"
    
    if user_input and behavior_clicked:
        with st.chat_message("user"):
            st.markdown(f"**[{behavior_clicked}]** {user_input}")
        st.session_state.messages.append({"role": "user", "content": user_input})
        
        with st.chat_message("assistant"):
            with st.spinner("思考中..."):
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=st.session_state.messages
                )
                ai_reply = response.choices[0].message.content
                st.markdown(ai_reply)
        st.session_state.messages.append({"role": "assistant", "content": ai_reply})
        
        new_data = pd.DataFrame([{
            "Timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Participant_ID": st.session_state.participant_id,
            "User_Prompt": user_input,
            "Behavior_Button": behavior_clicked,
            "AI_Response": ai_reply
        }])
        
        if not os.path.isfile(CSV_FILE):
            new_data.to_csv(CSV_FILE, index=False, encoding='utf-8-sig')
        else:
            new_data.to_csv(CSV_FILE, mode='a', header=False, index=False, encoding='utf-8-sig')
        
        st.session_state.prompt_value = ""
        st.rerun()
    
    elif behavior_clicked and not user_input:
        st.warning("请先输入提示词，再点击行为按钮哦！")
