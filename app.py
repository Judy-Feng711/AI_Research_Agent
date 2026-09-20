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

    with st.container(key="main_row"):
        col_left, col_right = st.columns([55, 45], gap="large")
        with col_left:
            st.subheader("💬 研究人机交互区")
            st.markdown("**AI 学术助手对话**")
            st.caption(INITIAL_GREETING)

            # 使用新的聊天容器结构
            with st.container():
                # 聊天消息区域（可滚动）
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

                # 输入区域（固定在底部）
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
            st.subheader("📝 研究方案填写区")
            existing_plan = load_plan(st.session_state.participant_id)
            st.markdown("**AI协同研究方案撰写**")
            st.caption("任务共分为 6 个递进环节，请根据您与AI的完整对话，将各环节的核心成果填入下方对应模块。您可以在交互过程中随时记录，或最后集中整理。")
            with st.form(key="plan_form"):
                st.markdown("**子任务1：选题与文献发现**")
                task1_text = st.text_area(
                    "1.选题依据（现实痛点与文献空白）；2.核心研究问题；3.拟借鉴的核心理论视角。（建议150字左右）",
                    value=existing_plan["task1_text"] if existing_plan else "",
                    height=160,
                    key="task1_text"
                )
                st.divider()
                st.markdown("**子任务2：研究规划与设计**")
                task2_text = st.text_area(
                    "1.研究类型（量化/实验/质性/混合等）；2.具体的研究实施步骤及研究方法。（建议150字左右）",
                    value=existing_plan["task2_text"] if existing_plan else "",
                    height=160,
                    key="task2_text"
                )
                st.divider()
                st.markdown("**子任务3：实施与数据采集**")
                task3_text = st.text_area(
                    "1.研究对象与选取策略；2.数据收集工具（如问卷维度、访谈提纲、观察指标等）及采集过程。（建议150字左右）",
                    value=existing_plan["task3_text"] if existing_plan else "",
                    height=160,
                    key="task3_text"
                )
                st.divider()
                st.markdown("**子任务4：数据分析与阐释**")
                task4_text = st.text_area(
                    "1.数据分析工具或方法；2.各项数据分析的具体目的（即每一项分析分别用于说明或解决什么问题）。（建议150字左右）",
                    value=existing_plan["task4_text"] if existing_plan else "",
                    height=160,
                    key="task4_text"
                )
                st.divider()
                st.markdown("**子任务5：论文撰写与润色**")
                task5_text = st.text_area(
                    "1.研究的创新点（2-3项）；2.研究存在的不足（2-3项）。（建议300-500字左右）",
                    value=existing_plan["task5_text"] if existing_plan else "",
                    height=300,
                    key="task5_text"
                )
                st.divider()
                st.markdown("**子任务6：传播、评估与伦理**")
                task6_text = st.text_area(
                    "1.成果发表与传播的计划（如学术期刊投稿计划、学术会议汇报、转化为教学实践指南等）；2.研究的伦理考量及其应对措施（如数据隐私、AI使用披露等）。（建议150字左右）",
                    value=existing_plan["task6_text"] if existing_plan else "",
                    height=160,
                    key="task6_text"
                )
                st.markdown(
    """
    <style>
        textarea[aria-label="1.选题依据（现实痛点与文献空白）；2.核心研究问题；3.拟借鉴的核心理论视角。（建议150字左右）"] {
            background-color: #e6f3ff;
        }
        textarea[aria-label="1.研究类型（量化/实验/质性/混合等）；2.具体的研究实施步骤及研究方法。（建议150字左右）"] {
            background-color: #f5e6ff;
        }
        textarea[aria-label="1.研究对象与选取策略；2.数据收集工具（如问卷维度、访谈提纲、观察指标等）及采集过程。（建议150字左右）"] {
            background-color: #e6f3ff;
        }
        textarea[aria-label="1.数据分析工具或方法；2.各项数据分析的具体目的（即每一项分析分别用于说明或解决什么问题）。（建议150字左右）"] {
            background-color: #f5e6ff;
        }
        textarea[aria-label="1.研究的创新点（2-3项）；2.研究存在的不足（2-3项）。（建议300-500字左右）"] {
            background-color: #e6f3ff;
        }
        textarea[aria-label="1.成果发表与传播的计划（如学术期刊投稿计划、学术会议汇报、转化为教学实践指南等）；2.研究的伦理考量及其应对措施（如数据隐私、AI使用披露等）。（建议150字左右）"] {
            background-color: #f5e6ff;
        }
    </style>
    """,
    unsafe_allow_html=True
)
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
            st.rerun()基于以上代码，现在教育实证研究全周期智能协同框架上面的留白和退出实验按钮下面的留白太大了，以至于中间区域太小了，两边还要保持高度一致，美观大方，请不改变其他功能的情况下，帮我生成所有代码。
