// App-level transport for the Unity ↔ backend agent loop.
//
// One Unity app opens one websocket. Per-cat ordering is enforced locally by
// tracking one in-flight request per creature_id; replies are routed by
// creature_id + request_id and consumed by that cat's dispatcher.

using UnityEngine;
using System;
using System.Collections.Generic;
using System.Text;
using System.Threading;
using NativeWebSocket;
using Cysharp.Threading.Tasks;

[DisallowMultipleComponent]
public class AgentNetworkHub : MonoBehaviour
{
    [Header("Backend")]
    public BackendConfig config;

    [Header("Dispatch")]
    [SerializeField] AgentWebSocketDispatcher _messageDispatcher;

    [Header("Debug")]
    public bool logTraffic = true;

    public static AgentNetworkHub Instance { get; private set; }
    public int FailedTickCount => _failedTickCount;
    public int RegisteredCreatureCount => _registeredCreatures.Count;
    public int InFlightCount => _inFlightByCreature.Count;

    int  _failedTickCount;
    bool _isConnecting;
    bool _registrationDirty;
    WebSocket _websocket;
    WebSocket _intentionalCloseSocket;
    CancellationTokenSource _cts;

    readonly HashSet<string> _registeredCreatures =
        new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    readonly Dictionary<string, PendingRequest> _inFlightByCreature =
        new Dictionary<string, PendingRequest>(StringComparer.OrdinalIgnoreCase);
    sealed class PendingRequest
    {
        public string requestId;
        public float startedAt;
    }

    [Serializable] sealed class RegisterEnvelope
    {
        public string type = "register";
        public string[] creature_ids;
    }

    [Serializable] sealed class TickEnvelope
    {
        public string type = "tick";
        public string agent_id = "";
        public string requestId = "";
        public PlanExecutionReport report;
        public SnapshotPayload snapshot;
    }

    public static AgentNetworkHub Resolve()
    {
        if (Instance != null) return Instance;
        return FindFirstObjectByType<AgentNetworkHub>();
    }

    void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Debug.LogWarning("[AgentNetworkHub] multiple hubs found; disabling duplicate.");
            enabled = false;
            return;
        }

        Instance = this;
        EnsureMessageDispatcher();
    }

    void EnsureMessageDispatcher()
    {
        if (_messageDispatcher == null)
            _messageDispatcher = GetComponent<AgentWebSocketDispatcher>();
        if (_messageDispatcher == null)
            _messageDispatcher = gameObject.AddComponent<AgentWebSocketDispatcher>();
    }

    public void RegisterCreature(string creatureId)
    {
        string id = NormalizeCreatureId(creatureId);
        if (string.IsNullOrEmpty(id))
            return;

        if (_registeredCreatures.Add(id))
        {
            _registrationDirty = true;
            if (logTraffic)
                Debug.Log($"[AgentNetworkHub] registered creature={id} total={_registeredCreatures.Count}");
            SendRegistrationIfConnected().Forget();
        }
    }

    public bool IsRequestInFlight(string creatureId)
    {
        string id = NormalizeCreatureId(creatureId);
        return !string.IsNullOrEmpty(id) && _inFlightByCreature.ContainsKey(id);
    }

    public bool SendTick(string creatureId, SnapshotPayload snapshot, PlanExecutionReport planReport = null)
    {
        string id = NormalizeCreatureId(creatureId);
        if (string.IsNullOrEmpty(id))
        {
            Debug.LogWarning("[AgentNetworkHub] SendTick called with empty creatureId");
            return false;
        }

        if (snapshot == null)
        {
            Debug.LogWarning($"[AgentNetworkHub] SendTick called with null snapshot creature={id}");
            return false;
        }

        string requestId = snapshot.requestId ?? "";
        if (string.IsNullOrWhiteSpace(requestId))
        {
            Debug.LogWarning($"[AgentNetworkHub] SendTick called with empty requestId creature={id}");
            return false;
        }

        if (_inFlightByCreature.ContainsKey(id))
        {
            if (logTraffic)
                Debug.Log($"[AgentNetworkHub] tick skipped: request already in flight creature={id}");
            return false;
        }

        RegisterCreature(id);

        var envelope = new TickEnvelope
        {
            type      = "tick",
            agent_id  = id,
            requestId = requestId,
            report    = planReport,
            snapshot  = snapshot,
        };

        _inFlightByCreature[id] = new PendingRequest
        {
            requestId = requestId,
            startedAt = Time.realtimeSinceStartup,
        };

        string json = JsonUtility.ToJson(envelope);
        if (logTraffic)
            Debug.Log($"[AgentNetworkHub] sending tick creature={id} request={requestId} bytes={json.Length} inFlight={_inFlightByCreature.Count}");

        EnsureAndSendAsync(id, requestId, json, CurrentCancellationToken).Forget();
        return true;
    }

    public bool TryConsumeDirective(string creatureId, out string intent, out string target)
    {
        intent = "";
        target = "";

        if (!TryConsumeDirective(creatureId, out CreatureBlackboard.MindDirective directive))
            return false;

        intent = directive.Intent ?? "";
        target = directive.FocusTarget ?? "";
        return !string.IsNullOrWhiteSpace(intent);
    }

    public bool TryConsumeDirective(string creatureId, out CreatureBlackboard.MindDirective directive)
    {
        directive = default;

        string id = NormalizeCreatureId(creatureId);
        if (string.IsNullOrEmpty(id))
            return false;

        EnsureMessageDispatcher();
        return _messageDispatcher != null &&
               _messageDispatcher.TryConsumeDirective(id, out directive);
    }

    void Update()
    {
#if !UNITY_WEBGL || UNITY_EDITOR
        _websocket?.DispatchMessageQueue();
#endif
        CheckRequestTimeouts();
    }

    void OnDisable()
    {
        _cts?.Cancel();
        _cts?.Dispose();
        _cts = null;
        _isConnecting = false;
        _inFlightByCreature.Clear();
        CloseSocketAsync().Forget();
        if (Instance == this)
            Instance = null;
    }

    CancellationToken CurrentCancellationToken
    {
        get
        {
            if (_cts == null)
                _cts = new CancellationTokenSource();
            return _cts.Token;
        }
    }

    async UniTaskVoid EnsureAndSendAsync(string creatureId, string requestId, string json, CancellationToken ct)
    {
        try
        {
            if (!await EnsureConnectedAsync(ct))
            {
                FailInFlight(creatureId, requestId, "websocket connection failed");
                return;
            }

            await SendRegistrationIfNeeded(ct);
            await _websocket.SendText(json);
            if (logTraffic)
                Debug.Log($"[AgentNetworkHub] websocket tick sent creature={creatureId} request={requestId}");
        }
        catch (OperationCanceledException)
        {
            ClearInFlight(creatureId, requestId);
            if (logTraffic)
                Debug.Log($"[AgentNetworkHub] websocket tick cancelled creature={creatureId} request={requestId}");
        }
        catch (Exception e)
        {
            FailInFlight(creatureId, requestId, $"websocket tick failed: {e.Message}");
        }
    }

    async UniTask<bool> EnsureConnectedAsync(CancellationToken ct)
    {
        if (config == null)
        {
            Debug.LogError("[AgentNetworkHub] missing BackendConfig");
            return false;
        }

        if (_websocket != null && _websocket.State == WebSocketState.Open)
            return true;

        if (_isConnecting)
        {
            await UniTask.WaitUntil(() => !_isConnecting, cancellationToken: ct);
            return _websocket != null && _websocket.State == WebSocketState.Open;
        }

        await CloseSocketAsync();

        string url = ApiRoutes.ResolveWebSocket(config, ApiRoutes.AgentTickWs);
        var headers = config.BuildAuthHeaders();
        _websocket = headers.Count > 0 ? new WebSocket(url, headers) : new WebSocket(url);
        BindWebSocketHandlers(_websocket);

        _isConnecting = true;
        if (logTraffic)
            Debug.Log($"[AgentNetworkHub] connecting websocket {url}");

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
                Debug.LogWarning($"[AgentNetworkHub] websocket connect ended state={(socket != null ? socket.State.ToString() : "null")}");
            return connected;
        }
        catch (Exception e)
        {
            Debug.LogWarning($"[AgentNetworkHub] websocket connect failed: {e.Message}");
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
                FailAllInFlight($"websocket connect failed: {e.Message}");
        }
    }

    void BindWebSocketHandlers(WebSocket socket)
    {
        socket.OnOpen += () =>
        {
            if (logTraffic)
                Debug.Log("[AgentNetworkHub] websocket connected");
            _registrationDirty = _registeredCreatures.Count > 0;
            SendRegistrationIfConnected().Forget();
        };

        socket.OnError += error =>
        {
            FailAllInFlight($"websocket error: {error}");
        };

        socket.OnClose += code =>
        {
            bool intentionalClose = _intentionalCloseSocket == socket;
            if (intentionalClose)
                _intentionalCloseSocket = null;

            if (logTraffic)
                Debug.LogWarning($"[AgentNetworkHub] websocket closed code={code}");
            if (_websocket == socket)
                _websocket = null;
            _isConnecting = false;
            if (!intentionalClose)
                FailAllInFlight($"websocket closed before response (code={code})");
        };

        socket.OnMessage += bytes =>
        {
            string message = Encoding.UTF8.GetString(bytes);
            EnsureMessageDispatcher();
            _messageDispatcher?.HandleServerMessage(message, this, logTraffic);
        };
    }

    async UniTaskVoid SendRegistrationIfConnected()
    {
        try
        {
            if (_websocket != null && _websocket.State == WebSocketState.Open)
                await SendRegistrationIfNeeded(CurrentCancellationToken);
        }
        catch (Exception e)
        {
            if (logTraffic)
                Debug.LogWarning($"[AgentNetworkHub] registration send failed: {e.Message}");
        }
    }

    async UniTask SendRegistrationIfNeeded(CancellationToken ct)
    {
        if (!_registrationDirty || _registeredCreatures.Count == 0)
            return;
        if (_websocket == null || _websocket.State != WebSocketState.Open)
            return;

        ct.ThrowIfCancellationRequested();
        string[] ids = new string[_registeredCreatures.Count];
        _registeredCreatures.CopyTo(ids);
        Array.Sort(ids, StringComparer.OrdinalIgnoreCase);

        string json = JsonUtility.ToJson(new RegisterEnvelope { creature_ids = ids });
        await _websocket.SendText(json);
        _registrationDirty = false;
        if (logTraffic)
            Debug.Log($"[AgentNetworkHub] sent register creatures=[{string.Join(",", ids)}]");
    }

    async UniTask CloseSocketAsync()
    {
        WebSocket socket = _websocket;
        _websocket = null;

        if (socket == null)
            return;

        try
        {
            _intentionalCloseSocket = socket;
            if (socket.State == WebSocketState.Open || socket.State == WebSocketState.Connecting)
                await socket.Close();
        }
        catch (Exception e)
        {
            if (logTraffic)
                Debug.LogWarning($"[AgentNetworkHub] websocket close failed: {e.Message}");
        }
    }

    void CheckRequestTimeouts()
    {
        if (config == null || config.websocketResponseTimeoutSeconds <= 0f || _inFlightByCreature.Count == 0)
            return;

        float now = Time.realtimeSinceStartup;
        var timedOut = new List<string>();
        foreach (var pair in _inFlightByCreature)
        {
            if (now - pair.Value.startedAt > config.websocketResponseTimeoutSeconds)
                timedOut.Add(pair.Key);
        }

        for (int i = 0; i < timedOut.Count; i++)
        {
            string creatureId = timedOut[i];
            PendingRequest pending = _inFlightByCreature[creatureId];
            FailInFlight(
                creatureId,
                pending.requestId,
                $"websocket response timed out after {config.websocketResponseTimeoutSeconds:F1}s");
        }
    }

    internal bool TryCompleteRequest(string creatureId, string requestId)
        => ClearInFlight(creatureId, requestId);

    internal void RecordFailedResponse() => MarkFailedTick();

    bool ClearInFlight(string creatureId, string requestId)
    {
        if (!_inFlightByCreature.TryGetValue(creatureId, out PendingRequest pending))
            return false;

        if (!string.IsNullOrWhiteSpace(requestId) &&
            !string.Equals(pending.requestId, requestId, StringComparison.Ordinal))
        {
            return false;
        }

        _inFlightByCreature.Remove(creatureId);
        return true;
    }

    void FailInFlight(string creatureId, string requestId, string reason)
    {
        if (!ClearInFlight(creatureId, requestId))
            return;

        MarkFailedTick();
        if (!string.IsNullOrWhiteSpace(reason))
            Debug.LogWarning($"[AgentNetworkHub] {reason} creature={creatureId} request={requestId}");
    }

    void FailAllInFlight(string reason)
    {
        if (_inFlightByCreature.Count == 0)
            return;

        var pending = new List<KeyValuePair<string, PendingRequest>>(_inFlightByCreature);
        _inFlightByCreature.Clear();
        for (int i = 0; i < pending.Count; i++)
        {
            MarkFailedTick();
            Debug.LogWarning($"[AgentNetworkHub] {reason} creature={pending[i].Key} request={pending[i].Value.requestId}");
        }
    }

    void MarkFailedTick() => Interlocked.Increment(ref _failedTickCount);

    static string NormalizeCreatureId(string creatureId)
        => string.IsNullOrWhiteSpace(creatureId) ? "" : creatureId.Trim();
}
