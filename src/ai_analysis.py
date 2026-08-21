# ai_analysis.py
# 這個檔案負責處理「把股價資料 + 新聞資料交給 AI 分析」的功能

import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic()


def format_news_for_prompt(news_list, max_items=15):
    """
    把新聞清單整理成一段文字，方便放進 prompt 裡給 AI 看。
    news_list: get_news_sentiment() 回傳的 list
    max_items: 最多放幾則新聞進 prompt（避免內容太長、太花費）
    回傳：一段文字
    """

    # 只取前 max_items 則，避免 prompt 太長
    selected_news = news_list[:max_items]

    if not selected_news:
        return "（目前沒有取得相關新聞資料）"

    lines = []
    for n in selected_news:
        # 把每則新聞整理成一行，格式：[時間] [情緒] 標題
        line = f"- [{n['time_published']}] [{n['overall_sentiment_label']}] {n['title']}"
        lines.append(line)

    return "\n".join(lines)


def generate_report(symbol, df, news_list=None):
    """
    把清理好的股價表格 (DataFrame) 和新聞清單，交給 Claude 產出研究報告。
    symbol: 股票代號，例如 "BTDR"
    df: clean_stock_data() 產生的 pandas DataFrame
    news_list: get_news_sentiment() 產生的新聞清單，可以不提供（預設 None）
    回傳：AI 生成的文字報告（字串）
    """

    data_text = df.to_string(index=False)

    # 如果有提供新聞資料，就整理成文字；沒有的話就給一個提示文字
    if news_list:
        news_text = format_news_for_prompt(news_list)
    else:
        news_text = "（本次分析未提供新聞資料）"

    prompt = f"""你是一位專業的股票研究分析師。

以下是股票代號 {symbol} 過去約 100 個交易日的每日價格與成交量資料（欄位：日期、開盤價、最高價、最低價、收盤價、成交量）：

{data_text}

以下是這支股票最近的相關新聞標題，附帶 AI 判斷的情緒標籤（Bullish=看漲, Bearish=看跌, Neutral=中性）：

{news_text}

請根據以上「歷史價格資料」與「新聞資料」，用繁體中文寫一份研究報告，內容包含：

1. 這段期間股價大致的走勢（上漲、下跌、盤整）
2. 波動最大的幾個時間點，並嘗試對應到附近時間點是否有相關新聞可以解釋這個變化
3. 成交量有沒有出現異常放大的時候，是否與新聞事件時間點吻合
4. 目前市場新聞的整體情緒氛圍（偏多、偏空、中立）
5. 用 2-3 句話總結目前這支股票的技術面與消息面狀態

請注意：
- 如果某個價格波動找不到對應的新聞可以解釋，請誠實說明「未找到明確對應消息」，不要臆測捏造原因
- 這只是根據歷史資料的研究觀察，不是投資建議"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1536,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    report_text = message.content[0].text

    return report_text