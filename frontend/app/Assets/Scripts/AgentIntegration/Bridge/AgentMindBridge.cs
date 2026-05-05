// AgentMindBridge.cs  (AgentIntegration/Bridge/)
//
// Pure transport adapter for the PeriodicMind ↔ LLM backend loop.
//
// Contract:
//   SendTick(json)        — POST + poll, store latest LLMIntent. Fire and forget.
//                           Cancels any in-flight request (latest-wins backpressure).
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

    public class LLMIntent
    {
        public string    intent;
        public Vector3   destination;
        public string    targetKey;
    }

    [Serializable] class TickAccepted { public string job_id; }

    [Serializable] class PollResponse
    {
        public string status = "";
        public string action = "";
        public float  x, y, z;
        public string target = "";
    }

    // Single writer: RunTickAsync after SwitchToMainThread.
    // Single reader: TryConsume on main thread.
    LLMIntent _latestIntent;

    CancellationTokenSource _cts;

    /// <summary>
    /// Send a pre-built snapshot JSON. Cancels any in-flight request first
    /// so only the latest tick survives.
    /// </summary>
    public void SendTick(string json)
    {
        if (string.IsNullOrEmpty(json))
        {
            Debug.LogWarning("[AgentMindBridge] SendTick called with empty json");
            return;
        }

        _cts?.Cancel();
        _cts = new CancellationTokenSource();
        RunTickAsync(json, _cts.Token).Forget();
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
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  ASYNC PIPELINE  (POST → poll → parse)
    // ─────────────────────────────────────────────────────────────────────────

    async UniTaskVoid RunTickAsync(string json, CancellationToken ct)
    {
        try
        {
            string jobId = await PostTickAsync(json, ct);
            if (string.IsNullOrEmpty(jobId)) return;

            var resp = await PollResultAsync(jobId, ct);
            if (resp == null) return;

            // We may resume on a worker thread after I/O — marshal back before
            // touching shared state.
            await UniTask.SwitchToMainThread(ct);
            ParseAndStore(resp);
        }
        catch (OperationCanceledException) { /* superseded by newer tick */ }
        catch (Exception e)
        {
            MarkFailedTick();
            Debug.LogWarning($"[AgentMindBridge] tick failed: {e.Message}");
        }
    }

    async UniTask<string> PostTickAsync(string json, CancellationToken ct)
    {
        using var req = new UnityWebRequest(
            ApiRoutes.Resolve(config, ApiRoutes.AgentTick), "POST");
        req.uploadHandler   = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
        req.downloadHandler = new DownloadHandlerBuffer();
        req.SetRequestHeader("Content-Type", "application/json");
        if (config.requestTimeoutSeconds > 0)
            req.timeout = Mathf.CeilToInt(config.requestTimeoutSeconds);

        await req.SendWebRequest().ToUniTask(cancellationToken: ct);

        if (req.result != UnityWebRequest.Result.Success)
        {
            MarkFailedTick();
            Debug.LogWarning($"[AgentMindBridge] POST failed: {req.error}");
            return null;
        }

        TickAccepted accepted;
        try
        {
            accepted = JsonUtility.FromJson<TickAccepted>(req.downloadHandler.text);
        }
        catch (Exception e)
        {
            MarkFailedTick();
            Debug.LogWarning($"[AgentMindBridge] failed to parse tick response: {e.Message}");
            return null;
        }

        if (string.IsNullOrEmpty(accepted?.job_id))
        {
            MarkFailedTick();
            Debug.LogWarning("[AgentMindBridge] 202 response missing job_id");
            return null;
        }

        if (logTraffic) Debug.Log($"[AgentMindBridge] job_id={accepted.job_id}");
        return accepted.job_id;
    }

    async UniTask<PollResponse> PollResultAsync(string jobId, CancellationToken ct)
    {
        string url = ApiRoutes.Resolve(config, ApiRoutes.AgentTickResult) + jobId;
        int    intervalMs = Mathf.Max(50, Mathf.RoundToInt(config.pollIntervalSeconds * 1000f));

        for (int i = 0; i < config.maxPollAttempts; i++)
        {
            await UniTask.Delay(intervalMs, DelayType.Realtime, cancellationToken: ct);

            using var get = UnityWebRequest.Get(url);
            await get.SendWebRequest().ToUniTask(cancellationToken: ct);

            if (get.result != UnityWebRequest.Result.Success) continue;

            PollResponse resp;
            try
            {
                resp = JsonUtility.FromJson<PollResponse>(get.downloadHandler.text);
            }
            catch (Exception e)
            {
                MarkFailedTick();
                Debug.LogWarning($"[AgentMindBridge] failed to parse poll response: {e.Message}");
                return null;
            }

            if (resp.status == "done")
            {
                if (logTraffic) Debug.Log($"[AgentMindBridge] job {jobId} done: {resp.action}");
                return resp;
            }
            if (resp.status == "error")
            {
                MarkFailedTick();
                Debug.LogWarning($"[AgentMindBridge] job {jobId} failed on backend");
                return null;
            }
        }

        MarkFailedTick();
        Debug.LogWarning($"[AgentMindBridge] job {jobId} timed out after {config.maxPollAttempts} polls");
        return null;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  MAIN-THREAD HELPERS
    // ─────────────────────────────────────────────────────────────────────────

    void ParseAndStore(PollResponse resp)
    {
        if (string.IsNullOrEmpty(resp.action) || resp.action == "wait") return;

        string action = resp.action.Trim().ToLowerInvariant();
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
            destination = new Vector3(resp.x, resp.y, resp.z),
            targetKey   = resp.target ?? "",
        };
    }

    void MarkFailedTick() => Interlocked.Increment(ref _failedTickCount);
}
