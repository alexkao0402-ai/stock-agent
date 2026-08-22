# app.py
# 這是 Streamlit 網頁版的入口
# 這一步：加入公司基本面資料，串接完整的分析流程

import streamlit as st
from src.stock_data import get_daily_stock_data, clean_stock_data, get_news_sentiment, get_company_overview
from src.ai_analysis import generate_report, extract_structured_data
from src.prediction_tracker import save_prediction, list_predictions, check_prediction_outcome
from src.strategy import add_moving_averages, add_signals, run_backtest
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

            with st.spinner(f"正在抓取 {symbol} 的公司基本面資料..."):
                time.sleep(15)
                overview = get_company_overview(symbol)
            if overview:
                st.success("成功取得公司基本面資料")
            else:
                st.info("未取得公司基本面資料，報告將僅根據股價與新聞進行分析")

            with st.spinner("正在請 AI 分析資料，請稍候（約需 30 秒到 1 分鐘）..."):
                report = generate_report(symbol, df, news_list, overview)

            with st.spinner("正在整理結構化數據..."):
                current_price = df["close"].iloc[-1]
                structured = extract_structured_data(symbol, current_price, report)

            # 把這次的分析結果存成永久紀錄，供未來追蹤預測準確度使用
            saved_path = save_prediction(symbol, current_price, structured, report)
            st.info(f"📁 這次的預測已存檔：{saved_path}")

            st.markdown("---")

            # 建立六個分頁
            tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📄 AI 研究報告", "📈 原始股價資料", "📰 新聞列表", "🏢 公司基本面", "🔢 結構化數據", "📉 均線策略回測"])
            with tab1:
                chart_data = df.set_index("date")[["close"]]
                st.line_chart(chart_data)
                st.markdown(report)

            with tab2:
                st.dataframe(df.sort_values("date", ascending=False), use_container_width=True)

            with tab3:
                for n in news_list:
                    st.markdown(f"**{n['title']}**")
                    st.caption(f"{n['time_published']}　|　{n['source']}　|　情緒：{n['overall_sentiment_label']}")
                    st.markdown("---")

            with tab4:
                if overview:
                    for key, value in overview.items():
                        if key == "公司簡介":
                            st.markdown(f"**{key}**")
                            st.write(value)
                        else:
                            st.markdown(f"**{key}**：{value}")
                else:
                    st.write("未取得公司基本面資料。")

            with tab5:
                st.caption("這是從 AI 報告中萃取出的結構化數字，可用於之後的預測追蹤與回測。")
                if structured:
                    st.json(structured)
                else:
                    st.warning("這次未能成功解析出結構化數據，AI 回傳格式可能不符預期。")

            with tab6:
                st.caption("這是一個規則型策略（均線交叉），完全不使用 AI 判斷，純粹依歷史股價計算，避免先見偏誤。")

                df_ma = add_moving_averages(df)
                df_signals = add_signals(df_ma)

                # 畫出收盤價 + 兩條均線的走勢圖，方便直觀看出交叉點
                chart_df = df_signals.set_index("date")[["close", "ma_short", "ma_long"]]
                st.line_chart(chart_df)

                # 顯示所有觸發過的訊號
                signal_rows = df_signals[df_signals["signal"].notna()]
                st.subheader("觸發訊號")
                if len(signal_rows) > 0:
                    st.dataframe(signal_rows[["date", "close", "ma_short", "ma_long", "signal"]], use_container_width=True)
                else:
                    st.write("這段期間沒有觸發任何交叉訊號。")

                # 執行回測，顯示績效
                st.subheader("回測績效（模擬本金 $10,000）")
                backtest_result = run_backtest(df_signals)

                col1, col2, col3 = st.columns(3)
                col1.metric("最終價值", f"${backtest_result['final_value']:,}")
                col2.metric("總報酬率", f"{backtest_result['total_return_pct']}%")
                col3.metric("交易次數", backtest_result['number_of_trades'])

                st.caption("⚠️ 此回測結果僅反映過去這段期間的表現，不代表未來績效，且未考慮手續費與滑點。")

st.markdown("---")
st.header("📊 歷史預測回顧")
st.caption("查看過去存下的預測紀錄，並比對現在的實際股價是否落在當初推估的區間內。")

all_predictions = list_predictions()

if not all_predictions:
    st.write("目前還沒有任何預測紀錄。")
else:
    # 用「股票代號 + 時間」組成選單選項，方便使用者辨識
    options = [f"{r['ticker']} — {r['timestamp']}" for r in all_predictions]
    selected_index = st.selectbox("選擇一筆歷史預測", range(len(options)), format_func=lambda i: options[i])

    selected_record = all_predictions[selected_index]

    st.write(f"**股票代號：** {selected_record['ticker']}")
    st.write(f"**預測時間：** {selected_record['timestamp']}")
    st.write(f"**當時股價：** ${selected_record.get('current_price_at_prediction')}")
    st.write(f"**Bull 區間：** {selected_record.get('bull_low')} ~ {selected_record.get('bull_high')}")
    st.write(f"**Base 區間：** {selected_record.get('base_low')} ~ {selected_record.get('base_high')}")
    st.write(f"**Bear 區間：** {selected_record.get('bear_low')} ~ {selected_record.get('bear_high')}")

    if selected_record.get("outcome_checked"):
        st.success("✅ 這筆預測已經驗證過結果")
        st.write(f"**驗證時間：** {selected_record.get('checked_at')}")
        st.write(f"**當時查詢到的實際股價：** ${selected_record.get('actual_price_at_check')}")
        st.write(f"**實際報酬率：** {selected_record.get('actual_return_pct')}%")
        st.write(f"**落在哪個情境：** {selected_record.get('which_scenario_occurred')}")
    else:
        st.info("這筆預測尚未驗證結果")
        if st.button("🔍 查詢目前股價並驗證這筆預測"):
            with st.spinner("正在查詢目前股價..."):
                raw = get_daily_stock_data(selected_record["ticker"])
                if "Time Series (Daily)" in raw:
                    latest_df = clean_stock_data(raw)
                    actual_price = latest_df["close"].iloc[-1]
                    updated = check_prediction_outcome(selected_record, actual_price)
                    st.success(f"驗證完成！目前股價：${actual_price}，落在：{updated['which_scenario_occurred']}")
                    st.rerun()
                else:
                    st.error("查詢目前股價失敗，請稍後再試。")