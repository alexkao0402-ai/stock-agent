# cache_utils.py
# 這個檔案負責處理「資料快取」的通用邏輯
# 目的：避免同一份資料在短時間內被重複呼叫 API，節省額度

import os
import json
from datetime import datetime, timedelta

CACHE_DIR = "cache"


def get_cache_path(cache_key):
    """
    根據快取的名稱（cache_key），組出對應的檔案路徑。
    cache_key: 例如 "BTDR_daily_price"
    回傳：完整檔案路徑字串
    """
    return os.path.join(CACHE_DIR, f"{cache_key}.json")


def save_to_cache(cache_key, data):
    """
    把資料存進快取檔案，同時記錄「存檔的時間」。

    cache_key: 快取的名稱，例如 "BTDR_daily_price"
    data: 要儲存的資料（必須是可以轉換成 JSON 的格式，例如字典或清單）
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    cache_content = {
        "cached_at": datetime.now().isoformat(),
        "data": data
    }

    filepath = get_cache_path(cache_key)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(cache_content, f, ensure_ascii=False, indent=2)


def load_from_cache(cache_key, max_age_hours):
    """
    嘗試從快取讀取資料，並檢查是否還「新鮮」（沒有過期）。

    cache_key: 快取的名稱，例如 "BTDR_daily_price"
    max_age_hours: 這份快取最多可以放多久（小時），超過這個時間就視為過期

    回傳：
      - 如果快取存在且沒過期：回傳快取裡的資料
      - 如果快取不存在，或已經過期：回傳 None
    """
    filepath = get_cache_path(cache_key)

    if not os.path.exists(filepath):
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        cache_content = json.load(f)

    cached_at = datetime.fromisoformat(cache_content["cached_at"])
    age = datetime.now() - cached_at

    if age > timedelta(hours=max_age_hours):
        # 快取已經過期，回傳 None，讓呼叫端知道需要重新抓取
        return None

    return cache_content["data"]

if __name__ == "__main__":
    import time

    # 測試 1：存一筆假資料，馬上讀回來，應該要能成功讀到
    save_to_cache("test_key", {"hello": "world"})
    result = load_from_cache("test_key", max_age_hours=1)
    print("測試1（剛存完馬上讀，應該要有資料）：", result)

    # 測試 2：用「max_age_hours=0」，代表「任何存過的資料都算過期」，應該要讀不到
    result2 = load_from_cache("test_key", max_age_hours=0)
    print("測試2（設定0小時過期，應該要是 None）：", result2)