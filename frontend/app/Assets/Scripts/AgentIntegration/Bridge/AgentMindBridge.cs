// AgentMindBridge.cs  (AgentIntegration/Bridge/)
//
// Pure transport adapter for the PeriodicMind ↔ LLM backend loop.
//
// Contract:
//   SendTick(json)        — POST + poll, store latest LLMIntent. Fire and forget.
//                           Cancels any in-flight request (latest-wins backpressure).
//   TryConsume(out intent)— PeriodicMind polls each Think(); returns and clears.
//   Tick()                — main-thread named-target resolution.
//
// NOT responsible for:
//   • Building the snapshot (SnapshotManager owns that)
//   • Writing the blackboard (PeriodicMind is the sole Mind-slot writer)
//   • Deciding which intent to apply (PeriodicMind owns that)

using UnityEngine;
using System;
using System.Collections.Generic;
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

    [Header("Named Targets (resolved for 'follow' intent)")]
    public List<NamedTarget> namedTargets = new List<NamedTarget>();

    [Serializable]
    public class NamedTarget
    {
        public string    key;
        public Transform target;
    }

    public class LLMIntent
    {
        public string    intent;
        public Vector3   destination;
        public Transform target;
    }

    [Serializable] class TickAccepted { public string job_id; }

    [Serializable] class PollResponse
    {
        public string status = "";
        public string action = "";
        public float  x, y, z;
        public string target = "";
    }

    Dictionary<string, Transform> _targetMap;

    // Single writer: RunTickAsync after SwitchToMainThread.
    // Single reader: TryConsume / ResolvePendingTarget on main thread.
    LLMIntent _latestIntent;
    string    _pendingTargetKey;

    CancellationTokenSource _cts;

    public void Init()
    {
        _targetMap = new Dictionary<string, Transform>(StringComparer.OrdinalIgnoreCase);
        foreach (var nt in namedTargets)
            if (nt.target != null) _targetMap[nt.key] = nt.target;
    }

    /// <summary>Main-thread per-frame work: resolve any pending named target.</summary>
    public void Tick() => ResolvePendingTarget();

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
            Debug.LogWarning($"[AgentMindBridge] POST failed: {req.error}");
            return null;
        }

        var accepted = JsonUtility.FromJson<TickAccepted>(req.downloadHandler.text);
        if (string.IsNullOrEmpty(accepted?.job_id))
        {
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

            var resp = JsonUtility.FromJson<PollResponse>(get.downloadHandler.text);
            if (resp.status == "done")
            {
                if (logTraffic) Debug.Log($"[AgentMindBridge] job {jobId} done: {resp.action}");
                return resp;
            }
            if (resp.status == "error")
            {
                Debug.LogWarning($"[AgentMindBridge] job {jobId} failed on backend");
                return null;
            }
        }

        Debug.LogWarning($"[AgentMindBridge] job {jobId} timed out after {config.maxPollAttempts} polls");
        return null;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  MAIN-THREAD HELPERS
    // ─────────────────────────────────────────────────────────────────────────

    void ParseAndStore(PollResponse resp)
    {
        if (string.IsNullOrEmpty(resp.action) || resp.action == "wait") return;

        string action = resp.action;
        if (action == "stop") action = "idle";
        if (action == "move")
        {
            var dest = new Vector3(resp.x, resp.y, resp.z);
            action = (dest != Vector3.zero) ? "go_to" : "wander";
        }

        _latestIntent = new LLMIntent
        {
            intent      = action,
            destination = new Vector3(resp.x, resp.y, resp.z),
            target      = null,
        };
        _pendingTargetKey = resp.target ?? "";
    }

    // Resolve a named target string to a Transform. GameObject.Find is safe
    // here because Tick() runs on the main thread.
    void ResolvePendingTarget()
    {
        if (_latestIntent == null || string.IsNullOrEmpty(_pendingTargetKey)) return;

        string key = _pendingTargetKey;

        if (!_targetMap.TryGetValue(key, out Transform resolved))
        {
            var go = GameObject.Find(key);
            if (go != null)
            {
                resolved = go.transform;
                _targetMap[key] = resolved;   // cache
            }
        }

        if (resolved != null)
        {
            if (_latestIntent.intent == "go_to") _latestIntent.destination = resolved.position;
            else                                  _latestIntent.target      = resolved;
        }
        else
        {
            Debug.LogWarning($"[AgentMindBridge] target '{key}' not found — falling back to wander");
            if (_latestIntent.intent == "go_to") _latestIntent.intent = "wander";
        }

        _pendingTargetKey = "";
    }
}
