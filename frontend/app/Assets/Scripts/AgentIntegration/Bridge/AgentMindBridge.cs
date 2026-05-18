// Pure transport adapter for the PeriodicMind ↔ LLM backend loop.
//
// Contract:
//   SendTick(creature,json) — POST + poll backend job. Fire and forget.
//                             Drops new ticks while one request is in flight.
//   TryConsume(out intent)— PeriodicMind polls each Think(); returns and clears.
//
// Flow (matches backend agent_router):
//   1. POST /api/v1/agent/tick/{creature_id} -> 202 with job_id (status "queued")
//   2. GET  /api/v1/agent/tick/jobs/{job_id} until status == "done" | "error"
//   3. Parse action from job.action and stash into _latestIntent
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

    [Serializable] class TickSubmitResponse
    {
        public string job_id     = "";
        public string creature_id = "";
        public string request_id = "";
        public string status     = "";
        public int    queue_depth;
    }

    [Serializable] class ActionPayload
    {
        public string status = "";
        public string action = "";
        public float  x, y, z;
        public string target = "";
    }

    [Serializable] class TickJobResponse
    {
        public string        job_id      = "";
        public string        creature_id = "";
        public string        request_id  = "";
        public string        status      = "";
        public int           tick;
        public ActionPayload action;
        public string        reasoning   = "";
        public string        error       = "";
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
    //  ASYNC PIPELINE  (POST → job poll → parse)
    // ─────────────────────────────────────────────────────────────────────────

    async UniTaskVoid RunTickAsync(string creatureId, string json, CancellationToken ct)
    {
        try
        {
            string jobId = await PostTickAsync(creatureId, json, ct);
            if (string.IsNullOrEmpty(jobId)) return;

            TickJobResponse job = await PollJobAsync(creatureId, jobId, ct);
            if (job == null) return;

            if (job.status == "error")
            {
                MarkFailedTick();
                Debug.LogWarning($"[AgentMindBridge] job {jobId} errored: {job.error}");
                return;
            }

            if (job.status != "done" || job.action == null)
            {
                if (logTraffic) Debug.Log($"[AgentMindBridge] job {jobId} ended status={job.status} (no action)");
                return;
            }

            if (logTraffic)
                Debug.Log($"[AgentMindBridge] job {jobId} DONE action={job.action.action} pos=({job.action.x:F2},{job.action.y:F2},{job.action.z:F2}) target='{job.action.target}' reasoning=\"{job.reasoning}\"");

            await UniTask.SwitchToMainThread(ct);
            ParseAndStore(
                job.action.action,
                new Vector3(job.action.x, job.action.y, job.action.z),
                job.action.target);
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

    async UniTask<string> PostTickAsync(string creatureId, string json, CancellationToken ct)
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

        TickSubmitResponse accepted;
        try
        {
            accepted = JsonUtility.FromJson<TickSubmitResponse>(req.downloadHandler.text);
        }
        catch (Exception e)
        {
            MarkFailedTick();
            Debug.LogWarning($"[AgentMindBridge] failed to parse submit response: {e.Message}");
            return null;
        }

        if (accepted == null || string.IsNullOrEmpty(accepted.job_id))
        {
            MarkFailedTick();
            Debug.LogWarning($"[AgentMindBridge] submit response missing job_id: {req.downloadHandler.text}");
            return null;
        }

        if (logTraffic)
            Debug.Log($"[AgentMindBridge] tick accepted job={accepted.job_id} status={accepted.status} queue_depth={accepted.queue_depth}");

        return accepted.job_id;
    }

    async UniTask<TickJobResponse> PollJobAsync(string creatureId, string jobId, CancellationToken ct)
    {
        string url        = ApiRoutes.ResolveWithId(config, ApiRoutes.AgentTickJob, jobId);
        int    intervalMs = Mathf.Max(50, Mathf.RoundToInt(config.pollIntervalSeconds * 1000f));

        for (int i = 0; i < config.maxPollAttempts; i++)
        {
            await UniTask.Delay(intervalMs, DelayType.Realtime, cancellationToken: ct);

            using var get = UnityWebRequest.Get(url);
            config.ApplyAuth(get);
            if (config.requestTimeoutSeconds > 0)
                get.timeout = Mathf.CeilToInt(config.requestTimeoutSeconds);

            await get.SendWebRequest().ToUniTask(cancellationToken: ct);

            if (get.result != UnityWebRequest.Result.Success)
            {
                // 404 means the job key expired or never persisted — bail.
                if (get.responseCode == 404)
                {
                    MarkFailedTick();
                    Debug.LogWarning($"[AgentMindBridge] job {jobId} not found (404); aborting poll");
                    return null;
                }
                if (logTraffic)
                    Debug.Log($"[AgentMindBridge] poll attempt {i + 1} transient failure: HTTP {get.responseCode} {get.error}");
                continue;
            }

            TickJobResponse job;
            try
            {
                job = JsonUtility.FromJson<TickJobResponse>(get.downloadHandler.text);
            }
            catch (Exception e)
            {
                MarkFailedTick();
                Debug.LogWarning($"[AgentMindBridge] failed to parse job response: {e.Message}");
                return null;
            }

            if (job == null) continue;

            if (job.status == "done" || job.status == "error")
            {
                if (logTraffic)
                    Debug.Log($"[AgentMindBridge] job {jobId} finished status={job.status} creature={creatureId}");
                return job;
            }

            if (logTraffic)
                Debug.Log($"[AgentMindBridge] job {jobId} status={job.status} (attempt {i + 1}/{config.maxPollAttempts})");
        }

        MarkFailedTick();
        Debug.LogWarning($"[AgentMindBridge] job {jobId} still pending after {config.maxPollAttempts} polls");
        return null;
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
