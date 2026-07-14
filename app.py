import streamlit as st
from openai import OpenAI
import pandas as pd
import datetime
import os
from supabase import create_client, Client

# ================= 1. 核心配置区（所有密钥从secrets读取） =================
DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ================= 2. 智能体系统提示词 =================
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

# ================= 3. 页面初始化 =================
st.set_page_config(page_title="EduResearch Copilot", page_icon="🎓", layout="centered")

if "prompt_value" not in st.session_state:
    st.session_state.prompt_value = ""
if "participant_id" not in st.session_state:
    st.session_state.participant_id = ""
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": "你好！我是你的教育研究全栈助理。无论你目前正卡在寻找文献的理论Gap，还是纠结数据分析的逻辑推演，亦或是需要模拟审稿人为你挑刺，我都在这里。请详细告诉我：你目前正在推进哪一项具体的教育学研究任务？"}
    ]
if "round_count" not in st.session_state:
    st.session_state.round_count = 0

# ================= 4. 侧边栏 =================
with st.sidebar:
    st.markdown("### 👤 被试身份")
    if st.session_state.participant_id == "":
        pid_input = st.text_input("请输入你的被试编号（如 P001）：", key="pid_input")
        if pid_input:
            st.session_state.participant_id = pid_input.strip()
            st.success(f"编号已记录：{st.session_state.participant_id}")
            st.rerun()
    else:
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

# ================= 5. 主页面 =================
st.title("🎓 EduResearch Copilot (教育研究全栈助理)")
st.markdown("欢迎！请输入你的科研提示词，并**选择最符合你当前行为意图的按钮**提交。")

if st.session_state.participant_id:
    st.caption(f"👤 当前被试：{st.session_state.participant_id}")

for msg in st.session_state.messages:
    if msg["role"] != "system":
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# ================= 6. 核心交互模块 =================
if st.session_state.participant_id == "":
    st.warning("⚠️ 请先在左侧边栏输入你的被试编号！")
else:
    user_input = st.text_area(
        "在这里输入你的提示词 (Prompt)：",
        height=100,
        value=st.session_state.prompt_value
    )

    st.markdown("👇 **请点击以下按钮提交你的提示词（请选择最符合你当前意图的行为）：**")
    col1, col2, col3, col4, col5 = st.columns(5)
    behavior_clicked = None

    if col1.button("获取基础信息"):
        behavior_clicked = "获取基础信息"
    elif col2.button("规范语言/格式"):
        behavior_clicked = "规范语言/格式"
    elif col3.button("微调研究逻辑"):
        behavior_clicked = "微调研究逻辑"
    elif col4.button("重构研究方案"):
        behavior_clicked = "重构研究方案"
    elif col5.button("拓展研究思路"):
        behavior_clicked = "拓展研究思路"

    if user_input and behavior_clicked:
        with st.chat_message("user"):
            st.markdown(f"**[{behavior_clicked}]** {user_input}")
        st.session_state.messages.append({"role": "user", "content": user_input})

        with st.chat_message("assistant"):
            with st.spinner("思考中..."):
                try:
                    response = client.chat.completions.create(
                        model="deepseek-chat",
                        messages=st.session_state.messages
                    )
                    ai_reply = response.choices[0].message.content
                    st.markdown(ai_reply)
                except Exception as e:
                    st.error(f"AI 调用失败：{e}")
                    st.stop()
        st.session_state.messages.append({"role": "assistant", "content": ai_reply})

        # 记录数据到 Supabase
        data_to_insert = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "participant_id": st.session_state.participant_id,
            "round": st.session_state.round_count + 1,
            "user_prompt": user_input,
            "behavior_button": behavior_clicked,
            "ai_response": ai_reply
        }
        try:
            supabase.table("research_logs").insert(data_to_insert).execute()
        except Exception as e:
            st.error(f"数据存储失败（但对话已生成）：{e}")

        st.session_state.round_count += 1
        st.session_state.prompt_value = ""
        st.rerun()

    elif behavior_clicked and not user_input:
        st.warning("请先输入提示词，再点击行为按钮哦！")
