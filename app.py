from pypdf import PdfReader
import docx
import streamlit as st
from openai import OpenAI
import pandas as pd
import datetime
import json
from supabase import create_client, Client
import time

# ... (前面的代码保持不变) ...

# ================= 8. 根据角色显示内容 =================
if st.session_state.user_role == "研究者":
    # ---------- 研究者模式（居中，密码框缩小，验证在下方） ----------
    col_space1, col_center, col_space2 = st.columns([1, 2, 1])
    with col_center:
        # 使用 markdown 强制居中标题
        st.markdown("<h3 style='text-align: center;'>📊 研究者数据导出</h3>", unsafe_allow_html=True)
        st.markdown(
            "<p style='text-align: center;'>请输入研究者密码以查看并下载数据</p>",
            unsafe_allow_html=True
        )
        if "export_authorized" not in st.session_state:
            st.session_state.export_authorized = False
        if not st.session_state.export_authorized:
            # 密码框居中，宽度约为总宽的 1/2
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                export_pass = st.text_input(
                    "密码",
                    type="password",
                    key="export_pass",
                    label_visibility="collapsed",
                    placeholder="请输入密码"
                )
            # 验证按钮居中，宽度约为总宽的 1/3
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

# ... (后面的被试模式代码保持不变) ...
