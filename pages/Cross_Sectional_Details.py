"""Visual audit dashboard for Cross-Sectional Momentum."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.backtest_engine import BacktestConfig, run_buy_and_hold
from src.cross_sectional import cross_sectional_momentum_backtest, equal_weight_buy_and_hold
from src.cross_sectional_analytics import (
    drawdown_series,
    monthly_return_matrix,
    open_position_ledger,
    realized_trade_ledger,
    rebalance_summary,
    stock_contribution,
)
from src.performance import calculate_equity_metrics
from src.stock_data import get_long_history_stock_data


UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT"]
CONFIG = BacktestConfig(initial_capital=10_000, transaction_cost_pct=0.001, slippage_pct=0.0005)

st.set_page_config(page_title="Cross-Sectional Details", page_icon="🔄", layout="wide", initial_sidebar_state="auto")
st.markdown(
    """
    <style>
      div[data-testid="stDataFrame"] {max-width: 100%; overflow-x: auto;}
      .block-container {max-width: 1280px;}
      @media (max-width: 720px) {
        .block-container {padding-left: .75rem; padding-right: .75rem;}
        div[data-testid="stMetric"] {min-width: 0;}
        div[data-testid="stMetricValue"] {font-size: 1.25rem; overflow-wrap: anywhere;}
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Cross-Sectional Momentum · 完整回測")
st.caption("每 20 個交易日重新排名大型股，持有排名最高且位於 MA200 上方的前 20%；T 日收盤決策，T+1 開盤成交。")
st.info("這是約每月一次的換股週期，不是每個曆月固定日期。所有損益均使用實際回測成交價並計入佣金與滑價。")


@st.cache_data(ttl=3600, show_spinner=False)
def load_detail_data():
    spy = get_long_history_stock_data("SPY", period="5y")
    prices = {symbol: get_long_history_stock_data(symbol, period="5y") for symbol in UNIVERSE}
    return prices, spy


with st.spinner("整理五年換股、成交與損益明細…"):
    price_data, spy_df = load_detail_data()
    if spy_df.empty or any(frame.empty for frame in price_data.values()):
        st.error("歷史行情不完整，暫時無法建立 Cross-Sectional 明細。")
        st.stop()
    try:
        result = cross_sectional_momentum_backtest(price_data, spy_df, CONFIG)
        universe_bh = equal_weight_buy_and_hold(price_data, CONFIG)
        spy_bh = run_buy_and_hold(spy_df, "SPY", CONFIG)
        cycles = rebalance_summary(result)
        closed = realized_trade_ledger(result["trades"])
        opened = open_position_ledger(result, price_data)
        contribution = stock_contribution(result, price_data)
    except (KeyError, ValueError, IndexError) as exc:
        st.error(f"回測明細產生失敗：{exc}")
        st.stop()

metrics = calculate_equity_metrics(result)
universe_metrics = calculate_equity_metrics(universe_bh)
spy_metrics = calculate_equity_metrics(spy_bh)
total_cost = sum(float(trade["transaction_cost"]) for trade in result["trades"])

st.subheader("一眼看懂結果")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("期末資產", f"${metrics['Final Value']:,.0f}")
c2.metric("總報酬", f"{metrics['Total Return %']:+.1f}%")
c3.metric("vs 等權持有", f"{metrics['Total Return %'] - universe_metrics['Total Return %']:+.1f}%")
c4.metric("最大回撤", f"{metrics['Max Drawdown %']:.1f}%")
c5.metric("總交易成本", f"${total_cost:,.0f}")

current_holdings = ", ".join(result.get("open_holdings", [])) or "現金"
st.success(f"目前回測期末持股：{current_holdings}　｜　換股週期：{len(cycles)} 次　｜　成交紀錄：{len(result['trades'])} 筆")

st.subheader("資產成長比較")
figure = go.Figure()
for label, item, color in (
    ("Cross-Sectional", result, "#32D583"),
    ("10 檔等權持有", universe_bh, "#53B1FD"),
    ("SPY", spy_bh, "#F97066"),
):
    curve = item["equity_curve"].copy()
    curve["date"] = pd.to_datetime(curve["date"])
    figure.add_trace(go.Scatter(x=curve["date"], y=curve["equity"], name=label, mode="lines", line={"color": color, "width": 2}))
figure.update_layout(
    height=520,
    margin={"l": 12, "r": 12, "t": 20, "b": 10},
    hovermode="x unified",
    yaxis_title="資產價值（美元）",
    legend={"orientation": "h", "y": 1.08},
    xaxis={
        "rangeselector": {"buttons": [
            {"count": 6, "label": "6M", "step": "month", "stepmode": "backward"},
            {"count": 1, "label": "1Y", "step": "year", "stepmode": "backward"},
            {"count": 3, "label": "3Y", "step": "year", "stepmode": "backward"},
            {"step": "all", "label": "全部"},
        ]},
        "rangeslider": {"visible": True},
    },
)
st.plotly_chart(figure, width="stretch", config={"scrollZoom": True, "displaylogo": False})

left, right = st.columns(2)
with left:
    st.subheader("回撤")
    dd = drawdown_series(result["equity_curve"])
    dd_fig = go.Figure(go.Scatter(x=dd["date"], y=dd["Drawdown %"], fill="tozeroy", line={"color": "#F97066"}, name="Drawdown"))
    dd_fig.update_layout(height=330, margin={"l": 10, "r": 10, "t": 10, "b": 10}, yaxis_title="回撤 %", hovermode="x unified")
    st.plotly_chart(dd_fig, width="stretch", config={"displaylogo": False})

with right:
    st.subheader("每月報酬熱圖")
    monthly = monthly_return_matrix(result["equity_curve"], CONFIG.initial_capital)
    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    heat = go.Figure(go.Heatmap(
        z=monthly.reindex(columns=range(1, 13)).values,
        x=month_labels,
        y=monthly.index.astype(str),
        colorscale=[[0, "#F04438"], [0.5, "#F2F4F7"], [1, "#12B76A"]],
        zmid=0,
        text=monthly.reindex(columns=range(1, 13)).round(1).values,
        texttemplate="%{text}%",
        hovertemplate="%{y} %{x}: %{z:.2f}%<extra></extra>",
    ))
    heat.update_layout(height=330, margin={"l": 10, "r": 10, "t": 10, "b": 10})
    st.plotly_chart(heat, width="stretch", config={"displaylogo": False})

st.subheader("每次換股：買誰、賣誰、該週期賺賠多少")
st.caption("Cycle P&L 是這次成交日收盤至下一次訊號日收盤的投資組合損益；Trading Cost 是該次換股的佣金，滑價已反映在成交價。")
cycle_view = cycles.copy()
for column in ("Cycle P&L", "Realized P&L at Rebalance", "Trading Cost"):
    cycle_view[column] = cycle_view[column].round(2)
for column in ("Cycle Return %", "Turnover %"):
    cycle_view[column] = cycle_view[column].round(2)
st.dataframe(
    cycle_view[[
        "Signal Date", "Execution Date", "Regime", "Selected Holdings", "Bought", "Sold",
        "Cycle P&L", "Cycle Return %", "Realized P&L at Rebalance", "Trading Cost", "Turnover %",
    ]],
    width="stretch",
    hide_index=True,
    column_config={
        "Signal Date": st.column_config.DateColumn("訊號日", format="YYYY-MM-DD"),
        "Execution Date": st.column_config.DateColumn("成交日", format="YYYY-MM-DD"),
        "Regime": "市場",
        "Selected Holdings": "換股後持股",
        "Bought": "買進／加碼",
        "Sold": "賣出／減碼",
        "Cycle P&L": st.column_config.NumberColumn("週期損益", format="$%.2f"),
        "Cycle Return %": st.column_config.NumberColumn("週期報酬", format="%.2f%%"),
        "Realized P&L at Rebalance": st.column_config.NumberColumn("換股實現損益", format="$%.2f"),
        "Trading Cost": st.column_config.NumberColumn("佣金", format="$%.2f"),
        "Turnover %": st.column_config.NumberColumn("換手率", format="%.1f%%"),
    },
)

if not cycles.empty:
    st.subheader("單次換股放大查看")
    options = {
        f"{row['Execution Date'].date()} · {row['Selected Holdings']} · {row['Cycle Return %']:+.2f}%": index
        for index, row in cycles.iterrows()
    }
    label = st.selectbox("選擇換股日期", list(options), index=len(options) - 1)
    chosen_index = options[label]
    chosen = cycles.loc[chosen_index]
    log = result["rebalance_log"][chosen_index]
    a, b, c, d = st.columns(4)
    a.metric("換股後持股", chosen["Selected Holdings"])
    b.metric("本週期損益", f"${chosen['Cycle P&L']:+,.2f}", f"{chosen['Cycle Return %']:+.2f}%")
    c.metric("本次實現損益", f"${chosen['Realized P&L at Rebalance']:+,.2f}")
    d.metric("本次成本", f"${chosen['Trading Cost']:,.2f}")
    ranking = pd.DataFrame(log["rankings"])
    if not ranking.empty:
        ranking = ranking.rename(columns={"rank": "排名", "symbol": "股票", "return_20d_pct": "20D 報酬 %", "above_ma200": "高於 MA200", "selected": "入選"})
        st.dataframe(ranking.round(2), width="stretch", hide_index=True)

st.subheader("每檔股票貢獻多少損益")
if contribution.empty:
    st.info("目前沒有可歸屬的持倉損益。")
else:
    colors = ["#12B76A" if value >= 0 else "#F04438" for value in contribution["Total Contribution"]]
    contrib_fig = go.Figure(go.Bar(
        x=contribution["Total Contribution"],
        y=contribution["Symbol"],
        orientation="h",
        marker_color=colors,
        text=[f"${value:+,.0f}" for value in contribution["Total Contribution"]],
        textposition="outside",
    ))
    contrib_fig.update_layout(height=380, margin={"l": 10, "r": 40, "t": 10, "b": 10}, xaxis_title="已實現 + 未實現損益（美元）", yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(contrib_fig, width="stretch", config={"displaylogo": False})
    st.dataframe(
        contribution.round(2), width="stretch", hide_index=True,
        column_config={
            "Net P&L": st.column_config.NumberColumn("已實現損益", format="$%.2f"),
            "Unrealized P&L": st.column_config.NumberColumn("未實現損益", format="$%.2f"),
            "Total Contribution": st.column_config.NumberColumn("總貢獻", format="$%.2f"),
        },
    )

st.subheader("已平倉明細")
if closed.empty:
    st.info("沒有已平倉部位。")
else:
    wins = int((closed["Net P&L"] > 0).sum())
    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.metric("平倉批次", len(closed))
    cc2.metric("獲利比例", f"{100 * wins / len(closed):.1f}%")
    cc3.metric("已實現損益", f"${closed['Net P&L'].sum():+,.2f}")
    cc4.metric("平均持有", f"{closed['Holding Days'].mean():.0f} 天")
    closed_display = closed.sort_values("Exit Date", ascending=False).copy()
    numeric_columns = closed_display.select_dtypes(include="number").columns
    closed_display[numeric_columns] = closed_display[numeric_columns].round(2)
    st.dataframe(
        closed_display, width="stretch", hide_index=True,
        column_config={
            "Entry Date": st.column_config.DateColumn("買進日", format="YYYY-MM-DD"),
            "Exit Date": st.column_config.DateColumn("賣出日", format="YYYY-MM-DD"),
            "Net P&L": st.column_config.NumberColumn("淨損益", format="$%.2f"),
            "Return %": st.column_config.NumberColumn("報酬", format="%.2f%%"),
        },
    )

st.subheader("期末未平倉部位")
if opened.empty:
    st.info("回測期末為全現金。")
else:
    st.dataframe(
        opened.round(2), width="stretch", hide_index=True,
        column_config={
            "Cost Basis": st.column_config.NumberColumn("成本", format="$%.2f"),
            "Last Close": st.column_config.NumberColumn("期末價格", format="$%.2f"),
            "Market Value": st.column_config.NumberColumn("市值", format="$%.2f"),
            "Unrealized P&L": st.column_config.NumberColumn("未實現損益", format="$%.2f"),
            "Unrealized Return %": st.column_config.NumberColumn("未實現報酬", format="%.2f%%"),
        },
    )

with st.expander("查看全部原始成交紀錄"):
    raw_trades = pd.DataFrame(result["trades"])
    if not raw_trades.empty:
        st.dataframe(raw_trades.round(4), width="stretch", hide_index=True)

st.caption("研究用途，不構成投資建議。固定現代大型股股票池仍具有 survivorship bias；歷史績效不代表未來表現。")
