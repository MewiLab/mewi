# ADR-0001: 使用 BERT-based 模型作為動態路由分類器與特化資料建構管線

## Status
Accepted (已接受)

## Context (背景情境)
在國科會計畫「混合雲架構代理人系統」中，核心挑戰為 **RQ1 (動態路由機制)**。系統需在邊緣端（手機 App）判斷微日記語意，決定運算卸載（Offloading）路徑。
1. **任務類型**：中/英雙語文本二分類（Binary Classification）。
2. **場域限制**：須對成大生活用語（如：育樂街、總圖）具高度敏感度，且需克服合成資料常見的「空間幻覺」。
3. **魯棒性需求**：須能處理行動端常見的輸入缺陷（錯字、語法凌亂）。

## Decision (決策)
採用 **Pre-trained BERT-based model** 並構建一套具備彈性的 **合成語料開發管線 (Synthetic Data Pipeline)**。

### 1. 資料集建構決策 (Data Engineering)
- **LBS 約束機制**：導入成大五大地景白名單（聖誕樹、成功湖、小西門、總圖、育樂街），消除虛假地點。
- **混合噪聲注入 (Noise Injection)**：透過參數控制模擬 0.0~0.8 機率的輸入缺陷，用於測試模型信心區間。
- **自動化生產線**：開發 `runner.py` 實作實驗矩陣的批量生產。

### 2. 模型決策
- **基礎模型**：`bert-base-chinese` (中文) / `bert-base-uncased` (英文)。
- **部署技術**：使用 TensorFlow Lite (TFLite) 進行量化後部署。

---

## 🛠️ Tooling & Usage (工具與使用說明)

為了維持開發彈性，我們實作了具備參數化接口的生成器。

### A. Generator 參數說明 (`generate_dataset.py`)
| 參數 | 說明 | 選項 / 範例 |
| :--- | :--- | :--- |
| `--api_key` | GitHub Models API Token | (必要參數) |
| `--mode` | 文本長度控制 | `long` (80-100字) / `short` (20-40字) |
| `--category` | 預期路由分類 | `edge` (直白) / `cloud` (隱晦/情緒) |
| `--lang` | 生成語言 | `zh` / `en` |
| `--noise` | 噪聲注入強度 | `0.0` 到 `1.0` (建議壓力測試用 0.8) |
| `--count` | 該批次生成數量 | 預設 `10` |

### B. 快速執行範例
**1. 生成高品質 Edge 端種子資料：**
```bash
python generate_dataset.py --api_key YOUR_TOKEN --mode short --category edge --noise 0.1 --count 20