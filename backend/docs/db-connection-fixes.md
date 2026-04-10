# DB 連線問題修復記錄

## 概述

本次修復共涉及三個面向：

1. Agent 記憶透過 DB 補水（hydration）的功能缺口
2. Unit test 的 mock 不完整導致 DB 操作觸碰真實連線
3. `real_settings` fixture 從未實作導致 integration test 全數 ERROR

---

## 問題一：Agent 首次 tick 時記憶是空的，未從 DB 補水

### 問題來源

`AgentService.run_tick()` 雖然接收 `creature_id`，但沒有將它傳給 graph state，也沒有在執行前嘗試從 DB/Redis 恢復上一個 session 的記憶。

### 根本原因

`MemoryManager` 是 in-memory 的 ring buffer，每次 app 重啟後都是空的。`hydrate_agent()` 雖然已實作（在 `memory_service.py`），但只在 `lifespan.py` 的 startup hook 中被呼叫一次，且帶的是硬編碼的 `creature_id="cat_01"`。真正從 Unity 傳入的 `creature_id` 在 `run_tick` 中拿到了，卻沒有被用來觸發補水。

### 影響

- Agent 在重啟後第一個 tick 推理時記憶永遠為空，LLM context 缺少歷史資料
- graph state 中沒有 `creature_id`，未來需要在 graph 節點內查詢 DB 時無從取得

### 修復內容

| 檔案 | 修改 |
|---|---|
| `app/agent/schemas/state_schema.py` | 新增 `creature_id: str` 欄位 |
| `app/services/agent_service.py` | 新增 `_hydrate_if_empty(creature_id)`；在 `run_tick` 呼叫 graph 前先補水；graph state 加入 `creature_id` |
| `app/workers/agent_worker.py` | graph state 加入 `creature_id` 保持一致 |

### `_hydrate_if_empty` 邏輯

```
_hydrate_if_empty(creature_id):
  tick_count > 0  →  直接返回（記憶已在，正常運行中）
  supabase = None →  直接返回（沒有 DB，從空記憶開始）
  否則            →  呼叫 hydrate_agent(agent, supabase, redis, creature_id)
                      └─ Redis 有 cache → 直接用
                      └─ Redis 沒 cache → 從 Supabase 讀，並回填 Redis
```

---

## 問題二：unit test 的 mock_redis 未覆蓋 MemoryCache 使用的指令

### 問題來源

`tests/conftest.py` 的 `mock_redis` fixture 只 mock 了 `set` 和 `get`，沒有 mock `MemoryCache` 實際使用的四個 Redis 指令。

### 根本原因

`MemoryCache`（`repositories/memory_cache.py`）使用：

| 方法 | 對應指令 |
|---|---|
| `push_tick` | `rpush`, `ltrim` |
| `load_ticks` | `lrange` |
| `clear` | `delete` |

這些在 `AsyncMock()` 產生的 mock 上自動會回傳另一個 `MagicMock`，迭代或 await 時行為不可預期。

### 影響

當 `_hydrate_if_empty` → `hydrate_agent` → `MemoryCache.load_ticks` 呼叫 `lrange` 時，因為 mock 沒設定，`lrange` 回傳 `MagicMock` 物件，後續 `json.loads(entry)` 炸掉或回傳垃圾資料。

### 修復內容

`tests/conftest.py` 的 `mock_redis` 補上：

```python
client.lrange = AsyncMock(return_value=[])   # load_ticks：cache miss → 回傳空
client.rpush  = AsyncMock(return_value=1)    # push_tick
client.ltrim  = AsyncMock()                  # push_tick（trim to max size）
client.delete = AsyncMock()                  # clear
```

---

## 問題三：`test_agent_tick_returns_200_with_action` 觸發了真實 DB 查詢

### 問題來源

`tests/unit/api/test_api_routes.py` 的 agent tick 測試只 override 了 `get_graph`，沒有 override `get_agent`。

### 根本原因

`_hydrate_if_empty` 的判斷條件是 `tick_count == 0` → 執行 DB 補水。FastAPI TestClient 的 lifespan 建立的是真實 `CreatureAgent`（`tick_count = 0`），而測試的 `mock_db` 對所有 table 共用同一個 builder，`execute()` 永遠回傳：

```python
MagicMock(data=[FAKE_ROW])
```

`FAKE_ROW` 是 microlog 的 row schema，沒有 `"perception"` 欄位。`hydrate_agent` 執行到：

```python
await cache.push_tick(creature_id=creature_id, perception=row["perception"])
```

就拋出 `KeyError: 'perception'`，導致整個 tick 以 500 失敗。

### 影響

`POST /api/v1/agent/tick` 測試期望 200，實際收到 500。

### 修復內容

測試中加入 `get_agent` override，給 `tick_count = 1`，讓 `_hydrate_if_empty` 直接 return：

```python
mock_agent = MagicMock()
mock_agent.memory.tick_count = 1          # 讓 _hydrate_if_empty 跳過 DB
mock_agent.body.available_actions = ["wait", "move"]
client.app.dependency_overrides[get_agent] = lambda: mock_agent
```

這個測試的目的是驗證 graph 結果能正確回傳至 HTTP response，不是測補水流程，所以跳過 hydration 語意上是正確的。

---

## 問題四：`real_settings` fixture 從未被實作

### 問題來源

`tests/conftest.py` 的 docstring 第 6 行已明確記載：

> Integration fixtures (`real_*`): loads real credentials from `.env`. Only used when running `make test-integration CONFIRM_PAID=1`.

但 `real_settings` fixture 的實作從來沒有寫進去。

### 根本原因

純粹是遺漏。所有使用 `real_settings` 的測試（涵蓋 unit 和 integration 目錄）在 pytest 收集時就直接 ERROR：

```
fixture 'real_settings' not found
```

受影響的測試檔：

- `tests/unit/core/test_supabase_connection.py`
- `tests/unit/core/test_redis_real.py`
- `tests/unit/services/test_embedding_real.py`
- `tests/integration/test_supabase_connection.py`
- `tests/integration/test_redis_real.py`
- `tests/integration/test_fullstack_e2e.py`

### 修復內容

`tests/conftest.py` 新增：

```python
@pytest.fixture
def real_settings():
    url    = os.environ.get("SUPABASE_URL", "")
    anon   = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    secret = os.environ.get("SUPABASE_SECRET_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not all([url, anon, secret]):
        pytest.skip("real_settings requires SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY / SUPABASE_SECRET_KEY in .env")
    return Settings(
        supabase_url=url,
        supabase_publishable_key=anon,
        supabase_secret_key=secret,
        openai_api_key=openai_key or "sk-fake",
    )
```

- 有 `.env` 且憑證齊全 → 建立真實 `Settings` 物件
- 缺少任一憑證 → `pytest.skip`，不爆紅、不阻擋 `make test`

---

---

## 問題五：`test_redis_real` 呼叫不存在的公開方法 `set_status`

### 問題來源

`tests/unit/core/test_redis_real.py` 呼叫 `svc.set_status(...)`，但 `AgentService` 的對應方法是私有的 `_set_status`（底線前綴）。

### 根本原因

測試寫作時用了公開 API 的命名，但實作刻意將其設為私有（CLAUDE.md 設計原則：status 寫入只透過 `run_tick` 觸發，外部不應直接呼叫）。兩者命名從未對齊過。

### 影響

```
AttributeError: 'AgentService' object has no attribute 'set_status'.
Did you mean: '_set_status'?
```

### 修復內容

`test_redis_real.py` 中所有 `svc.set_status(` 改為 `svc._set_status(`。
Integration test 測試內部行為，直接呼叫私有方法是合理的。

---

## 問題六：`get_status` 對 `decode_responses=True` 的 Redis client 炸掉

### 問題來源

`get_status` 的回傳邏輯：

```python
return value.decode() if value else "idle"
```

`.decode()` 是 `bytes` 型別的方法。當 Redis client 建立時帶了 `decode_responses=True`，`get()` 直接回傳 `str`，對 `str` 呼叫 `.decode()` 就炸。

### 根本原因

`test_redis_real.py` 建立 client 時設了 `decode_responses=True`（第 19 行）：

```python
pool = aioredis.ConnectionPool.from_url(
    f"redis://{real_settings.redis_host}:{real_settings.redis_port}/0",
    decode_responses=True,
)
```

而 production lifespan 建立的 Redis client 沒有設此選項，所以 `get()` 回傳 `bytes`。兩種情境行為不同，`get_status` 只處理了其中一種。

### 影響

```
AttributeError: 'str' object has no attribute 'decode'. Did you mean: 'encode'?
```
`test_set_and_get_status` 寫入成功、讀取時炸掉。

### 修復內容

`app/services/agent_service.py` 的 `get_status` 改為同時處理兩種回傳型別：

```python
if not value:
    return "idle"
return value.decode() if isinstance(value, bytes) else value
```

- `bytes`（production，`decode_responses` 未設）→ `.decode()`
- `str`（`decode_responses=True` 的 client）→ 直接回傳
- `None`（key 不存在）→ `"idle"`

---

## 修改檔案總覽

| 檔案 | 類型 | 修改說明 |
|---|---|---|
| `app/agent/schemas/state_schema.py` | 功能 | 新增 `creature_id` 欄位 |
| `app/services/agent_service.py` | 功能 | 新增 `_hydrate_if_empty`；`run_tick` 補水並傳入 `creature_id`；`get_status` 相容 `str`/`bytes` 兩種 Redis 回傳型別 |
| `app/workers/agent_worker.py` | 功能 | graph state 補上 `creature_id` |
| `tests/conftest.py` | 測試基礎建設 | 新增 `real_settings` fixture；補全 `mock_redis` 的 Redis 指令 |
| `tests/unit/api/test_api_routes.py` | 測試修復 | `test_agent_tick` 補 `get_agent` override，避免觸碰真實 DB |
| `tests/unit/workers/test_agent_worker.py` | 測試修復 | `mock_agent.body.get_state` 改為 `AsyncMock` |
| `tests/unit/services/test_agent_service.py` | 測試新增 | 新增 4 個測試驗證補水行為 |
| `tests/unit/core/test_redis_real.py` | 測試修復 | `set_status` → `_set_status`，對齊實際方法名稱 |
