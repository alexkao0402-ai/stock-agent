# app.py
# 這是 Streamlit 網頁版的入口
# 這一步：把輸入框、按鈕接上完整的分析流程

import streamlit as st
from src.stock_data import get_daily_stock_data, clean_stock_data, get_news_sentiment
from src.ai_analysis import generate_report
import time

st.set_page_config(page_title="AI 股票研究助理", page_icon="📈")

st.title("📈 AI 股票研究助理")
st.write("輸入股票代號，取得歷史股價、新聞分析與 AI 研究報告。")
st.caption("本工具僅供教育與研究用途，所有內容皆非投資建議。")

symbol_input = st.text_input("請輸入股票代號", placeholder="例如 BTDR")

if st.button("開始分析"):
    if not symbol_input.strip():
        st.warning("請先輸入股票代號。")
    else:
        symbol = symbol_input.strip().upper()

        with st.spinner(f"正在抓取 {symbol} 的歷史股價資料..."):
            raw_data = get_daily_stock_data(symbol)

        if "Time Series (Daily)" not in raw_data:
            st.error("抓取股價資料失敗，請確認股票代號是否正確，或稍後再試。")
        else:
            df = clean_stock_data(raw_data)
            st.success(f"成功取得 {len(df)} 筆股價資料，時間範圍：{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")

            with st.spinner(f"正在抓取 {symbol} 的相關新聞..."):
                time.sleep(15)
                news_list = get_news_sentiment(symbol, limit=20)
            st.success(f"成功取得 {len(news_list)} 則新聞")

            with st.spinner("正在請 AI 分析資料，請稍候（約需 30 秒到 1 分鐘）..."):
                report = generate_report(symbol, df, news_list)

            st.markdown("---")
            st.subheader("研究報告")
            st.markdown(report)