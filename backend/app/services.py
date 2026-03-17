import json
import os

MOCK_DATA_PATH = os.path.join(os.path.dirname(__file__), "mock_data/test_sample.json")

async def get_scent_samples(count: int, category: str, mode: str):
    with open(MOCK_DATA_PATH, "r", encoding="utf-8") as f:
        all_data = json.load(f)
    
    # 找出符合類別跟模式的資料
    filtered = [
        item for item in all_data 
        if item["routing_label"].lower() == category.lower() 
        and item["mode"].lower() == mode.lower()
    ]
    
    # 如果過濾完沒東西，就隨機回傳一筆保險
    result = filtered if filtered else all_data
    return result[:count]