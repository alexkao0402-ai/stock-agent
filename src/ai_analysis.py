# ai_analysis.py
# 這個檔案負責處理「把股價資料交給 AI 分析」的功能

import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# 建立一個 Anthropic 的「客戶端」(client)
# 它會自動去讀取環境變數 ANTHROPIC_API_KEY，不用我們手動傳
client = Anthropic()


def generate_report(symbol, df):
    """
    把清理好的股價表格 (DataFrame) 交給 Claude，請它寫一份簡單的分析報告。
    symbol: 股票代號，例如 "BTDR"
    df: clean_stock_data() 產生的 pandas DataFrame
    回傳：AI 生成的文字報告（字串）
    """

    # df.to_string() 把整張表格轉換成純文字，這樣才能放進提示詞裡給 AI 看
    # index=False 代表不要把 pandas 自動編的列號也印出來
    data_text = df.to_string(index=False)

    # 這是我們要交給 AI 的指令（prompt）
    # 寫清楚「你是誰」「資料是什麼」「要做什麼」「用什麼語言回答」
    prompt = f"""你是一位專業的股票研究分析師。
以下是股票代號 {symbol} 過去約 100 個交易日的每日價格與成交量資料（欄位：日期、開盤價、最高價、最低價、收盤價、成交量）：

{data_text}

請根據這份歷史資料，用繁體中文寫一份簡短的分析報告，內容包含：
1. 這段期間股價大致的走勢（上漲、下跌、盤整）
2. 波動最大的幾個時間點，以及當時發生了什麼樣的價格變化
3. 成交量有沒有出現異常放大的時候
4. 用 2-3 句話總結目前這支股票的技術面狀態

請注意：這只是根據歷史價格資料的技術面觀察，不是投資建議。"""

    # 呼叫 Claude API
    message = client.messages.create(
        model="claude-sonnet-4-5",   # 使用的 AI 模型
        max_tokens=1024,              # 回覆內容的長度上限
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    # API 回傳的內容是一個「區塊列表」，我們取出第一個區塊的文字內容
    report_text = message.content[0].text

    return report_text