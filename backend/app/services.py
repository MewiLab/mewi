import json
import os
import random

DATA_DIR = os.path.join(os.path.dirname(__file__), "../evals/data")

async def get_scent_samples(count: int, category: str, mode: str):
    # ex. data_edge_short_zh.json
    filename = f"data_{category}_{mode}_zh.json"
    file_path = os.path.join(DATA_DIR, filename)
    
    if not os.path.exists(file_path):
        return []

    # read file
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # check if maximum, then return all data
    if count >= len(data):
        return data
    
    # randomly select samples
    return random.sample(data, count)