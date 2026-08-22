# ai_analysis.py
# 這個檔案負責處理「把股價資料 + 新聞資料 + 公司基本面資料交給 AI 分析」的功能

import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic()


def format_news_for_prompt(news_list, max_items=15):
    """
    把新聞清單整理成一段文字，方便放進 prompt 裡給 AI 看。
    """
    selected_news = news_list[:max_items]

    if not selected_news:
        return "（目前沒有取得相關新聞資料）"

    lines = []
    for n in selected_news:
        line = f"- [{n['time_published']}] [{n['overall_sentiment_label']}] {n['title']}"
        lines.append(line)

    return "\n".join(lines)


def format_overview_for_prompt(overview):
    """
    把公司基本面資料整理成一段文字，方便放進 prompt 裡給 AI 看。
    """
    if not overview:
        return "（目前沒有取得公司基本面資料）"

    lines = []
    for key, value in overview.items():
        if key == "公司簡介":
            value = str(value)[:200] + "..."
        lines.append(f"- {key}：{value}")

    return "\n".join(lines)


def generate_report(symbol, df, news_list=None, overview=None):
    """
    把清理好的股價表格 (DataFrame)、新聞清單、公司基本面資料，交給 Claude 產出研究報告。
    symbol: 股票代號，例如 "BTDR"
    df: clean_stock_data() 產生的 pandas DataFrame
    news_list: get_news_sentiment() 產生的新聞清單，可以不提供（預設 None）
    overview: get_company_overview() 產生的基本面字典，可以不提供（預設 None）
    回傳：AI 生成的文字報告（字串）
    """

    data_text = df.to_string(index=False)

    if news_list:
        news_text = format_news_for_prompt(news_list)
    else:
        news_text = "（本次分析未提供新聞資料）"

    if overview:
        overview_text = format_overview_for_prompt(overview)
    else:
        overview_text = "（本次分析未提供公司基本面資料）"

    prompt = f"""你是一位專業的股票研究分析師。

以下是股票代號 {symbol} 過去約 100 個交易日的每日價格與成交量資料（欄位：日期、開盤價、最高價、最低價、收盤價、成交量）：

{data_text}

以下是這支股票最近的相關新聞標題，附帶 AI 判斷的情緒標籤（Bullish=看漲, Bearish=看跌, Neutral=中性）：

{news_text}

以下是這家公司的基本面總覽資料：

{overview_text}

請根據以上「歷史價格資料」「新聞資料」「公司基本面資料」，用繁體中文寫一份研究報告，分成以下四大部分：

## 第一部分：基本面摘要
用 3-4 句話總結這家公司目前的基本面體質：市值規模、獲利能力（本益比、每股盈餘是否合理）、營收與毛利表現，並簡述公司主要業務。如果某些數字缺失或不適用，請誠實說明「資料不足」，不要瞎猜數字。

## 第二部分：歷史回顧
1. 這段期間股價大致的走勢（上漲、下跌、盤整）
2. 波動最大的幾個時間點，並嘗試對應到附近時間點是否有相關新聞可以解釋這個變化
3. 成交量有沒有出現異常放大的時候，是否與新聞事件時間點吻合
4. 目前市場新聞的整體情緒氛圍（偏多、偏空、中立）

## 第三部分：未來情境推估
請注意，這一部分**不是預測**，而是「根據目前已知資訊，推估幾種可能的走向」。
請列出三種情境，每種情境都要包含：「觸發條件」「大致的價格區間」「推估邏輯」：

### Bull Case（樂觀情境）
- 什麼條件成立時，股價可能走向這個情境
- 大致價格區間推估（用「大約落在 X~Y 美元」這種語氣，不要給出精確數字）
- 支撐這個推估的邏輯

### Base Case（中性情境）
- 同上結構

### Bear Case（悲觀情境）
- 同上結構

## 第四部分：參考價位區間
在完成三情境分析後，請根據目前股價位置與歷史波動特性，額外提供以下三個參考區間：

### 潛在進場區（Entry Zone）
如果有人想根據這份分析考慮進場，從風險報酬的角度來看，大約在什麼價格區間介入，相對比較合理？請說明理由。

### 潛在停利區（Take-Profit Zone）
如果進場後股價朝 Bull Case 或 Base Case 發展，大約在什麼價格區間附近，可以考慮獲利了結？請說明理由。

### 論點失效價位（Invalidation Level）
如果股價跌破（或漲破）什麼價位，代表這整份分析的前提假設可能是錯的，應該重新檢視整個判斷，而不是繼續套用這份報告的邏輯？請說明理由。

最後用 2-3 句話總結，說明目前市場證據比較支持哪一種情境「傾向」，但強調三種情境都有可能發生。

請務必遵守以下原則：
- 如果某個價格波動找不到對應的新聞可以解釋，請誠實說明「未找到明確對應消息」，不要臆測捏造原因
- 價格區間是「基於歷史波動幅度與現有消息面的粗略推估」，絕對不要用「將會達到」「保證」這類肯定語氣，要用「可能」「傾向」「若條件成立」這類語氣
- 進場區、停利區、失效價位是「研究性質的參考區間」，不是明確的買賣訊號，請在這部分結尾明確提醒讀者：這不是投資建議，實際操作應自行判斷並考量自身風險承受度
- 這整份報告只是研究觀察與情境推演，不是投資建議，也不是精確預測"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    report_text = message.content[0].text

    return report_text

import json


def extract_structured_data(symbol, current_price, report_text):
    """
    把已經生成的文字報告，交給 AI 整理成結構化的 JSON 數字資料。
    這一步只負責「格式轉換」，不做新的分析判斷，只是把報告裡已經提到的數字整理出來。

    symbol: 股票代號
    current_price: 目前股價（分析當下最後一筆收盤價）
    report_text: generate_report() 產生的文字報告
    回傳：一個 Python 字典（如果解析失敗，回傳 None）
    """

    extraction_prompt = f"""以下是一份關於 {symbol} 的股票研究報告：

{report_text}

請從這份報告中，把「未來情境推估」與「參考價位區間」部分提到的數字，整理成純 JSON 格式輸出。

規則：
- 只能輸出 JSON，前後不要有任何其他文字、說明、或 Markdown 符號（不要用```json 包起來）
- 如果報告中某個數字沒有明確提到，該欄位請填 null，不要自己編造
- JSON 格式如下：

{{
  "current_price": {current_price},
  "bull_low": 數字或null,
  "bull_high": 數字或null,
  "base_low": 數字或null,
  "base_high": 數字或null,
  "bear_low": 數字或null,
  "bear_high": 數字或null,
  "entry_zone_low": 數字或null,
  "entry_zone_high": 數字或null,
  "take_profit_low": 數字或null,
  "take_profit_high": 數字或null,
  "invalidation_down": 數字或null,
  "invalidation_up": 數字或null
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=500,
        messages=[
            {"role": "user", "content": extraction_prompt}
        ]
    )

    raw_text = message.content[0].text.strip()

    # AI 有時候會習慣性地在 JSON 外面包上 ```json 和 ``` 這種 Markdown 符號
    # 這裡做清理：如果偵測到這些符號，就把它們去掉，只留下純 JSON 內容
    if raw_text.startswith("```"):
        # 去掉開頭的 ```json 或 ```（可能後面還接著換行）
        raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text
        # 去掉結尾的 ```
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

    try:
        structured_data = json.loads(raw_text)
        return structured_data
    except json.JSONDecodeError:
        return None

if __name__ == "__main__":
    from src.stock_data import get_daily_stock_data, clean_stock_data, get_news_sentiment, get_company_overview

    raw = get_daily_stock_data("BTDR")
    df = clean_stock_data(raw)
    news = get_news_sentiment("BTDR", limit=10)
    overview = get_company_overview("BTDR")

    report = generate_report("BTDR", df, news, overview)
    print("===== 文字報告（節錄前500字）=====")
    print(report[:500])

    current_price = df["close"].iloc[-1]
    structured = extract_structured_data("BTDR", current_price, report)

    print("\n\n===== 結構化資料 =====")
    print(structured)