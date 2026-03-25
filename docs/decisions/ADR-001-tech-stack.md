# ADR-0001: 使用 BERT-based 模型作為動態路由分類器與特化資料建構管線

## Status
Accepted (已接受) - v3.5 強化版

## Context (背景情境)
在國科會計畫「混合雲架構代理人系統」中，核心挑戰為 **RQ1 (動態路由機制)**。系統需在邊緣端（手機 App）判斷微日記語意，決定運算卸載（Offloading）路徑。
1. **任務類型**：中/英雙語文本二分類（Binary Classification）。
2. **場域限制**：須對成大生活用語（如：育樂街、成功湖、總圖）具高度敏感度。
3. **資料分布挑戰**：需同時處理極簡碎碎念（Short）與具備豐富細節的長篇日記（Long），並需精準區分「直白事實描述」（Edge）與「深層情緒/隱喻」（Cloud）。

## Decision (決策)
採用 **Pre-trained BERT-based model** 並構建一套具備 **多級距範例 (Multi-shot)** 與 **結構化補丁 (Structural Patching)** 的合成語料開發管線 (Synthetic Data Pipeline)。



### 1. 資料集建構決策 (Data Engineering)
- **多級距長度控制 (Multi-scale Length Control)**：
  - **Short 模式**：模擬即時社群動態，分布於 20、30、40 字/詞。
  - **Long 模式**：模擬深度心情日記，分布於 80、100、120 字/詞。
- **結構化提示補丁 (Structural Patching)**：針對長篇文本強制執行「場景細節、事件過程、深度獨白」三段式生成指令，解決 LLM 生成懶惰（Laziness）導致字數不足的問題。
- **LBS 與 Null 約束機制**：
  - 導入成大地景白名單（聖誕樹、成功湖、小西門、總圖、育樂街）。
  - 配置 **40% 的「無地點 (Null LBS)」樣本**，強迫模型學習純語意情緒而非僅依賴地標關鍵字，避免空間幻覺。
- **混合噪聲注入 (Noise Injection)**：透過參數模擬輸入缺陷（如錯字、無意義符號），壓力測試模型信心區間。

### 2. 風險管理與資料特性 (Risk Management)
- **標籤邊界模糊處理 (Label Inconsistency)**：部分 `Edge` 資料集中可能包含微弱的情緒特徵（如對排隊的不耐煩）。
  - **決策**：刻意保留此類「困難樣本 (Hard Examples)」，用以訓練模型在複雜語意下的決策邊界，而非僅依賴生硬的標籤分類。這有助於路由器判斷任務是否真的需要消耗雲端資源。

### 3. 模型決策
- **基礎模型**：使用 `bert-base-chinese` (中文) 與 `bert-base-uncased` (英文)。
- **部署技術**：使用 TensorFlow Lite (TFLite) 進行量化後部署至行動端。

---

## 🛠️ Tooling & Usage (工具與使用說明)

為了維持開發與實驗彈性，我們實作了具備參數化接口的生成器。

### A. Generator 參數說明 (`generate_dataset.py`)

| 參數 | 說明 | 選項 / 範例 |
| :--- | :--- | :--- |
| `--api_key` | GitHub Models API Token | (必要參數) |
| `--mode` | 文本長度控制 | `long` (80-120字) / `short` (20-45字) |
| `--category` | 預期路由分類 | `edge` (直白事實) / `cloud` (隱晦情緒) |
| `--lang` | 生成語言 | `zh` / `en` (英文採 Word-count 邏輯) |
| `--noise` | 噪聲注入強度 | `0.1` (低噪) / `0.5` (高噪壓力測試) |
| `--count` | 單次生成數量 | 建議設為 `10` 以確保穩定性 |

### B. 快速執行範例

**1. 生成高品質 Cloud 端長篇語料 (含結構化補丁)：**
```bash
python runner.py --api_key github_pat_你的TOKEN --count 單次生成次數(建議10~20)