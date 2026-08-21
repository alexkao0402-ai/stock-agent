# main.py
# 這是整個專案的「入口」，執行這個檔案就能跑完整流程：
# 使用者輸入股票代號 → 抓取歷史股價 → 清理資料 → AI 分析 → 印出報告

from src.stock_data import get_daily_stock_data, clean_stock_data
from src.ai_analysis import generate_report


def main():
    # 讓使用者輸入股票代號
    symbol = input("請輸入股票代號（例如 BTDR）：").strip().upper()

    print(f"\n正在抓取 {symbol} 的歷史股價資料...")
    raw_data = get_daily_stock_data(symbol)

    # 簡單檢查一下，如果 API 沒有回傳我們預期的資料結構，就提前告知使用者
    if "Time Series (Daily)" not in raw_data:
        print("抓取資料失敗，請確認股票代號是否正確，或稍後再試。")
        print("API 回傳內容：", raw_data)
        return

    df = clean_stock_data(raw_data)
    print(f"成功取得 {len(df)} 筆資料，時間範圍：{df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")

    print("\n正在請 AI 分析資料，請稍候...")
    report = generate_report(symbol, df)

    print("\n========== 研究報告 ==========")
    print(report)
    print("================================")


# 只有直接執行 main.py 時才會跑
if __name__ == "__main__":
    main()