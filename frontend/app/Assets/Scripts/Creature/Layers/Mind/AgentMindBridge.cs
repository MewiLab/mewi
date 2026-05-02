// AgentMindBridge.cs  (Creature/Layers/Mind/)
//
// Pure transport adapter for the PeriodicMind ↔ LLM backend loop.
//
// Responsibilities (and ONLY these):
//   Outbound — SendTick(board)
//              Asks SnapshotManager to build the wire JSON, then POSTs it.
//              Returns a requestId the caller uses to match the response.
//              Does NOT know about channels, mood, spatial, etc.
//
//   Inbound  — PostAndPoll coroutine POSTs the tick and receives a job_id (202).
//              PollResult coroutine polls GET /agent/tick/result/{job_id} until
//              the backend writes a "done" or "error" result to Redis.
//              Parses the response into an LLMIntent and stores it.
//
//   Query    — TryConsumeResponse(requestId, out LLMIntent)
//              PeriodicMind polls this each Think() cycle.
//              Returns true and clears the intent on match.
//
// NOT responsible for:
//   • Building the snapshot (SnapshotManager)
//   • Writing the blackboard (PeriodicMind is the sole Mind-slot writer)
//   • Deciding which intent to apply (PeriodicMind owns that)
//
// requestId matching uses "latest wins" for v1.
// TODO: tighten to strict ID match once the backend echoes requestId.

using UnityEngine;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine.Networking;

public class AgentMindBridge : MonoBehaviour
{
    // ─────────────────────────────────────────────────────────────────────────
    //  INSPECTOR
    // ─────────────────────────────────────────────────────────────────────────

    [Header("Backend")]
    public string backendUrl    = "http://localhost:8000/api/v1/agent/tick";
    public string resultBaseUrl = "http://localhost:8000/api/v1/agent/tick/result/";

    [Header("Polling")]
    public float pollIntervalSeconds = 1.5f;
    public int   maxPollAttempts     = 20;    // ~30 s cap

    [Header("Debug")]
    public bool logTraffic = true;

    [Header("Named Targets (resolved for 'follow' intent)")]
    public List<NamedTarget> namedTargets = new List<NamedTarget>();

    [System.Serializable]
    public class NamedTarget
    {
        public string    key;
        public Transform target;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  OUTPUT TYPE — produced here, consumed by PeriodicMind
    // ─────────────────────────────────────────────────────────────────────────

    public class LLMIntent
    {
        public string    intent;
        public Vector3   destination;
        public Transform target;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  INBOUND WIRE FORMATS
    // ─────────────────────────────────────────────────────────────────────────

    [Serializable] class TickAccepted { public string job_id; }

    // Flat layout — mirrors the ActionCallback the backend used to POST directly.
    // "status" is added; action/x/y/z/target are the same fields.
    [Serializable] class PollResponse
    {
        public string status = "";
        public string action = "";
        public float  x, y, z;
        public string target    = "";
        public string requestId = "";
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  PRIVATE STATE
    // ─────────────────────────────────────────────────────────────────────────

    Dictionary<string, Transform> _targetMap;
    SnapshotManager               _snapshot;

    readonly object _lock = new object();

    LLMIntent _latestIntent = null;
    string    _pendingTargetKey = "";

    // ─────────────────────────────────────────────────────────────────────────
    //  INIT
    // ─────────────────────────────────────────────────────────────────────────

    public void Init(SnapshotManager snapshot)
    {
        _snapshot  = snapshot;
        _targetMap = new Dictionary<string, Transform>(StringComparer.OrdinalIgnoreCase);
        foreach (var nt in namedTargets)
            if (nt.target != null)
                _targetMap[nt.key] = nt.target;

        if (_snapshot == null)
            Debug.LogError("[AgentMindBridge] No SnapshotManager — SendTick will fail. Add SnapshotManager to the cat root.");
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  TICK  (called by CreatureController.Update — main thread)
    // ─────────────────────────────────────────────────────────────────────────

    public void Tick() => ResolvePendingTarget();

    // ─────────────────────────────────────────────────────────────────────────
    //  PUBLIC API — called by PeriodicMind
    // ─────────────────────────────────────────────────────────────────────────

    public string SendTick(CreatureBlackboard board)
    {
        if (_snapshot == null)
        {
            Debug.LogError("[AgentMindBridge] SendTick aborted — SnapshotManager not wired.");
            return null;
        }

        string id   = Guid.NewGuid().ToString("N")[..8];
        string json = _snapshot.BuildJson(id);

        if (logTraffic) Debug.Log($"[AgentMindBridge] SendTick id={id}");
        StartCoroutine(PostAndPoll(json));
        return id;
    }

    public bool TryConsumeResponse(string requestId, out LLMIntent intent)
    {
        lock (_lock)
        {
            if (_latestIntent == null) { intent = null; return false; }

            intent        = _latestIntent;
            _latestIntent = null;
            return true;
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  OUTBOUND + POLL COROUTINES
    // ─────────────────────────────────────────────────────────────────────────

    IEnumerator PostAndPoll(string json)
    {
        var req = new UnityWebRequest(backendUrl, "POST");
        req.uploadHandler   = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
        req.downloadHandler = new DownloadHandlerBuffer();
        req.SetRequestHeader("Content-Type", "application/json");
        yield return req.SendWebRequest();

        if (req.result != UnityWebRequest.Result.Success)
        {
            Debug.LogWarning($"[AgentMindBridge] SendTick failed: {req.error}");
            yield break;
        }

        var accepted = JsonUtility.FromJson<TickAccepted>(req.downloadHandler.text);
        if (string.IsNullOrEmpty(accepted?.job_id))
        {
            Debug.LogWarning("[AgentMindBridge] 202 response missing job_id");
            yield break;
        }

        if (logTraffic) Debug.Log($"[AgentMindBridge] job_id={accepted.job_id}");
        yield return PollResult(accepted.job_id);
    }

    IEnumerator PollResult(string jobId)
    {
        string pollUrl = resultBaseUrl + jobId;
        var    wait    = new WaitForSecondsRealtime(pollIntervalSeconds);

        for (int attempt = 0; attempt < maxPollAttempts; attempt++)
        {
            yield return wait;

            var get = UnityWebRequest.Get(pollUrl);
            yield return get.SendWebRequest();

            if (get.result != UnityWebRequest.Result.Success) continue;

            var resp = JsonUtility.FromJson<PollResponse>(get.downloadHandler.text);

            if (resp.status == "done")
            {
                if (logTraffic) Debug.Log($"[AgentMindBridge] job {jobId} done: {resp.action}");
                ParseAndStore(resp);
                yield break;
            }

            if (resp.status == "error")
            {
                Debug.LogWarning($"[AgentMindBridge] job {jobId} failed on backend");
                yield break;
            }
        }

        Debug.LogWarning($"[AgentMindBridge] job {jobId} timed out after {maxPollAttempts} polls");
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  RESPONSE PARSING  (main thread — Transform lookup safe here)
    // ─────────────────────────────────────────────────────────────────────────

    void ParseAndStore(PollResponse resp)
    {
        if (string.IsNullOrEmpty(resp.action) || resp.action == "wait") return;

        lock (_lock)
        {
            string action = resp.action;
            if (action == "stop")  action = "idle";
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
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  MAIN-THREAD HELPERS
    // ─────────────────────────────────────────────────────────────────────────

    // Called every frame from Tick() — resolves a pending named target to a
    // Transform, then applies it to the intent (position for go_to, target for follow).
    // GameObject.Find is safe here because we're on the main thread.
    void ResolvePendingTarget()
    {
        string pendingKey;
        string pendingIntent;

        lock (_lock)
        {
            if (_latestIntent == null || string.IsNullOrEmpty(_pendingTargetKey)) return;
            pendingKey    = _pendingTargetKey;
            pendingIntent = _latestIntent.intent;
        }

        // Resolve: inspector list first, then scene search by name.
        if (!_targetMap.TryGetValue(pendingKey, out Transform resolved))
        {
            var go = GameObject.Find(pendingKey);
            if (go != null)
            {
                resolved = go.transform;
                _targetMap[pendingKey] = resolved;   // cache for next time
            }
        }

        lock (_lock)
        {
            if (_latestIntent == null || _pendingTargetKey != pendingKey) return;

            if (resolved != null)
            {
                if (pendingIntent == "go_to")
                    _latestIntent.destination = resolved.position;
                else
                    _latestIntent.target = resolved;
            }
            else
            {
                Debug.LogWarning($"[AgentMindBridge] target '{pendingKey}' not found in scene — falling back to wander");
                if (pendingIntent == "go_to")
                    _latestIntent.intent = "wander";
            }

            _pendingTargetKey = "";
        }
    }
}
