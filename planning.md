# Refactor: Async Job Polling (webhook → poll)

## Problem

The current architecture uses a reverse-webhook: after running LangGraph, the backend
POSTs the result back to `http://localhost:8080/action` on the Unity client.  
This works in local dev but **breaks in production** — a cloud server cannot reach a
port behind a player's NAT/firewall.

## Target Architecture

```
Unity                              FastAPI backend                  Redis
──────                             ───────────────                  ─────
POST /api/v1/agent/tick  ────────▶  enqueue job              ────▶ job:{id} = "pending"
◀────  202 { job_id }
                                   BackgroundTask / worker
                                     runs LangGraph pipeline
                                     writes result            ────▶ job:{id} = { action… }

GET /api/v1/agent/tick/result/{id}  ◀──  poll every ~1.5 s
◀────  { status:"pending" }  or  { status:"done", action:… }
       on "done": apply LLMIntent, clear job
```

No listener on port 8080. No backend-initiated connections. All HTTP flows
Unity → backend.

---

## Work Items

### Backend

#### 1. `backend/app/api/routes/agent_router.py`

- **Change `POST /agent/tick`**
  - Enqueue a background job to Redis (`job:{uuid}` → `"pending"`)
  - Fire `BackgroundTasks.add_task(run_agent_job, job_id, payload, redis, settings, graph)`
  - Return `202 { "job_id": "…" }` immediately (do NOT `await graph.ainvoke` inline)

- **Add `GET /agent/tick/result/{job_id}`**
  - Read `job:{job_id}` from Redis
  - If missing or `"pending"`: return `{ "status": "pending" }`
  - If JSON object: return `{ "status": "done", "action": … }` and delete the key

#### 2. `backend/app/services/agent_service.py` — add job methods

`AgentService` owns ALL agent state in Redis (status + jobs).
Add four methods:
- `enqueue_job(job_id)` — set `job:{id}` = `"pending"`
- `complete_job(job_id, result_dict)` — set `job:{id}` = `{"status":"done", …}`
- `fail_job(job_id)` — set `job:{id}` = `{"status":"error"}`
- `consume_job(job_id)` — read + delete terminal keys; return status dict

Key points:
- 120-second TTL on all keys so stale jobs self-clean
- **`fail_job` writes `{"status":"error"}`, never deletes the key** — if the key
  were deleted, the GET endpoint would see a missing key and return `"pending"`,
  causing Unity to poll for the full 30 s timeout instead of aborting immediately.
- Router and worker never touch `job:*` keys directly — only via `AgentService`.

#### 3. `backend/app/workers/agent_tasks.py`

Replace the `asyncio.sleep(3)` stub with `run_agent_job`:
- Receives `job_id`, `payload`, `redis`, `settings`, `graph`, `agent`
- Creates `AgentService(redis, settings)` internally
- Calls `graph.ainvoke(…)`, extracts `action_result` + `kwargs`
- Flattens kwargs into `x, y, z, target` to match Unity's `ActionCallback` shape
- Calls `svc.complete_job(…)` on success, `svc.fail_job(…)` on exception
- No POST back to Unity

#### 4. `backend/app/agent/graph.py` — change `make_act_node`

The act node no longer calls `agent.act()` (which used to POST to Unity port 8080).
It now returns the chosen action as data only — delivery is via Redis polling.

Before:
```python
result = await agent.act(chosen["action"], **chosen.get("kwargs", {}))
return {"action_result": {"success": result.success, "action": result.action}}
```

After:
```python
return {"action_result": {"action": chosen["action"], "kwargs": chosen.get("kwargs", {})}}
```

#### 5. Remove backend action-callback code

The backend no longer calls `POST localhost:8080/action` — delete any such code in
`agent_tasks.py` or `agent_service.py`.

---

### Unity

#### 6. `AgentMindBridge.cs` — remove the HTTP listener

Delete:
- `StartListener()`, `Listen()`, `HandleHttp()`, `Send(resp, …)` methods
- `HttpListener _listener` field
- The background `Thread`
- `Application.runInBackground = true` (no longer needed for the listener)
- `listenerPort` inspector field
- The `/state` endpoint (or keep separately if used by other systems — check first)

#### 7. `AgentMindBridge.cs` — change `SendTick()` to return job_id

```csharp
// Old: fire-and-forget POST
// New: POST → receive 202 → start PollResult coroutine

public string SendTick(CreatureBlackboard board)
{
    string localId = Guid.NewGuid().ToString("N")[..8];
    string json    = BuildSnapshotJson(board, localId);
    StartCoroutine(PostAndPoll(json));
    return localId;   // PeriodicMind still stores this as _pendingId
}

IEnumerator PostAndPoll(string json)
{
    // 1. POST tick → get job_id
    var post = new UnityWebRequest(backendUrl, "POST");
    post.uploadHandler   = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
    post.downloadHandler = new DownloadHandlerBuffer();
    post.SetRequestHeader("Content-Type", "application/json");
    yield return post.SendWebRequest();

    if (post.result != UnityWebRequest.Result.Success) { /* log & bail */ yield break; }

    string jobId = ParseJobId(post.downloadHandler.text);   // parse { "job_id": "…" }
    yield return PollResult(jobId);
}
```

#### 8. `AgentMindBridge.cs` — add `PollResult` coroutine

```csharp
IEnumerator PollResult(string jobId)
{
    string pollUrl = resultBaseUrl + jobId;
    var wait = new WaitForSecondsRealtime(pollIntervalSeconds);   // ~1.5 s

    for (int attempt = 0; attempt < maxPollAttempts; attempt++)
    {
        yield return wait;

        var get = UnityWebRequest.Get(pollUrl);
        yield return get.SendWebRequest();

        if (get.result != UnityWebRequest.Result.Success) continue;

        var resp = JsonUtility.FromJson<PollResponse>(get.downloadHandler.text);
        if (resp.status == "done")
        {
            ParseAndStore(new ActionCallback {
                action = resp.action, x = resp.x, y = resp.y, z = resp.z, target = resp.target
            });
            yield break;
        }
        if (resp.status == "error")   // fail fast — no 30-second timeout wait
        {
            Debug.LogWarning($"[AgentMindBridge] job {jobId} failed on backend");
            yield break;
        }
    }
    Debug.LogWarning($"[AgentMindBridge] job {jobId} timed out after {maxPollAttempts} polls");
}
```

New inspector fields:
```
[Header("Polling")]
public string resultBaseUrl   = "http://localhost:8000/api/v1/agent/tick/result/";
public float  pollIntervalSeconds = 1.5f;
public int    maxPollAttempts     = 20;   // 30 s cap
```

New wire types:
```csharp
[Serializable] class TickAccepted { public string job_id; }
[Serializable] class PollResponse { public string status; public ActionCallback action; }
```

#### 9. `PeriodicMind.cs` — no logic changes needed

`TickLLM()` already uses `TryConsumeResponse(_pendingId, …)` and the latest-wins
pattern. The polling coroutine writes to `_latestIntent` via `ParseAndStore()` exactly
as the old `/action` listener did — PeriodicMind is unaffected.

---

## What Gets Deleted

| Location | What |
|---|---|
| `AgentMindBridge.cs` | `HttpListener`, background `Thread`, `StartListener`, `Listen`, `HandleHttp`, `Send(resp)`, `listenerPort` |
| `agent_tasks.py` | `asyncio.sleep(3)` stub |
| Any backend code | `POST localhost:8080/action` callback |

## What Gets Added

| Location | What |
|---|---|
| `agent_router.py` | `GET /agent/tick/result/{job_id}` endpoint |
| `agent_tasks.py` | Real `run_agent_job` function (LangGraph call + Redis write) |
| `AgentMindBridge.cs` | `PostAndPoll`, `PollResult` coroutines; `TickAccepted`, `PollResponse` types; 3 inspector fields |

---

## Migration / Testing Checklist

- [ ] Backend: `POST /agent/tick` returns `202 { job_id }` (curl test)
- [ ] Backend: Worker writes result to `job:{id}` in Redis (redis-cli `GET`)
- [ ] Backend: `GET /agent/tick/result/{job_id}` returns `pending` then `done` (curl test)
- [ ] Backend: TTL on Redis key confirmed (redis-cli `TTL`)
- [ ] Unity: `SendTick()` receives 202 and parses `job_id` (Editor log)
- [ ] Unity: `PollResult` coroutine fires, picks up `done` response (Editor log)
- [ ] Unity: `PeriodicMind.TryConsumeResponse()` returns the intent (Editor log)
- [ ] Unity: Cat executes the intent correctly in-scene
- [ ] No port 8080 listener started (verify no log line `Listening on http://localhost:8080`)
- [ ] Simulate backend latency > `mindTickInterval` — cat falls back gracefully (mood decay only)
- [ ] Build target (Mac/Windows standalone) — confirm polling works outside Editor
