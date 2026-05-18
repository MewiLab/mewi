// Pure transport adapter for the PeriodicMind ↔ LLM backend loop.
//
// Contract:
//   SendTick(creature,json) — POST + poll backend status. Fire and forget.
//                             Drops new ticks while one request is in flight.
//   TryConsume(out intent)— PeriodicMind polls each Think(); returns and clears.
//
// NOT responsible for:
//   • Building the snapshot (SnapshotManager owns that)
//   • Writing the blackboard (PeriodicMind is the sole Mind-slot writer)
//   • Deciding which intent to apply (PeriodicMind owns that)

using UnityEngine;
using System;
using System.Text;
using System.Threading;
using UnityEngine.Networking;
using Cysharp.Threading.Tasks;

public class AgentMindBridge : MonoBehaviour
{
    [Header("Backend")]
    public BackendConfig config;

    [Header("Debug")]
    public bool logTraffic = true;

    public int FailedTickCount => _failedTickCount;

    bool _warnedMoveDeprecated;
    int  _failedTickCount;
    bool _requestInFlight;

    public class LLMIntent
    {
        public string    intent;
        public Vector3   destination;
        public string    targetKey;
    }

    [Serializable] class ActionResponse
    {
        public bool   success;
        public string action = "";
        public string detail = "";
        public float  x, y, z;
        public string target = "";
    }

    [Serializable] class TickResponse
    {
        public string status = "";
        public ActionResponse action;
        public string reasoning = "";
        public int    buffered_count;
        public float  latency_ms;
    }

    [Serializable] class StatusResponse
    {
        public string creature_id = "";
        public string status = "";
        public bool   is_thinking;
    }

    [Serializable] class AgentResultResponse
    {
        public string creature_id = "";
        public string status = "";
        public string request_id = "";
        public string action = "";
        public string reasoning = "";
        public string detail = "";
        public float  x, y, z;
        public string target = "";
    }

    // Single writer: RunTickAsync after SwitchToMainThread.
    // Single reader: TryConsume on main thread.
    LLMIntent _latestIntent;

    CancellationTokenSource _cts;

    /// <summary>
    /// Send a pre-built snapshot JSON. If a request is already in flight, this
    /// tick is dropped; the next mind tick after completion will send fresh state.
    /// </summary>
    public void SendTick(string creatureId, string json)
    {
        if (string.IsNullOrWhiteSpace(creatureId))
        {
            Debug.LogWarning("[AgentMindBridge] SendTick called with empty creatureId");
            return;
        }

        if (string.IsNullOrEmpty(json))
        {
            Debug.LogWarning("[AgentMindBridge] SendTick called with empty json");
            return;
        }

        if (_requestInFlight)
        {
            if (logTraffic) Debug.Log("[AgentMindBridge] tick skipped: request already in flight");
            return;
        }

        _cts = new CancellationTokenSource();
        _requestInFlight = true;
        if (logTraffic) Debug.Log($"[AgentMindBridge] sending tick creature={creatureId} bytes={json.Length}");
        RunTickAsync(creatureId, json, _cts.Token).Forget();
    }

    public bool TryConsume(out LLMIntent intent)
    {
        intent = _latestIntent;
        _latestIntent = null;
        return intent != null;
    }

    void OnDisable()
    {
        _cts?.Cancel();
        _cts?.Dispose();
        _cts = null;
        _requestInFlight = false;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  ASYNC PIPELINE  (POST → status poll → optional parse)
    // ─────────────────────────────────────────────────────────────────────────

    async UniTaskVoid RunTickAsync(string creatureId, string json, CancellationToken ct)
    {
        try
        {
            TickResponse resp = await PostTickAsync(creatureId, json, ct);
            if (resp == null) return;

            if (resp.action != null && !string.IsNullOrWhiteSpace(resp.action.action))
            {
                // Some backend/test configurations return an immediate action.
                // The buffered production path normally returns only status.
                await UniTask.SwitchToMainThread(ct);
                ParseAndStore(resp.action.action, new Vector3(resp.action.x, resp.action.y, resp.action.z), resp.action.target);
                return;
            }

            if (resp.status == "processing")
            {
                var result = await PollStatusAsync(creatureId, ct);
                if (result == null || result.status != "done") return;

                await UniTask.SwitchToMainThread(ct);
                ParseAndStore(result.action, new Vector3(result.x, result.y, result.z), result.target);
            }
        }
        catch (OperationCanceledException)
        {
            if (logTraffic) Debug.Log("[AgentMindBridge] tick cancelled");
        }
        catch (Exception e)
        {
            MarkFailedTick();
            Debug.LogWarning($"[AgentMindBridge] tick failed: {e.Message}");
        }
        finally
        {
            _requestInFlight = false;
        }
    }

    async UniTask<TickResponse> PostTickAsync(string creatureId, string json, CancellationToken ct)
    {
        using var req = new UnityWebRequest(
            ApiRoutes.ResolveWithId(config, ApiRoutes.AgentTick, creatureId), "POST");
        req.uploadHandler   = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
        req.downloadHandler = new DownloadHandlerBuffer();
        req.SetRequestHeader("Content-Type", "application/json");
        config.ApplyAuth(req);
        if (config.requestTimeoutSeconds > 0)
            req.timeout = Mathf.CeilToInt(config.requestTimeoutSeconds);

        await req.SendWebRequest().ToUniTask(cancellationToken: ct);

        if (req.result != UnityWebRequest.Result.Success)
        {
            MarkFailedTick();
            Debug.LogWarning($"[AgentMindBridge] POST failed: HTTP {req.responseCode} {req.error} {req.downloadHandler.text}");
            return null;
        }

        TickResponse accepted;
        try
        {
            accepted = JsonUtility.FromJson<TickResponse>(req.downloadHandler.text);
        }
        catch (Exception e)
        {
            MarkFailedTick();
            Debug.LogWarning($"[AgentMindBridge] failed to parse tick response: {e.Message}");
            return null;
        }

        if (logTraffic)
        {
            string status = accepted != null ? accepted.status : "";
            int buffered = accepted != null ? accepted.buffered_count : 0;
            float latency = accepted != null ? accepted.latency_ms : 0f;
            Debug.Log($"[AgentMindBridge] tick accepted status={status} buffered={buffered} latency_ms={latency:F1}");
        }
        return accepted;
    }

    async UniTask<AgentResultResponse> PollStatusAsync(string creatureId, CancellationToken ct)
    {
        string url = ApiRoutes.ResolveWithId(config, ApiRoutes.AgentStatus, creatureId);
        int    intervalMs = Mathf.Max(50, Mathf.RoundToInt(config.pollIntervalSeconds * 1000f));

        for (int i = 0; i < config.maxPollAttempts; i++)
        {
            await UniTask.Delay(intervalMs, DelayType.Realtime, cancellationToken: ct);

            using var get = UnityWebRequest.Get(url);
            config.ApplyAuth(get);
            if (config.requestTimeoutSeconds > 0)
                get.timeout = Mathf.CeilToInt(config.requestTimeoutSeconds);
            await get.SendWebRequest().ToUniTask(cancellationToken: ct);

            if (get.result != UnityWebRequest.Result.Success) continue;

            StatusResponse resp;
            try
            {
                resp = JsonUtility.FromJson<StatusResponse>(get.downloadHandler.text);
            }
            catch (Exception e)
            {
                MarkFailedTick();
                Debug.LogWarning($"[AgentMindBridge] failed to parse status response: {e.Message}");
                return null;
            }

            if (!resp.is_thinking)
            {
                if (logTraffic) Debug.Log($"[AgentMindBridge] creature {creatureId} status={resp.status}");
                var result = await FetchResultAsync(creatureId, ct);
                if (result != null && result.status != "pending")
                    return result;
            }
        }

        MarkFailedTick();
        Debug.LogWarning($"[AgentMindBridge] creature {creatureId} still thinking after {config.maxPollAttempts} polls");
        return null;
    }

    async UniTask<AgentResultResponse> FetchResultAsync(string creatureId, CancellationToken ct)
    {
        string url = ApiRoutes.ResolveWithId(config, ApiRoutes.AgentResult, creatureId) + "?consume=true";
        using var get = UnityWebRequest.Get(url);
        config.ApplyAuth(get);
        if (config.requestTimeoutSeconds > 0)
            get.timeout = Mathf.CeilToInt(config.requestTimeoutSeconds);

        await get.SendWebRequest().ToUniTask(cancellationToken: ct);

        if (get.result != UnityWebRequest.Result.Success)
        {
            MarkFailedTick();
            Debug.LogWarning($"[AgentMindBridge] result fetch failed: HTTP {get.responseCode} {get.error} {get.downloadHandler.text}");
            return null;
        }

        try
        {
            var result = JsonUtility.FromJson<AgentResultResponse>(get.downloadHandler.text);
            if (logTraffic) Debug.Log($"[AgentMindBridge] result status={result.status} action={result.action}");
            return result;
        }
        catch (Exception e)
        {
            MarkFailedTick();
            Debug.LogWarning($"[AgentMindBridge] failed to parse result response: {e.Message}");
            return null;
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  MAIN-THREAD HELPERS
    // ─────────────────────────────────────────────────────────────────────────

    void ParseAndStore(string rawAction, Vector3 destination, string target)
    {
        if (string.IsNullOrWhiteSpace(rawAction)) return;

        string action = rawAction.Trim().ToLowerInvariant();
        if (action == "wait") return;
        if (action == "stop") action = "stop_moving";
        if (action == "move")
        {
            if (!_warnedMoveDeprecated)
            {
                _warnedMoveDeprecated = true;
                Debug.LogWarning("[AgentMindBridge] backend emitted deprecated action 'move'; normalizing to 'go_to'.");
            }
            action = "go_to";
        }

        _latestIntent = new LLMIntent
        {
            intent      = action,
            destination = destination,
            targetKey   = target ?? "",
        };
    }

    void MarkFailedTick() => Interlocked.Increment(ref _failedTickCount);
}
