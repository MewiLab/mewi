import pandas as pd
import json
import os

def convert_to_csv():
    raw_path = os.path.join("..", "data", "raw")
    processed_path = os.path.join("..", "data", "processed")
    
    if not os.path.exists(processed_path):
        os.makedirs(processed_path)

    all_data = []
    # 讀取 base 和 edge 兩個檔案
    for filename in ["general_base_generated.json", "general_edge_generated.json"]:
        with open(os.path.join(raw_path, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
            for item in data:
                # 簡化為 BERT 需要的 text 與 label (0: Edge, 1: Cloud)
                label = 0 if item["routing_label"] == "Edge" else 1
                all_data.append({"text": item["text"], "label": label})

    df = pd.DataFrame(all_data)
    df.to_csv(os.path.join(processed_path, "train.csv"), index=False, encoding="utf-8-sig")
    print(f"BERT 訓練資料已轉換完成：{len(df)} 筆")

if __name__ == "__main__":
    convert_to_csv()