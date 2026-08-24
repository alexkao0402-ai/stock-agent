# strategy_v1.py
# Strategy V1：趨勢 + 動能 + 相對強弱
# 重要原則：所有計算只使用歷史資料，絕不使用未來資訊（避免 look-ahead bias）

import pandas as pd


def add_trend_filter(df, window=200):
    """
    新增「趨勢過濾」欄位：判斷收盤價是否高於200日均線。

    df: 股價 DataFrame（必須包含 close 欄位，按日期由舊到新排序）
    window: 均線天數，預設200天

    回傳：新增了 ma200, is_bullish_regime 兩欄的 DataFrame
    """
    df = df.copy()
    df["ma200"] = df["close"].rolling(window=window).mean()
    df["is_bullish_regime"] = df["close"] > df["ma200"]
    return df


def add_momentum(df, months=6, trading_days_per_month=21):
    """
    新增「動能」欄位：計算過去N個月的報酬率。

    df: 股價 DataFrame（必須包含 close 欄位）
    months: 要看幾個月的動能，預設6個月
    trading_days_per_month: 一個月大約有幾個交易日，預設21天（業界常用估計值）

    回傳：新增了 momentum_pct 欄位的 DataFrame
    """
    df = df.copy()
    window_days = months * trading_days_per_month

    # pct_change(periods=N) 計算「現在的值，相對於N天前的值，變化了百分之多少」
    # 這個計算方式，天生只會用到「過去」的資料，不會用到未來
    df["momentum_pct"] = df["close"].pct_change(periods=window_days) * 100
    return df


def add_relative_strength(stock_df, benchmark_df, months=6, trading_days_per_month=21):
    """
    新增「相對強弱」欄位：比較股票的N個月報酬率，是否贏過基準（例如BTC）的N個月報酬率。

    stock_df: 已經跑過 add_momentum() 的股票 DataFrame（必須包含 date, momentum_pct 欄位）
    benchmark_df: 基準的股價 DataFrame（例如 BTC，必須包含 date, close 欄位）
    months, trading_days_per_month: 跟 add_momentum() 使用同樣的參數，確保計算基礎一致

    回傳：新增了 benchmark_momentum_pct, outperforms_benchmark 兩欄的 DataFrame
    """
    df = stock_df.copy()
    window_days = months * trading_days_per_month

    # 先計算基準（例如BTC）自己的動能
    benchmark_df = benchmark_df.copy()
    benchmark_df["benchmark_momentum_pct"] = benchmark_df["close"].pct_change(periods=window_days) * 100

    # 用「日期」把股票資料跟基準資料對齊合併
    # 這一步很重要：股票的交易日跟加密貨幣的交易日不完全一樣（加密貨幣是全年無休，股票有休市日）
    # 用 merge 可以確保我們是拿「同一天」的兩邊資料做比較，而不是隨便對齊
    merged = pd.merge(
        df[["date", "momentum_pct"]],
        benchmark_df[["date", "benchmark_momentum_pct"]],
        on="date",
        how="left"  # 以股票的交易日為主，如果那天剛好沒有對應的BTC資料，就先留空
    )

    df = df.merge(merged[["date", "benchmark_momentum_pct"]], on="date", how="left")
    df["outperforms_benchmark"] = df["momentum_pct"] > df["benchmark_momentum_pct"]

    return df

def add_entry_exit_signals(df):
    """
    根據三因子條件，產生進場/出場訊號，並標記「實際執行交易的價格」。
    重要：訊號在第t天算出，但實際成交價使用第t+1天（隔天）的開盤價，避免look-ahead bias。

    df: 已經跑過 add_trend_filter(), add_momentum(), add_relative_strength() 的 DataFrame

    回傳：新增了 signal, execution_price 欄位的 DataFrame
    signal 欄位的值："buy" / "sell" / None
    execution_price：這個訊號實際會用哪一天、哪個價格成交（如果是最後一天發出訊號、沒有隔天資料可用，則為 None）
    """
    df = df.copy()

    # 進場條件：三個條件同時成立
    entry_condition = (
        df["is_bullish_regime"] == True
    ) & (
        df["momentum_pct"] > 0
    ) & (
        df["outperforms_benchmark"] == True
    )

    # 出場條件：只要「不在多頭趨勢」或「不再贏過基準」，任一成立就出場
    exit_condition = (
        df["is_bullish_regime"] == False
    ) | (
        df["outperforms_benchmark"] == False
    )

    # 用「今天符合條件、昨天不符合」來判斷「訊號第一次成立」，避免同一個持續成立的狀態每天都重複發訊號
    entry_condition_yesterday = entry_condition.shift(1)
    exit_condition_yesterday = exit_condition.shift(1)

    new_buy_signal = (entry_condition == True) & (entry_condition_yesterday == False)
    new_sell_signal = (exit_condition == True) & (exit_condition_yesterday == False)

    df["signal"] = None
    df.loc[new_buy_signal, "signal"] = "buy"
    df.loc[new_sell_signal, "signal"] = "sell"

    # 核心邏輯：把「隔天的開盤價」，對應回「今天這一列」
    # .shift(-1) 代表「把整欄資料往上移一格」，這樣「今天這一列」對應到的，就是「明天的值」
    # 這樣一來，df.loc[某一天, "execution_price"] 存的就是「這個訊號真正會拿去成交的價格」
    df["execution_price"] = df["open"].shift(-1)

    return df

def run_backtest_v1(df, initial_capital=10000, transaction_cost_pct=0.001, slippage_pct=0.0005):
    """
    模擬照著 Strategy V1 的訊號進行買賣，並且扣除交易成本與滑價，計算真實績效。

    df: 已經跑過 add_entry_exit_signals() 的 DataFrame
    initial_capital: 起始模擬本金，預設 10000
    transaction_cost_pct: 每筆交易的手續費比例，預設 0.1%（0.001）
    slippage_pct: 每筆交易的滑價比例，預設 0.05%（0.0005）
                  滑價代表「實際成交價，通常會比你想要的價格差一點點」，這是真實交易中常見的現象

    回傳：一個字典，包含完整交易紀錄與績效指標
    """

    cash = initial_capital
    shares = 0
    trades = []

    for _, row in df.iterrows():
        # 如果這一天沒有 execution_price（例如是資料的最後一天，沒有隔天可以成交），就跳過
        if pd.isna(row["execution_price"]):
            continue

        if row["signal"] == "buy" and cash > 0:
            raw_price = row["execution_price"]
            # 買進時，滑價讓你「買貴一點」（用比預期價格更高的價格成交，模擬真實市場的不利影響）
            actual_price = raw_price * (1 + slippage_pct)

            # 先扣除手續費，剩下的錢才拿去買股票
            cash_after_fee = cash * (1 - transaction_cost_pct)
            shares = cash_after_fee / actual_price
            cash = 0

            trades.append({
                "date": row["date"],
                "action": "buy",
                "signal_date": row["date"],
                "execution_price": actual_price,
                "shares": shares,
                "reason": "三因子條件成立：趨勢多頭 + 正動能 + 優於BTC"
            })

        elif row["signal"] == "sell" and shares > 0:
            raw_price = row["execution_price"]
            # 賣出時，滑價讓你「賣便宜一點」（同樣模擬不利影響）
            actual_price = raw_price * (1 - slippage_pct)

            gross_cash = shares * actual_price
            # 賣出所得，也要扣一次手續費
            cash = gross_cash * (1 - transaction_cost_pct)

            trades.append({
                "date": row["date"],
                "action": "sell",
                "signal_date": row["date"],
                "execution_price": actual_price,
                "shares": shares,
                "reason": "趨勢轉空頭 或 不再優於BTC"
            })
            shares = 0

    final_price = df["close"].iloc[-1]
    final_value = cash + (shares * final_price)
    total_return_pct = round((final_value - initial_capital) / initial_capital * 100, 2)

    result = {
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": total_return_pct,
        "number_of_trades": len(trades),
        "transaction_cost_pct": transaction_cost_pct,
        "slippage_pct": slippage_pct,
        "trades": trades,
        "still_holding_shares": shares > 0
    }

    return result

def run_backtest_v1_with_takeprofit(df, initial_capital=10000, transaction_cost_pct=0.001,
                                      slippage_pct=0.0005, take_profit_pct=25.0):
    """
    在原本Strategy V1的基礎上，加入停利機制：
    持有期間只要帳面獲利達到 take_profit_pct，就主動出場，不等待趨勢反轉訊號。
    這是為了解決診斷分析發現的「缺乏停利機制導致獲利回吐」問題。

    df: 已經跑過 add_entry_exit_signals() 的 DataFrame
    take_profit_pct: 停利門檻（百分比），預設25%，這是一個合理的固定猜測值，不是優化過的最佳參數

    回傳：跟 run_backtest_v1() 相同格式的結果字典
    """

    cash = initial_capital
    shares = 0
    entry_price = None  # 記錄目前持有部位的進場價，用來判斷是否達到停利門檻
    trades = []

    for _, row in df.iterrows():
        current_price = row["close"]

        # ---------- 停利檢查：只要目前有持股，且今天的收盤價已經比進場價高出門檻，就主動賣出 ----------
        # 這個檢查獨立於原本的訊號邏輯，用「今天收盤價」判斷，並用「今天收盤價」執行
        # （這裡不是隔天執行，因為主動停利是「看到達標當下立刻行動」，這是策略設計上的合理假設，
        #  而不是像原本趨勢訊號那樣需要等隔天開盤，兩者屬於不同性質的決策）
        if shares > 0 and entry_price is not None:
            current_gain_pct = (current_price - entry_price) / entry_price * 100
            if current_gain_pct >= take_profit_pct:
                actual_price = current_price * (1 - slippage_pct)
                gross_cash = shares * actual_price
                cash = gross_cash * (1 - transaction_cost_pct)
                trades.append({
                    "date": row["date"],
                    "action": "sell",
                    "execution_price": actual_price,
                    "shares": shares,
                    "reason": f"觸發停利機制（獲利達{round(current_gain_pct, 2)}%，門檻{take_profit_pct}%）"
                })
                shares = 0
                entry_price = None
                continue  # 這一天已經處理過停利賣出，不用再檢查原本的訊號

        if pd.isna(row["execution_price"]):
            continue

        if row["signal"] == "buy" and cash > 0:
            raw_price = row["execution_price"]
            actual_price = raw_price * (1 + slippage_pct)
            cash_after_fee = cash * (1 - transaction_cost_pct)
            shares = cash_after_fee / actual_price
            cash = 0
            entry_price = actual_price  # 記錄這次進場價，供之後停利判斷使用

            trades.append({
                "date": row["date"],
                "action": "buy",
                "execution_price": actual_price,
                "shares": shares,
                "reason": "三因子條件成立"
            })

        elif row["signal"] == "sell" and shares > 0:
            raw_price = row["execution_price"]
            actual_price = raw_price * (1 - slippage_pct)
            gross_cash = shares * actual_price
            cash = gross_cash * (1 - transaction_cost_pct)

            trades.append({
                "date": row["date"],
                "action": "sell",
                "execution_price": actual_price,
                "shares": shares,
                "reason": "趨勢轉空頭 或 不再優於BTC"
            })
            shares = 0
            entry_price = None

    final_price = df["close"].iloc[-1]
    final_value = cash + (shares * final_price)
    total_return_pct = round((final_value - initial_capital) / initial_capital * 100, 2)

    return {
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": total_return_pct,
        "number_of_trades": len(trades),
        "take_profit_pct": take_profit_pct,
        "trades": trades,
        "still_holding_shares": shares > 0
    }

def run_backtest_v1_with_takeprofit_v2(
    df,
    initial_capital=10000,
    transaction_cost_pct=0.001,
    slippage_pct=0.0005,
    take_profit_pct=25.0
):
    """
    Strategy V1 + fixed take-profit.

    Important execution assumption:
    - The take-profit trigger uses the day's HIGH.
    - If HIGH reaches the take-profit price, the trade is assumed
      to execute at the take-profit price.
    - This avoids assuming that we can observe the closing price
      and then execute at that same closing price.

    This is a research assumption for daily OHLC backtesting.
    """

    cash = initial_capital
    shares = 0
    entry_price = None
    trades = []

    for _, row in df.iterrows():

        current_close = row["close"]
        current_high = row["high"]

        # --------------------------------------------------
        # 1. TAKE PROFIT
        # --------------------------------------------------

        if shares > 0 and entry_price is not None:

            take_profit_price = entry_price * (
                1 + take_profit_pct / 100
            )

            # Use HIGH to determine whether the price
            # reached the take-profit level.
            if current_high >= take_profit_price:

                actual_price = take_profit_price * (
                    1 - slippage_pct
                )

                gross_cash = shares * actual_price

                cash = gross_cash * (
                    1 - transaction_cost_pct
                )

                current_gain_pct = (
                    (take_profit_price - entry_price)
                    / entry_price
                    * 100
                )

                trades.append({
                    "date": row["date"],
                    "action": "sell",
                    "execution_price": actual_price,
                    "shares": shares,
                    "reason": (
                        f"Take profit triggered "
                        f"({current_gain_pct:.2f}%)"
                    )
                })

                shares = 0
                entry_price = None

                continue

        # --------------------------------------------------
        # 2. NORMAL STRATEGY SIGNAL
        # --------------------------------------------------

        if pd.isna(row["execution_price"]):
            continue

        if row["signal"] == "buy" and cash > 0:

            raw_price = row["execution_price"]

            actual_price = raw_price * (
                1 + slippage_pct
            )

            cash_after_fee = cash * (
                1 - transaction_cost_pct
            )

            shares = cash_after_fee / actual_price

            cash = 0

            entry_price = actual_price

            trades.append({
                "date": row["date"],
                "action": "buy",
                "execution_price": actual_price,
                "shares": shares,
                "reason": "Three-factor signal"
            })

        elif row["signal"] == "sell" and shares > 0:

            raw_price = row["execution_price"]

            actual_price = raw_price * (
                1 - slippage_pct
            )

            gross_cash = shares * actual_price

            cash = gross_cash * (
                1 - transaction_cost_pct
            )

            trades.append({
                "date": row["date"],
                "action": "sell",
                "execution_price": actual_price,
                "shares": shares,
                "reason": (
                    "Trend reversal or relative strength failure"
                )
            })

            shares = 0
            entry_price = None

    # --------------------------------------------------
    # 3. FINAL PORTFOLIO VALUE
    # --------------------------------------------------

    final_price = df["close"].iloc[-1]

    final_value = cash + (
        shares * final_price
    )

    total_return_pct = (
        (final_value - initial_capital)
        / initial_capital
        * 100
    )

    return {
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return_pct, 2),
        "number_of_trades": len(trades),
        "take_profit_pct": take_profit_pct,
        "trades": trades,
        "still_holding_shares": shares > 0
    }

def run_backtest_v1_with_trailing_exit(
    df,
    initial_capital=10000,
    transaction_cost_pct=0.001,
    slippage_pct=0.0005,
    trailing_pct=20.0
):
    """
    Strategy V1 + trailing exit.

    The trailing level is calculated from the highest HIGH
    observed since entering the position.

    If the day's LOW reaches the trailing level,
    the position exits at the trailing level.

    This is a fixed research baseline, not an optimized parameter.
    """

    cash = initial_capital
    shares = 0
    entry_price = None
    highest_price = None
    trades = []

    for _, row in df.iterrows():

        current_high = row["high"]
        current_low = row["low"]

        # ==========================================
        # 1. TRAILING EXIT
        # ==========================================

        if shares > 0 and highest_price is not None:

            # Update highest price reached
            highest_price = max(
                highest_price,
                current_high
            )

            trailing_price = highest_price * (
                1 - trailing_pct / 100
            )

            # If today's low reaches trailing level
            if current_low <= trailing_price:

                actual_price = trailing_price * (
                    1 - slippage_pct
                )

                gross_cash = shares * actual_price

                cash = gross_cash * (
                    1 - transaction_cost_pct
                )

                trades.append({
                    "date": row["date"],
                    "action": "sell",
                    "execution_price": actual_price,
                    "shares": shares,
                    "reason": (
                        f"Trailing exit "
                        f"({trailing_pct}% from high)"
                    )
                })

                shares = 0
                entry_price = None
                highest_price = None

                continue

        # ==========================================
        # 2. NORMAL SIGNAL
        # ==========================================

        if pd.isna(row["execution_price"]):
            continue

        if row["signal"] == "buy" and cash > 0:

            raw_price = row["execution_price"]

            actual_price = raw_price * (
                1 + slippage_pct
            )

            cash_after_fee = cash * (
                1 - transaction_cost_pct
            )

            shares = cash_after_fee / actual_price

            cash = 0

            entry_price = actual_price
            highest_price = current_high

            trades.append({
                "date": row["date"],
                "action": "buy",
                "execution_price": actual_price,
                "shares": shares,
                "reason": "Three-factor signal"
            })

        elif row["signal"] == "sell" and shares > 0:

            raw_price = row["execution_price"]

            actual_price = raw_price * (
                1 - slippage_pct
            )

            gross_cash = shares * actual_price

            cash = gross_cash * (
                1 - transaction_cost_pct
            )

            trades.append({
                "date": row["date"],
                "action": "sell",
                "execution_price": actual_price,
                "shares": shares,
                "reason": (
                    "Trend reversal or relative strength failure"
                )
            })

            shares = 0
            entry_price = None
            highest_price = None

    # ==========================================
    # 3. FINAL VALUE
    # ==========================================

    final_price = df["close"].iloc[-1]

    final_value = cash + (
        shares * final_price
    )

    total_return_pct = (
        (final_value - initial_capital)
        / initial_capital
        * 100
    )

    return {
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return_pct, 2),
        "number_of_trades": len(trades),
        "trailing_pct": trailing_pct,
        "trades": trades,
        "still_holding_shares": shares > 0
    }

def run_backtest_v1_with_equity_curve(
    df,
    initial_capital=10000,
    transaction_cost_pct=0.001,
    slippage_pct=0.0005
):
    """
    Strategy V1 + Daily Equity Curve

    正確的時間軸：

    Day T:
        使用 Day T 的資料產生 signal

    Day T+1:
        使用 Day T+1 的 OPEN 執行交易

    Day T+1 收盤:
        用 Day T+1 CLOSE 計算當日 portfolio value

    這樣可以避免把未來的開盤價提前拿來交易。
    """

    cash = initial_capital
    shares = 0

    trades = []
    equity_curve = []

    # ==================================================
    # 按日期由舊到新逐日處理
    # ==================================================

    for i in range(len(df)):

        row = df.iloc[i]

        current_date = row["date"]
        current_open = row["open"]
        current_close = row["close"]

        # ==================================================
        # 1. 執行「昨天產生的 signal」
        # ==================================================

        if i > 0:

            previous_row = df.iloc[i - 1]

            previous_signal = previous_row["signal"]

            # ------------------------------------------
            # BUY
            # ------------------------------------------

            if previous_signal == "buy" and cash > 0:

                raw_price = current_open

                actual_price = raw_price * (
                    1 + slippage_pct
                )

                cash_after_fee = cash * (
                    1 - transaction_cost_pct
                )

                shares = cash_after_fee / actual_price

                cash = 0

                trades.append({
                    "date": current_date,
                    "action": "buy",
                    "signal_date": previous_row["date"],
                    "execution_price": actual_price,
                    "shares": shares,
                    "reason": (
                        "三因子條件成立："
                        "趨勢多頭 + 正動能 + 優於BTC"
                    )
                })

            # ------------------------------------------
            # SELL
            # ------------------------------------------

            elif previous_signal == "sell" and shares > 0:

                raw_price = current_open

                actual_price = raw_price * (
                    1 - slippage_pct
                )

                gross_cash = shares * actual_price

                cash = gross_cash * (
                    1 - transaction_cost_pct
                )

                trades.append({
                    "date": current_date,
                    "action": "sell",
                    "signal_date": previous_row["date"],
                    "execution_price": actual_price,
                    "shares": shares,
                    "reason": (
                        "趨勢轉空頭 或 不再優於BTC"
                    )
                })

                shares = 0

        # ==================================================
        # 2. 每日 Mark-to-Market
        # ==================================================

        position_value = shares * current_close

        portfolio_value = cash + position_value

        equity_curve.append({
            "date": current_date,
            "close": current_close,
            "cash": cash,
            "shares": shares,
            "position_value": position_value,
            "portfolio_value": portfolio_value,
            "position": 1 if shares > 0 else 0
        })

    # ==================================================
    # 3. Equity Curve DataFrame
    # ==================================================

    equity_df = pd.DataFrame(equity_curve)

    # ==================================================
    # 4. 最終績效
    # ==================================================

    final_value = equity_df["portfolio_value"].iloc[-1]

    total_return_pct = (
        (final_value - initial_capital)
        / initial_capital
        * 100
    )

    return {
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return_pct, 2),
        "number_of_trades": len(trades),
        "transaction_cost_pct": transaction_cost_pct,
        "slippage_pct": slippage_pct,
        "trades": trades,
        "still_holding_shares": shares > 0,
        "equity_curve": equity_df
    }

def calculate_max_drawdown(equity_df):
    """
    根據每日 Portfolio Value 計算 Maximum Drawdown。

    Maximum Drawdown = 從歷史高點到之後最低點的最大跌幅。

    回傳：
    {
        "max_drawdown_pct": ...,
        "peak_date": ...,
        "trough_date": ...
    }
    """

    equity = equity_df["portfolio_value"]

    running_max = equity.cummax()

    drawdown = (
        equity - running_max
    ) / running_max * 100

    min_index = drawdown.idxmin()

    max_drawdown_pct = drawdown.loc[min_index]

    peak_index = equity.loc[:min_index].idxmax()

    return {
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "peak_date": equity_df.loc[peak_index, "date"],
        "trough_date": equity_df.loc[min_index, "date"]
    }

def calculate_risk_metrics(equity_df):
    """
    根據每日 Equity Curve 計算風險調整後績效。

    使用：
    - Daily Return
    - Annualized Volatility
    - Sharpe Ratio
    - Sortino Ratio
    - Maximum Drawdown

    假設一年約 252 個交易日。
    無風險利率目前先假設為 0%，
    方便建立第一版研究基準。
    """

    equity = equity_df["portfolio_value"].copy()

    # ==========================================
    # 每日報酬率
    # ==========================================

    daily_returns = equity.pct_change().dropna()

    if len(daily_returns) == 0:
        return {
            "annualized_volatility_pct": None,
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "max_drawdown_pct": None
        }

    # ==========================================
    # 年化波動率
    # ==========================================

    daily_volatility = daily_returns.std()

    annualized_volatility = (
        daily_volatility * (252 ** 0.5)
    )

    # ==========================================
    # Sharpe Ratio
    #
    # Risk-free rate = 0%
    # ==========================================

    daily_mean_return = daily_returns.mean()

    if daily_volatility > 0:

        sharpe_ratio = (
            daily_mean_return
            / daily_volatility
        ) * (252 ** 0.5)

    else:
        sharpe_ratio = None

    # ==========================================
    # Sortino Ratio
    #
    # 只懲罰負報酬
    # ==========================================

    downside_returns = daily_returns[
        daily_returns < 0
    ]

    if len(downside_returns) > 0:

        downside_deviation = (
            downside_returns.std()
        )

        if downside_deviation > 0:

            sortino_ratio = (
                daily_mean_return
                / downside_deviation
            ) * (252 ** 0.5)

        else:
            sortino_ratio = None

    else:
        sortino_ratio = None

    # ==========================================
    # Maximum Drawdown
    # ==========================================

    running_max = equity.cummax()

    drawdown = (
        equity - running_max
    ) / running_max

    max_drawdown = drawdown.min()

    return {
        "annualized_volatility_pct": round(
            annualized_volatility * 100,
            2
        ),

        "sharpe_ratio": round(
            sharpe_ratio,
            3
        ) if sharpe_ratio is not None else None,

        "sortino_ratio": round(
            sortino_ratio,
            3
        ) if sortino_ratio is not None else None,

        "max_drawdown_pct": round(
            max_drawdown * 100,
            2
        )
    }

def calculate_buy_and_hold(df, initial_capital=10000):
    """
    計算「從資料第一天就買進，一路持有到最後一天」的績效，作為比較基準。

    df: 股價 DataFrame（必須包含 close 欄位，按日期排序）
    initial_capital: 起始模擬本金，預設 10000

    回傳：一個字典，包含最終價值與總報酬率
    """
    first_price = df["close"].iloc[0]
    last_price = df["close"].iloc[-1]

    shares = initial_capital / first_price
    final_value = shares * last_price
    total_return_pct = round((final_value - initial_capital) / initial_capital * 100, 2)

    return {
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": total_return_pct,
        "start_date": df["date"].iloc[0],
        "end_date": df["date"].iloc[-1],
        "start_price": first_price,
        "end_price": last_price
    }

def calculate_performance_metrics(trades, initial_capital, final_value, df):
    """
    根據交易紀錄，計算完整的績效指標。

    trades: run_backtest_v1() 產生的交易紀錄清單
    initial_capital: 起始本金
    final_value: 最終價值
    df: 原始股價 DataFrame，用來取得回測的起訖日期（計算年化報酬需要知道經過了幾年）

    回傳：一個包含各項績效指標的字典
    """

    # ---------- CAGR（年化複合報酬率）----------
    start_date = pd.to_datetime(df["date"].iloc[0])
    end_date = pd.to_datetime(df["date"].iloc[-1])
    years = (end_date - start_date).days / 365.25

    if years > 0 and initial_capital > 0:
        cagr_pct = round((((final_value / initial_capital) ** (1 / years)) - 1) * 100, 2)
    else:
        cagr_pct = None

    # ---------- 把交易紀錄整理成「一買一賣配對」的完整交易，才能算勝率等指標 ----------
    completed_trades = []
    buy_trade = None

    for trade in trades:
        if trade["action"] == "buy":
            buy_trade = trade
        elif trade["action"] == "sell" and buy_trade is not None:
            trade_return_pct = (trade["execution_price"] - buy_trade["execution_price"]) / buy_trade["execution_price"] * 100
            completed_trades.append({
                "entry_date": buy_trade["date"],
                "entry_price": buy_trade["execution_price"],
                "exit_date": trade["date"],
                "exit_price": trade["execution_price"],
                "return_pct": round(trade_return_pct, 2)
            })
            buy_trade = None

    # ---------- 勝率、平均獲利、平均虧損、獲利因子 ----------
    if completed_trades:
        winning_trades = [t for t in completed_trades if t["return_pct"] > 0]
        losing_trades = [t for t in completed_trades if t["return_pct"] <= 0]

        win_rate_pct = round(len(winning_trades) / len(completed_trades) * 100, 2)

        avg_win_pct = round(sum(t["return_pct"] for t in winning_trades) / len(winning_trades), 2) if winning_trades else 0
        avg_loss_pct = round(sum(t["return_pct"] for t in losing_trades) / len(losing_trades), 2) if losing_trades else 0

        total_gains = sum(t["return_pct"] for t in winning_trades)
        total_losses = abs(sum(t["return_pct"] for t in losing_trades))
        # 獲利因子 = 總獲利 / 總虧損，大於1代表整體是賺錢的，數字越大代表賺賠比越好
        profit_factor = round(total_gains / total_losses, 2) if total_losses > 0 else None
    else:
        win_rate_pct = None
        avg_win_pct = None
        avg_loss_pct = None
        profit_factor = None

    return {
        "cagr_pct": cagr_pct,
        "years_covered": round(years, 2),
        "win_rate_pct": win_rate_pct,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "profit_factor": profit_factor,
        "number_of_completed_trades": len(completed_trades),
        "completed_trades": completed_trades
    }

def build_trade_diagnostics(df, completed_trades):
    """
    針對每一筆完整交易（進場到出場），計算詳細的診斷資訊：
    持有天數、同期間市場報酬、最大有利偏移(MFE)、最大不利偏移(MAE)。

    df: 原始股價 DataFrame（必須包含 date, close 欄位）
    completed_trades: calculate_performance_metrics() 產生的 completed_trades 清單

    回傳：一個更詳細的交易診斷清單
    """

    diagnostics = []

    for trade in completed_trades:
        entry_date = trade["entry_date"]
        exit_date = trade["exit_date"]
        entry_price = trade["entry_price"]

        # 取出這筆交易「持有期間」對應的股價區間（用日期字串比較，因為日期格式是YYYY-MM-DD，字串排序恰好等於時間排序）
        window = df[(df["date"] >= entry_date) & (df["date"] <= exit_date)]

        if window.empty:
            continue

        # 持有天數：用實際日曆天數計算（而非交易日數），方便跟其他時間單位比較
        holding_days = (pd.to_datetime(exit_date) - pd.to_datetime(entry_date)).days

        # 同期間市場報酬：如果单纯持有股票、不透過任何策略訊號，這段期間的原始漲跌幅
        window_start_close = window["close"].iloc[0]
        window_end_close = window["close"].iloc[-1]
        market_return_pct = round((window_end_close - window_start_close) / window_start_close * 100, 2)

        # MFE：這段期間股價曾經漲到的最高點，相對進場價的漲幅
        max_close = window["close"].max()
        mfe_pct = round((max_close - entry_price) / entry_price * 100, 2)

        # MAE：這段期間股價曾經跌到的最低點，相對進場價的跌幅
        min_close = window["close"].min()
        mae_pct = round((min_close - entry_price) / entry_price * 100, 2)

        diagnostics.append({
            "entry_date": entry_date,
            "entry_price": round(entry_price, 2),
            "exit_date": exit_date,
            "exit_price": round(trade["exit_price"], 2),
            "return_pct": trade["return_pct"],
            "holding_days": holding_days,
            "market_return_pct": market_return_pct,
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct
        })

    return diagnostics

if __name__ == "__main__":
    from src.stock_data import get_long_history_stock_data, get_crypto_daily_data, clean_crypto_data

    # 改用 yfinance 抓取BTDR的長期歷史股價（2年，足夠算 MA200）
    stock_df = get_long_history_stock_data("BTDR", period="2y")

    # BTC 資料維持用 Alpha Vantage（這個資料源本身就給完整歷史，不受影響）
    raw_crypto = get_crypto_daily_data("BTC", "USD")
    crypto_df = clean_crypto_data(raw_crypto)

    print(f"BTDR資料筆數：{len(stock_df)}，時間範圍：{stock_df['date'].iloc[0]} ~ {stock_df['date'].iloc[-1]}")
    print(f"BTC資料筆數：{len(crypto_df)}")

    stock_df = add_trend_filter(stock_df)
    stock_df = add_momentum(stock_df)
    stock_df = add_relative_strength(stock_df, crypto_df)

    print("\n最後15天的三因子數據：")
    print(stock_df[["date", "close", "ma200", "is_bullish_regime", "momentum_pct", "benchmark_momentum_pct", "outperforms_benchmark"]].tail(15))

    stock_df = add_entry_exit_signals(stock_df)

    print("\n所有觸發過的訊號：")
    signal_rows = stock_df[stock_df["signal"].notna()]
    print(signal_rows[["date", "close", "signal", "execution_price"]])

    print("\n===== Strategy V1 回測結果（含交易成本與滑價）=====")
    backtest_result = run_backtest_v1(stock_df)
    print(f"本金：${backtest_result['initial_capital']}")
    print(f"最終價值：${backtest_result['final_value']}")
    print(f"總報酬率：{backtest_result['total_return_pct']}%")
    print(f"交易次數：{backtest_result['number_of_trades']}")
    print(f"手續費率：{backtest_result['transaction_cost_pct']*100}%，滑價率：{backtest_result['slippage_pct']*100}%")

    print("\n===== Buy & Hold 基準比較 =====")
    bh_result = calculate_buy_and_hold(stock_df)
    print(f"從 {bh_result['start_date']}（${bh_result['start_price']}）持有到 {bh_result['end_date']}（${bh_result['end_price']}）")
    print(f"Buy & Hold 最終價值：${bh_result['final_value']}")
    print(f"Buy & Hold 總報酬率：{bh_result['total_return_pct']}%")

    print(f"\nStrategy V1 總報酬率：{backtest_result['total_return_pct']}%")
    print(f"Buy & Hold 總報酬率：{bh_result['total_return_pct']}%")
    if backtest_result['total_return_pct'] > bh_result['total_return_pct']:
        print("結論：Strategy V1 表現優於 Buy & Hold")
    else:
        print("結論：Strategy V1 表現劣於 Buy & Hold")

    print("\n===== 完整績效指標 =====")
    metrics = calculate_performance_metrics(
        backtest_result["trades"],
        backtest_result["initial_capital"],
        backtest_result["final_value"],
        stock_df
    )
    print(f"回測涵蓋年數：{metrics['years_covered']} 年")
    print(f"CAGR（年化報酬率）：{metrics['cagr_pct']}%")
    print(f"完整交易次數：{metrics['number_of_completed_trades']}")
    print(f"勝率：{metrics['win_rate_pct']}%")
    print(f"平均獲利：{metrics['avg_win_pct']}%")
    print(f"平均虧損：{metrics['avg_loss_pct']}%")
    print(f"獲利因子：{metrics['profit_factor']}")