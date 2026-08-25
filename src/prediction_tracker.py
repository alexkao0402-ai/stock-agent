# prediction_tracker.py
# 這個檔案負責處理「儲存與管理預測紀錄」的功能
# 核心原則：預測一旦存檔，原始預測數字絕對不能被修改，只能新增「事後驗證結果」的欄位

import os
import json
from datetime import datetime, timedelta

# 所有預測紀錄會存放在這個資料夾裡
PREDICTIONS_DIR = "predictions"


def save_prediction(symbol, current_price, structured_data, report_text, model_version="claude-sonnet-4-5"):
    """
    把一次分析的預測結果存成一個獨立的 JSON 檔案。

    symbol: 股票代號，例如 "BTDR"
    current_price: 分析當下的股價
    structured_data: extract_structured_data() 產生的字典（各情境的價格區間等）
    report_text: 完整的文字報告
    model_version: 使用的 AI 模型版本，方便未來比較不同模型的表現

    回傳：儲存的檔案路徑（字串）
    """

    # 如果 predictions 資料夾還不存在，就自動建立一個
    # exist_ok=True 代表「如果資料夾已經存在，不要報錯，直接略過」
    os.makedirs(PREDICTIONS_DIR, exist_ok=True)

    # 取得現在的時間，作為這筆預測的時間戳記
    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%dT%H:%M:%S")

    # 組成這筆預測紀錄的完整內容
    prediction_record = {
        "ticker": symbol,
        "timestamp": timestamp_str,
        "current_price_at_prediction": current_price,
        "model_version": model_version,
        "full_report_text": report_text,

        # 以下這些數字，如果 structured_data 是 None（代表 AI 那次沒有成功產生結構化資料），
        # 我們就用空字典 {} 代替，避免程式出錯
        **(structured_data if structured_data else {}),

        # 這幾個欄位是「事後驗證」用的，存檔當下一律是空的，
        # 之後 V0.7 Step 2 的「回顧比對」功能，才會回頭填入這些欄位
        "outcome_checked": False,
        "actual_price_at_check": None,
        "actual_return_pct": None,
        "which_scenario_occurred": None,
        "checked_at": None
    }

    # 用「股票代號_時間戳記」當作檔名，確保每次存檔都是獨一無二的檔名，不會互相覆蓋
    filename_timestamp = now.strftime("%Y-%m-%d_%H%M%S")
    filename = f"{symbol}_{filename_timestamp}.json"
    filepath = os.path.join(PREDICTIONS_DIR, filename)

    # 把這筆紀錄寫進檔案
    # ensure_ascii=False 讓中文字能正常儲存，不會變成亂碼的 unicode 編碼
    # indent=2 讓存出來的 JSON 檔案有適當的縮排，方便人類閱讀
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(prediction_record, f, ensure_ascii=False, indent=2)

    return filepath


def list_predictions(symbol=None):
    """
    列出所有已經存檔的預測紀錄。
    symbol: 如果指定股票代號，只列出該股票的紀錄；不指定則列出全部

    回傳：一個 list，每一項是一筆預測紀錄（字典格式）
    """

    if not os.path.exists(PREDICTIONS_DIR):
        return []

    records = []
    for filename in os.listdir(PREDICTIONS_DIR):
        if not filename.endswith(".json"):
            continue

        # 如果有指定股票代號，只讀取檔名開頭符合的檔案
        if symbol and not filename.startswith(f"{symbol}_"):
            continue

        filepath = os.path.join(PREDICTIONS_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            record = json.load(f)
            record["_filepath"] = filepath  # 順便記錄檔案路徑，方便之後更新這筆紀錄
            records.append(record)

    return records


def get_recent_prediction(symbol, max_age_hours=12):
    """Return the newest reusable analysis record within the requested age."""
    records = list_predictions(symbol)
    if not records:
        return None
    records.sort(key=lambda record: record.get("timestamp", ""), reverse=True)
    newest = records[0]
    try:
        created_at = datetime.fromisoformat(newest["timestamp"])
    except (KeyError, TypeError, ValueError):
        return None
    if datetime.now() - created_at > timedelta(hours=max_age_hours):
        return None
    return newest

def classify_scenario(actual_price, record):
    """
    判斷「實際股價」落在當初預測的哪個情境。

    actual_price: 現在的實際股價
    record: 一筆預測紀錄（字典），裡面應該要有 bull_low/high、base_low/high、bear_low/high

    回傳：一個字串，代表落在哪個情境
    """

    if actual_price is None:
        return None

    # 把三個情境的價格區間整理成一個清單，方便逐一檢查
    scenarios = [
        ("bear", record.get("bear_low"), record.get("bear_high")),
        ("base", record.get("base_low"), record.get("base_high")),
        ("bull", record.get("bull_low"), record.get("bull_high")),
    ]

    # 檢查實際股價有沒有落在某個情境的區間內
    for name, low, high in scenarios:
        if low is not None and high is not None and low <= actual_price <= high:
            return name

    # 如果沒有落在任何區間內，判斷是「比熊市情境還低」還是「比牛市情境還高」
    bear_low = record.get("bear_low")
    bull_high = record.get("bull_high")

    if bear_low is not None and actual_price < bear_low:
        return "below_bear（比悲觀情境還低）"
    if bull_high is not None and actual_price > bull_high:
        return "above_bull（比樂觀情境還高）"

    return "between_scenarios（介於情境之間，例如base與bull的空隙）"


def check_prediction_outcome(record, actual_price):
    """
    用「現在的實際股價」，回頭驗證一筆舊的預測紀錄。
    這個函式只會「新增」驗證結果欄位，絕對不會修改原始預測數字（bull_low等）。

    record: list_predictions() 讀回來的一筆紀錄（字典，包含 _filepath）
    actual_price: 現在的實際股價

    回傳：更新後的紀錄（同時也會把結果寫回原本的檔案）
    """

    original_price = record.get("current_price_at_prediction")

    # 計算報酬率：(現在價格 - 當初價格) / 當初價格 * 100
    if original_price:
        actual_return_pct = round((actual_price - original_price) / original_price * 100, 2)
    else:
        actual_return_pct = None

    which_scenario = classify_scenario(actual_price, record)

    # 更新這筆紀錄的驗證欄位（只動這幾個欄位，其他原始預測資料完全不碰）
    record["outcome_checked"] = True
    record["actual_price_at_check"] = actual_price
    record["actual_return_pct"] = actual_return_pct
    record["which_scenario_occurred"] = which_scenario
    record["checked_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # 把更新後的紀錄寫回原本的檔案
    filepath = record["_filepath"]
    # 存檔前先把 _filepath 這個「輔助用」欄位移除，因為它不該被存進 JSON 檔案本身
    record_to_save = {k: v for k, v in record.items() if k != "_filepath"}

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(record_to_save, f, ensure_ascii=False, indent=2)

    return record
