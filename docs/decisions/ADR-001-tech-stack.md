# ADR-0001: 使用 BERT-based 模型作為中文微日記之動態路由分類器

## Status
Accepted (已接受)

## Context (背景情境)
在國科會計畫之「混合雲架構代理人系統」中，核心挑戰在於 **RQ1 (動態路由機制)**。
系統需在邊緣端（手機 App）即時判斷使用者輸入的微日記語意，決定運算卸載（Offloading）路徑：
1. **任務類型**：中文文本二分類（Binary Classification）。
2. **分類目標**：
   - **Edge (本地處理)**：語意直白、描述性事實、具備明確 LBS 資訊。
   - **Cloud (雲端處理)**：語意模糊、具備反諷、隱喻或深層情緒需求。
3. **場域限制**：
   - 須對成大校園生活用語（如：育樂街、計中、成功湖）具備高度敏感度。
   - 須克服大語言模型（LLM）生成資料時產生的 **「空間幻覺 (Spatial Hallucination)」**（如編造不存在的地標）。
   - 須處理長短不一（20-100字）的非結構化輸入。

## Decision (決策)
我們決定採用 **Pre-trained BERT-based Chinese model**（首選：`bert-base-chinese`）作為基礎模型，並使用自建之 **1,000 筆「成大校園特化型」資料集** 進行監督式微調（Supervised Fine-tuning）。

### 資料集建構決策 (Data Engineering)：
- **Seed-based Generation**：利用 GPT-4o 生成 200 筆高品質種子語料（Seed Data）。
- **LBS 硬性約束 (White-listing)**：導入 12 處真實成大地標白名單，強制模型僅能選取真實存在的地點。
- **長度多樣性 (Length Diversity)**：混合生成「短句型 (20-40字)」與「長句型 (80-100字)」，確保路由決策不產生長度依賴偏誤。
- **數據增廣 (Data Augmentation)**：透過同義詞替換與語法變換，將 200 筆精選資料擴充至 1,000 筆平衡語料。

## Consequences (影響與結果)

### Positive (優點)
- **上下文感知 (Context-Aware)**：BERT 的 Transformer 架構能精準捕捉「反諷」語氣，確保隱喻型日記準確送往雲端。
- **實地真實性 (Ground Truth Verifiability)**：因導入 LBS 白名單，模型對成大場景的理解具備物理真實性。
- **小樣本微調效率**：透過 Pre-trained 權重，僅需 1,000 筆資料即可達到預期 F1-Score > 0.90。
- **邊緣端相容性**：模型可導出為 `.tflite` 格式，實現手機端 <150ms 的推論延遲。



### Negative (缺點)
- **維護成本**：若校園地標發生重大更動（如系館搬遷），需重新校準 LBS 白名單並重訓模型。
- **資源佔用**：儘管量化後體積縮小，仍會佔用約 40-80MB 的行動裝置記憶體。

## Alternatives Considered (曾考慮的替代方案)
1. **Regex / Keyword Heuristics**：無法處理「這 Bug 真貼心」等反諷語意。
2. **Cloud-only LLM Inference**：延遲過高（Latency > 1s），且 API 成本難以支撐大規模日常使用。
3. **FastText / Word2Vec**：在處理字數較少且語意複雜的「微日記」時，準確度顯著低於 BERT。

## Implementation Plan (實施計畫)
1. **資料準備**：執行 `generate_dataset.py` 獲取 LBS 約束下的 200 筆高品質 JSON 資料。
2. **數據擴充**：運行 `augment_data.py` 將語料擴充至 1,000 筆，並進行長度分佈檢查。
3. **模型微調**：使用 `transformers` 進行 5-10 Epochs 的微調訓練。
4. **驗證與壓縮**：進行 Post-training Quantization (PTQ) 並導出至 Android/iOS 端。

## Related (相關參考)
- **Research Question**: RQ1 - 混合雲路由決策最佳化。
- **Dataset**: `general_base_long/short.json` 與 `edge_cases_long/short.json`。
- **Evaluation Metric**: SOI (State Oscillation Index) 狀態震盪指數。