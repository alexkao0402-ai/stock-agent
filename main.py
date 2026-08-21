# main.py
# 這是整個專案的「入口」，執行這個檔案就能跑完整流程：
# 使用者輸入股票代號 → 抓取歷史股價 → 清理資料 → 抓取新聞 → AI 分析 → 印出報告

import time
from src.stock_data import get_daily_stock_data, clean_stock_data, get_news_sentiment
from src.ai_analysis import generate_report


def main():
    symbol = input("請輸入股票代號（例如 BTDR）：").strip().upper()

    print(f"\n正在抓取 {symbol} 的歷史股價資料...")
    raw_data = get_daily_stock_data(symbol)

    if "Time Series (Daily)" not in raw_data:
        print("抓取股價資料失敗，請確認股票代號是否正確，或稍後再試。")
        print("API 回傳內容：", raw_data)
        return

    df = clean_stock_data(raw_data)
    print(f"成功取得 {len(df)} 筆股價資料，時間範圍：{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")

    import time
    time.sleep(15)  # 等待 15 秒，避免超過 Alpha Vantage 免費版每分鐘的請求限制

    print(f"\n正在抓取 {symbol} 的相關新聞...")
    news_list = get_news_sentiment(symbol, limit=20)
    print(f"成功取得 {len(news_list)} 則新聞")

    print("\n正在請 AI 分析資料，請稍候...")
    report = generate_report(symbol, df, news_list)

    print("\n========== 研究報告 ==========")
    print(report)
    print("================================")


if __name__ == "__main__":
    main()