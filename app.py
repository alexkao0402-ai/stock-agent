# app.py
# 這是 Streamlit 網頁版的入口
# 這一步：加入公司基本面資料，串接完整的分析流程

import pandas as pd
import streamlit as st
from src.stock_data import get_daily_stock_data, clean_stock_data, get_news_sentiment, get_company_overview
from src.ai_analysis import generate_report, extract_structured_data
from src.prediction_tracker import save_prediction, list_predictions, check_prediction_outcome
from src.strategy import add_moving_averages, add_signals, run_backtest
from src.stock_data import get_long_history_stock_data
from src.strategy_v1 import (
    add_trend_filter, add_momentum, add_relative_strength,
    add_entry_exit_signals, run_backtest_v1,
    calculate_buy_and_hold, calculate_performance_metrics
)
import time
from src.strategy_v1 import (
    run_backtest_v1_with_equity_curve, run_backtest_v1_with_takeprofit_v2,
    run_backtest_v1_with_trailing_exit, calculate_risk_metrics, build_comparison_row
)
from src.regime_analysis import build_regime_series


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

            # 建立七個分頁
            tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["📄 AI 研究報告", "📈 原始股價資料", "📰 新聞列表", "🏢 公司基本面", "🔢 結構化數據", "📉 均線策略回測", "🎯 Strategy V1"])
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

            with tab7:
                st.caption("Strategy V1：趨勢過濾(MA200) + 6個月動能 + 相對BTC強弱，三條件同時成立才進場。含交易成本、滑價，並與Buy & Hold比較。")

                with st.spinner("正在抓取長期歷史資料並執行回測（約需20-30秒）..."):
                    v1_stock_df = get_long_history_stock_data(symbol, period="2y")

                    if v1_stock_df.empty or len(v1_stock_df) < 200:
                        st.warning("這支股票的歷史資料不足200天，無法計算MA200，暫時無法執行Strategy V1回測。")
                    else:
                        from src.stock_data import get_crypto_daily_data, clean_crypto_data
                        raw_crypto = get_crypto_daily_data("BTC", "USD")
                        crypto_df = clean_crypto_data(raw_crypto)

                        v1_stock_df = add_trend_filter(v1_stock_df)
                        v1_stock_df = add_momentum(v1_stock_df)
                        v1_stock_df = add_relative_strength(v1_stock_df, crypto_df)
                        v1_stock_df = add_entry_exit_signals(v1_stock_df)

                        v1_result = run_backtest_v1(v1_stock_df)
                        bh_result = calculate_buy_and_hold(v1_stock_df)
                        v1_metrics = calculate_performance_metrics(
                            v1_result["trades"], v1_result["initial_capital"],
                            v1_result["final_value"], v1_stock_df
                        )

                        # 圖表：收盤價 + MA200
                        chart_df = v1_stock_df.set_index("date")[["close", "ma200"]]
                        st.line_chart(chart_df)

                        # 用表格清楚標示每一次買賣訊號發生的日期與價格，方便對照上面的走勢圖
                        signal_points = v1_stock_df[v1_stock_df["signal"].notna()][["date", "close", "signal", "execution_price"]]
                        if len(signal_points) > 0:
                            st.caption("訊號點位（訊號當天收盤價 vs 隔天實際成交價）：")
                            st.dataframe(signal_points, use_container_width=True)

                        st.subheader("Strategy V1 vs Buy & Hold")
                        col1, col2 = st.columns(2)
                        col1.metric("Strategy V1 總報酬率", f"{v1_result['total_return_pct']}%")
                        col2.metric("Buy & Hold 總報酬率", f"{bh_result['total_return_pct']}%")

                        st.subheader("完整績效指標")
                        col3, col4, col5, col6 = st.columns(4)
                        col3.metric("CAGR", f"{v1_metrics['cagr_pct']}%")
                        col4.metric("勝率", f"{v1_metrics['win_rate_pct']}%")
                        col5.metric("交易次數", v1_metrics['number_of_completed_trades'])
                        col6.metric("獲利因子", v1_metrics['profit_factor'])

                        if v1_metrics["completed_trades"]:
                            st.subheader("交易診斷報告（含最大有利/不利偏移）")
                            st.caption("MFE = 持有期間股價曾漲到的最高點（相對進場價）；MAE = 持有期間股價曾跌到的最低點（相對進場價）。若MFE遠高於最終報酬，代表出場時機可能太晚。")

                            from src.strategy_v1 import build_trade_diagnostics
                            diagnostics = build_trade_diagnostics(v1_stock_df, v1_metrics["completed_trades"])
                            diag_df = pd.DataFrame(diagnostics)
                            st.dataframe(diag_df, use_container_width=True)

                        st.caption("⚠️ 此為規則型策略回測，完全不使用AI判斷。過去表現不代表未來績效，且此策略在特定股票上可能表現不佳，這是正常且重要的研究發現，不代表系統有誤。")
                        st.markdown("---")
                        st.subheader("策略版本完整比較")
                        st.caption("比較 V1原版、V1+固定停利25%、V1+移動停損20%、Buy&Hold 四種版本的完整績效指標")

                        with st.spinner("正在計算完整比較表..."):
                            v1_eq_result = run_backtest_v1_with_equity_curve(v1_stock_df)
                            v1_eq_risk = calculate_risk_metrics(v1_eq_result["equity_curve"])
                            v1_eq_perf = calculate_performance_metrics(
                                v1_eq_result["trades"], v1_eq_result["initial_capital"],
                                v1_eq_result["final_value"], v1_stock_df
                            )
                            row_v1 = build_comparison_row(symbol, "V1", v1_eq_result, v1_eq_risk, v1_eq_perf)

                            tp_result = run_backtest_v1_with_takeprofit_v2(v1_stock_df, take_profit_pct=25.0)
                            tp_perf = calculate_performance_metrics(
                                tp_result["trades"], tp_result["initial_capital"],
                                tp_result["final_value"], v1_stock_df
                            )
                            row_tp = build_comparison_row(symbol, "V1+TakeProfit25", tp_result, None, tp_perf)

                            trail_result = run_backtest_v1_with_trailing_exit(v1_stock_df, trailing_pct=20.0)
                            trail_perf = calculate_performance_metrics(
                                trail_result["trades"], trail_result["initial_capital"],
                                trail_result["final_value"], v1_stock_df
                            )
                            row_trail = build_comparison_row(symbol, "V1+Trailing20", trail_result, None, trail_perf)

                            row_bh = build_comparison_row(symbol, "Buy&Hold", bh_result, None, None)

                            comparison_df = pd.DataFrame([row_v1, row_tp, row_trail, row_bh])

                        st.dataframe(comparison_df, use_container_width=True)
                        st.caption("Volatility/Sharpe/Sortino/MaxDD顯示為空白的策略，代表該版本目前尚未實作逐日權益曲線，這是已知的功能限制，非計算錯誤。")

                        st.markdown("---")
                        st.subheader("市場狀態分析")
                        st.caption("依據 SPY 與 BTC 各自的200日均線趨勢，將市場分為 Risk-On／Risk-Off／Mixed 三種狀態（規則未依歷史績效校準）")

                        with st.spinner("正在分析市場狀態..."):
                            regime_df = build_regime_series(period="2y")

                        regime_counts = regime_df["regime"].value_counts()
                        col7, col8, col9 = st.columns(3)
                        col7.metric("Risk-On 天數", regime_counts.get("Risk-On", 0))
                        col8.metric("Risk-Off 天數", regime_counts.get("Risk-Off", 0))
                        col9.metric("Mixed 天數", regime_counts.get("Mixed", 0))

                        st.caption("⚠️ 完整方法論說明與研究誠信聲明，請參見專案根目錄 RESEARCH_FINDINGS.md")

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