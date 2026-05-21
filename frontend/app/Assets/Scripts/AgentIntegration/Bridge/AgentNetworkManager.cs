// Pure transport adapter for the PeriodicMind ↔ LLM backend loop.
//
// Contract:
//   SendTick(creature,snapshot,planReport) — WebSocket backend tick envelope.
//                                              Drops new ticks while one request is in flight.
//   TryConsumePlan(out plan) — PeriodicMind polls each Think(); returns and clears.
//
// Flow (matches backend agent_router websocket):
//   1. Lazily open /api/v1/agent/ws/{creature_id}
//   2. Send one nested tick envelope over the socket
//   3. Receive final plan response, parse actions, stash into _latestPlan
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
using NativeWebSocket;
using Cysharp.Threading.Tasks;

public class AgentNetworkManager : MonoBehaviour
{
    [Header("Backend")]
    public BackendConfig config;

    [Header("Debug")]
    public bool logTraffic = true;

    public int FailedTickCount => _failedTickCount;
    public bool RequestInFlight => _requestInFlight;

    bool _warnedMoveDeprecated;
    int  _failedTickCount;
    bool _requestInFlight;
    bool _isConnecting;
    float _requestStartedAt;
    string _connectedCreatureId = "";
    WebSocket _websocket;
    WebSocket _intentionalCloseSocket;

    public class LLMIntent
    {
        public string    intent;
        public Vector3   destination;
        public string    targetKey;
        public string    reason;
    }

    public class LLMPlan
    {
        public string      jobId;
        public string      requestId;
        public string      reasoning;
        public LLMIntent[] steps;
    }

    [Serializable] class ActionPayload
    {
        public string status = "";
        public string action = "";
        public string target = "";
    }

    [Serializable] class PlanStepPayload
    {
        public string action = "";
        public string target = "";
        public string reason = "";
    }

    [Serializable] class AgentPlanResponse
    {
        public string        job_id      = "";
        public string        creature_id = "";
        public string        request_id  = "";
        public string        status      = "";
        public int           tick;
        public ActionPayload action;
        public PlanStepPayload[] actions;
        public PlanStepPayload[] plan_steps;
        public string        reasoning   = "";
        public string        error       = "";
    }

    [Serializable] class TickEnvelope
    {
        public string type = "tick";
        public string agent_id = "";
        public string requestId = "";
        public PlanExecutionReport report;
        public SnapshotPayload snapshot;
    }

    // Single writer: HandleServerMessage on the Unity message queue.
    // Single reader: TryConsumePlan on main thread.
    LLMPlan _latestPlan;

    CancellationTokenSource _cts;

    /// <summary>
    /// Send a snapshot plus the previous plan result as one ordered websocket
    /// envelope. If a request is already in flight, this tick is dropped; the
    /// next mind tick after completion will send fresh state.
    /// </summary>
    public bool SendTick(string creatureId, SnapshotPayload snapshot, PlanExecutionReport planReport = null)
    {
        if (snapshot == null)
        {
            Debug.LogWarning("[AgentNetworkManager] SendTick called with null snapshot");
            return false;
        }

        var envelope = new TickEnvelope
        {
            type      = "tick",
            agent_id  = creatureId,
            requestId = snapshot.requestId ?? "",
            report    = planReport,
            snapshot  = snapshot,
        };

        return SendTickJson(creatureId, JsonUtility.ToJson(envelope));
    }

    public bool SendTick(string creatureId, string json)
    {
        return SendTickJson(creatureId, json);
    }

    bool SendTickJson(string creatureId, string json)
    {
        if (string.IsNullOrWhiteSpace(creatureId))
        {
            Debug.LogWarning("[AgentNetworkManager] SendTick called with empty creatureId");
            return false;
        }

        if (string.IsNullOrEmpty(json))
        {
            Debug.LogWarning("[AgentNetworkManager] SendTick called with empty json");
            return false;
        }

        if (_requestInFlight)
        {
            if (logTraffic) Debug.Log("[AgentNetworkManager] tick skipped: request already in flight");
            return false;
        }

        _cts?.Dispose();
        _cts = new CancellationTokenSource();
        _requestInFlight = true;
        _requestStartedAt = Time.realtimeSinceStartup;
        if (logTraffic) Debug.Log($"[AgentNetworkManager] sending websocket tick creature={creatureId} bytes={json.Length}");
        SendTickAsync(creatureId, json, _cts.Token).Forget();
        return true;
    }

    public bool TryConsume(out LLMIntent intent)
    {
        intent = null;
        if (!TryConsumePlan(out var plan) || plan.steps == null || plan.steps.Length == 0)
            return false;

        intent = plan.steps[0];
        return intent != null;
    }

    public bool TryConsumePlan(out LLMPlan plan)
    {
        plan = _latestPlan;
        _latestPlan = null;
        return plan != null && plan.steps != null && plan.steps.Length > 0;
    }

    void Update()
    {
#if !UNITY_WEBGL || UNITY_EDITOR
        _websocket?.DispatchMessageQueue();
#endif
        CheckRequestTimeout();
    }

    void OnDisable()
    {
        _cts?.Cancel();
        _cts?.Dispose();
        _cts = null;
        _requestInFlight = false;
        _isConnecting = false;
        CloseSocketAsync().Forget();
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  ASYNC PIPELINE  (connect → send → websocket response)
    // ─────────────────────────────────────────────────────────────────────────

    async UniTaskVoid SendTickAsync(string creatureId, string json, CancellationToken ct)
    {
        try
        {
            if (!await EnsureConnectedAsync(creatureId, ct))
            {
                FailInFlight("websocket connection failed");
                return;
            }

            await _websocket.SendText(json);
            if (logTraffic) Debug.Log("[AgentNetworkManager] websocket tick sent");
        }
        catch (OperationCanceledException)
        {
            if (logTraffic) Debug.Log("[AgentNetworkManager] websocket tick cancelled");
            _requestInFlight = false;
        }
        catch (Exception e)
        {
            FailInFlight($"websocket tick failed: {e.Message}");
        }
    }

    async UniTask<bool> EnsureConnectedAsync(string creatureId, CancellationToken ct)
    {
        if (config == null)
        {
            Debug.LogError("[AgentNetworkManager] missing BackendConfig");
            return false;
        }

        if (_websocket != null &&
            _websocket.State == WebSocketState.Open &&
            string.Equals(_connectedCreatureId, creatureId, StringComparison.Ordinal))
        {
            return true;
        }

        if (_isConnecting)
        {
            await UniTask.WaitUntil(() => !_isConnecting, cancellationToken: ct);
            return _websocket != null && _websocket.State == WebSocketState.Open;
        }

        await CloseSocketAsync();

        string url = ApiRoutes.ResolveWebSocketWithId(config, ApiRoutes.AgentTickWs, creatureId);
        var headers = config.BuildAuthHeaders();
        _websocket = headers.Count > 0 ? new WebSocket(url, headers) : new WebSocket(url);
        _connectedCreatureId = creatureId;
        BindWebSocketHandlers(_websocket);

        _isConnecting = true;
        if (logTraffic) Debug.Log($"[AgentNetworkManager] connecting websocket {url}");

        try
        {
            WebSocket socket = _websocket;
            ConnectSocketAsync(socket).Forget();

            float connectTimeout = Mathf.Max(1f, config.requestTimeoutSeconds);
            float deadline = Time.realtimeSinceStartup + connectTimeout;
            while (_websocket == socket &&
                   socket.State != WebSocketState.Open &&
                   Time.realtimeSinceStartup < deadline)
            {
                ct.ThrowIfCancellationRequested();
                await UniTask.Yield(PlayerLoopTiming.Update, ct);
            }

            bool connected = _websocket == socket && socket.State == WebSocketState.Open;
            if (!connected)
                Debug.LogWarning($"[AgentNetworkManager] websocket connect ended state={(socket != null ? socket.State.ToString() : "null")}");
            return connected;
        }
        catch (Exception e)
        {
            Debug.LogWarning($"[AgentNetworkManager] websocket connect failed: {e.Message}");
            return false;
        }
        finally
        {
            _isConnecting = false;
        }
    }

    async UniTaskVoid ConnectSocketAsync(WebSocket socket)
    {
        try
        {
            await socket.Connect();
        }
        catch (Exception e)
        {
            if (_websocket == socket)
                FailInFlight($"websocket connect failed: {e.Message}");
        }
    }

    void BindWebSocketHandlers(WebSocket socket)
    {
        socket.OnOpen += () =>
        {
            if (logTraffic) Debug.Log("[AgentNetworkManager] websocket connected");
        };

        socket.OnError += error =>
        {
            FailInFlight($"websocket error: {error}");
        };

        socket.OnClose += code =>
        {
            bool intentionalClose = _intentionalCloseSocket == socket;
            if (intentionalClose)
                _intentionalCloseSocket = null;

            if (logTraffic) Debug.LogWarning($"[AgentNetworkManager] websocket closed code={code}");
            if (_websocket == socket)
            {
                _websocket = null;
                _connectedCreatureId = "";
            }
            _isConnecting = false;
            if (!intentionalClose)
                FailInFlight($"websocket closed before response (code={code})");
        };

        socket.OnMessage += bytes =>
        {
            string message = Encoding.UTF8.GetString(bytes);
            HandleServerMessage(message);
        };
    }

    void HandleServerMessage(string message)
    {
        AgentPlanResponse job;
        try
        {
            job = JsonUtility.FromJson<AgentPlanResponse>(message);
        }
        catch (Exception e)
        {
            FailInFlight($"failed to parse websocket response: {e.Message}");
            return;
        }

        if (job == null || string.IsNullOrWhiteSpace(job.status))
        {
            FailInFlight($"websocket response missing status: {message}");
            return;
        }

        string status = job.status.Trim().ToLowerInvariant();
        if (status == "queued" || status == "processing")
        {
            if (logTraffic) Debug.Log($"[AgentNetworkManager] job {job.job_id} status={status}");
            return;
        }

        _requestInFlight = false;

        if (status == "error")
        {
            MarkFailedTick();
            Debug.LogWarning($"[AgentNetworkManager] job {job.job_id} errored: {job.error}");
            return;
        }

        bool hasPlan =
            (job.actions != null && job.actions.Length > 0) ||
            (job.plan_steps != null && job.plan_steps.Length > 0);
        bool hasAction = job.action != null && !string.IsNullOrWhiteSpace(job.action.action);
        if (status != "done" || (!hasPlan && !hasAction))
        {
            if (logTraffic) Debug.Log($"[AgentNetworkManager] job {job.job_id} ended status={job.status} (no plan)");
            return;
        }

        if (logTraffic)
            Debug.Log($"[AgentNetworkManager] job {job.job_id} DONE steps={StepSummary(job)} reasoning=\"{job.reasoning}\"");

        ParseAndStore(job);
    }

    async UniTask CloseSocketAsync()
    {
        WebSocket socket = _websocket;
        _websocket = null;
        _connectedCreatureId = "";

        if (socket == null) return;

        try
        {
            _intentionalCloseSocket = socket;
            if (socket.State == WebSocketState.Open || socket.State == WebSocketState.Connecting)
                await socket.Close();
        }
        catch (Exception e)
        {
            if (logTraffic) Debug.LogWarning($"[AgentNetworkManager] websocket close failed: {e.Message}");
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  MAIN-THREAD HELPERS
    // ─────────────────────────────────────────────────────────────────────────

    void ParseAndStore(AgentPlanResponse job)
    {
        var steps = new List<LLMIntent>();

        PlanStepPayload[] wireSteps = job.actions != null && job.actions.Length > 0
            ? job.actions
            : job.plan_steps;

        if (wireSteps != null)
        {
            for (int i = 0; i < wireSteps.Length; i++)
            {
                LLMIntent step = ParseStep(wireSteps[i]);
                if (step != null) steps.Add(step);
            }
        }

        if (steps.Count == 0 && job.action != null)
        {
            LLMIntent fallback = ParseStep(job.action.action, job.action.target, "");
            if (fallback != null) steps.Add(fallback);
        }

        if (steps.Count == 0)
            return;

        _latestPlan = new LLMPlan
        {
            jobId     = job.job_id ?? "",
            requestId = job.request_id ?? "",
            reasoning = job.reasoning ?? "",
            steps     = steps.ToArray(),
        };
    }

    LLMIntent ParseStep(PlanStepPayload step)
    {
        if (step == null) return null;
        return ParseStep(step.action, step.target, step.reason);
    }

    LLMIntent ParseStep(string rawAction, string target, string reason)
    {
        if (string.IsNullOrWhiteSpace(rawAction)) return null;

        string action = rawAction.Trim().ToLowerInvariant();
        if (action == "wait") action = "idle";
        if (action == "stop") action = "stop_moving";
        if (action == "move")
        {
            if (!_warnedMoveDeprecated)
            {
                _warnedMoveDeprecated = true;
                Debug.LogWarning("[AgentNetworkManager] backend emitted deprecated action 'move'; normalizing to 'go_to'.");
            }
            action = "go_to";
        }

        return new LLMIntent
        {
            intent      = action,
            destination = Vector3.zero,
            targetKey   = target ?? "",
            reason      = reason ?? "",
        };
    }

    string StepSummary(AgentPlanResponse job)
    {
        if (job == null) return "(null)";

        PlanStepPayload[] wireSteps = job.actions != null && job.actions.Length > 0
            ? job.actions
            : job.plan_steps;

        if (wireSteps != null && wireSteps.Length > 0)
        {
            var parts = new List<string>();
            for (int i = 0; i < wireSteps.Length; i++)
            {
                var step = wireSteps[i];
                if (step == null || string.IsNullOrWhiteSpace(step.action)) continue;
                string target = string.IsNullOrWhiteSpace(step.target) ? "" : $"->{step.target}";
                parts.Add($"{step.action}{target}");
            }
            if (parts.Count > 0) return string.Join(", ", parts);
        }

        if (job.action != null)
        {
            string target = string.IsNullOrWhiteSpace(job.action.target) ? "" : $"->{job.action.target}";
            return $"{job.action.action}{target}";
        }

        return "(none)";
    }

    void CheckRequestTimeout()
    {
        if (!_requestInFlight || config == null || config.websocketResponseTimeoutSeconds <= 0f) return;
        if (Time.realtimeSinceStartup - _requestStartedAt <= config.websocketResponseTimeoutSeconds) return;

        FailInFlight($"websocket response timed out after {config.websocketResponseTimeoutSeconds:F1}s");
        CloseSocketAsync().Forget();
    }

    void FailInFlight(string reason)
    {
        if (!_requestInFlight) return;

        MarkFailedTick();
        _requestInFlight = false;
        if (!string.IsNullOrWhiteSpace(reason))
            Debug.LogWarning($"[AgentNetworkManager] {reason}");
    }

    void MarkFailedTick() => Interlocked.Increment(ref _failedTickCount);
}
