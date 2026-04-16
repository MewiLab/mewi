// AgentBridge.cs — Attach to your cat GameObject in Unity
// Receives HTTP commands from the Python backend and routes them to either:
//   • MAnimalAIControl + NavMesh  (go_to, follow, wander, stop)
//   • MInputLink / MAnimal        (button presses, legacy axis)
//
// Endpoints:
//   POST /action  {"action":"go_to","x":10,"y":0,"z":5}
//   POST /action  {"action":"follow","target":"Player"}
//   POST /action  {"action":"wander"}
//   POST /action  {"action":"Sit","hold":2.0}        ← button, unchanged
//   GET  /state   → JSON with animal + AI nav state
//   GET  /actions → list of valid action names
//   GET  /ping    → {"status":"ok"}

using UnityEngine;
using System.Net;
using System.Threading;
using System.Text;
using System.IO;
using System.Collections.Generic;
using MalbersAnimations;
using MalbersAnimations.Controller;
using MalbersAnimations.Controller.AI;
using MalbersAnimations.InputSystem;

public class AgentBridge : MonoBehaviour
{
    [Header("Settings")]
    public int  port       = 8080;
    public bool logActions = true;

    [Header("References (auto-found if empty)")]
    public MAnimal         animal;
    public MInputLink      inputLink;

    [Header("AI Control (auto-found if empty)")]
    public MAnimalAIControl aiControl;

    [Header("Named Targets")]
    public List<NamedTarget> namedTargets = new List<NamedTarget>();

    [System.Serializable]
    public class NamedTarget
    {
        public string    key;      // e.g. "Player", "FoodBowl", "HomeArea"
        public Transform target;
    }

    // ─── Internal ─────────────────────────────────────────────────────────────
    private Dictionary<string, Transform> _targetMap;

    // ─── HTTP listener ────────────────────────────────────────────────────────
    private HttpListener    _listener;
    private readonly object _lock    = new object();
    private Queue<string>   _pending = new Queue<string>();

    // ─── State / actions JSON cached on main thread ───────────────────────────
    private volatile string _stateJson   = "{}";
    private volatile string _actionsJson = "{\"actions\":[\"go_to\",\"follow\",\"wander\",\"stop\",\"wait\"]}";

    // ─── Legacy move axis (persists until stop/move overrides it) ─────────────
    private Vector2 _moveAxis  = Vector2.zero;
    private float   _moveTimer = 0f;

    // ─────────────────────────────────────────────────────────────────────────
    //  DATA CLASSES
    // ─────────────────────────────────────────────────────────────────────────

    [System.Serializable]
    private class ActionRequest
    {
        public string action = "";
        public float  hold   = 0.3f;   // button hold duration
        public float  x      = 0f;     // go_to world X  /  move axis X
        public float  y      = 0f;     // go_to world Y  /  move axis forward
        public float  z      = 0f;     // go_to world Z
        public string target = "";     // follow: named target key
    }

    [System.Serializable]
    private class GameState
    {
        // Position / orientation
        public float  posX, posY, posZ;
        public float  rotY;

        // Malbers animal state
        public string activeState;
        public string activeStance;
        public bool   grounded;
        public float  speed;
        public bool   sprint;
        public float  moveX, moveY;

        // AI navigation state (populated when MAnimalAIControl is present)
        public bool   aiActive;
        public bool   hasArrived;
        public float  remainingDist;
        public string currentTarget;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  UNITY LIFECYCLE
    // ─────────────────────────────────────────────────────────────────────────

    void Start()
    {
        // Auto-find references if not wired in Inspector
        if (animal    == null) animal    = GetComponentInParent<MAnimal>();
        if (inputLink == null) inputLink = GetComponentInParent<MInputLink>() ?? GetComponent<MInputLink>();
        if (aiControl == null) aiControl = GetComponentInParent<MAnimalAIControl>() ?? GetComponent<MAnimalAIControl>();

        if (animal    == null) Debug.LogError  ("[AgentBridge] MAnimal not found!");
        if (inputLink == null) Debug.LogWarning("[AgentBridge] MInputLink not found — button actions disabled.");
        if (aiControl == null) Debug.LogWarning("[AgentBridge] MAnimalAIControl not found — nav actions (go_to/follow/wander) disabled.");

        // Build target lookup (case-insensitive) from Inspector list
        _targetMap = new Dictionary<string, Transform>(System.StringComparer.OrdinalIgnoreCase);
        foreach (var nt in namedTargets)
            if (nt.target != null)
                _targetMap[nt.key] = nt.target;

        Application.runInBackground = true;

        CacheActions();

        try
        {
            _listener = new HttpListener();
            _listener.Prefixes.Add($"http://localhost:{port}/");
            _listener.Start();
            new Thread(Listen) { IsBackground = true }.Start();
            Debug.Log($"[AgentBridge] Listening on http://localhost:{port}/");
        }
        catch (System.Exception e)
        {
            Debug.LogError($"[AgentBridge] Failed to start listener: {e.Message}");
        }
    }

    void OnDestroy()
    {
        _listener?.Stop();
    }

    void Update()
    {
        CacheState();

        // Tick legacy move axis while its timer is active
        if (_moveTimer > 0f)
        {
            ApplyMoveAxis(_moveAxis);
            _moveTimer -= Time.deltaTime;
            if (_moveTimer <= 0f)
            {
                _moveAxis = Vector2.zero;
                ApplyMoveAxis(Vector2.zero);
            }
        }

        // Dispatch one queued action per frame (main-thread safe)
        string raw = null;
        lock (_lock)
        {
            if (_pending.Count > 0) raw = _pending.Dequeue();
        }
        if (raw != null)
        {
            if (logActions) Debug.Log($"[AgentBridge] dispatch: {raw}");
            Dispatch(JsonUtility.FromJson<ActionRequest>(raw));
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  HTTP LISTENER  (background thread)
    // ─────────────────────────────────────────────────────────────────────────

    void Listen()
    {
        while (_listener != null && _listener.IsListening)
        {
            try   { HandleHttp(_listener.GetContext()); }
            catch (HttpListenerException) { break; }
            catch (System.Exception e)    { Debug.LogError($"[AgentBridge] listener error: {e.Message}"); }
        }
    }

    void HandleHttp(HttpListenerContext ctx)
    {
        var req  = ctx.Request;
        var resp = ctx.Response;

        resp.Headers.Add("Access-Control-Allow-Origin",  "*");
        resp.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
        resp.Headers.Add("Access-Control-Allow-Headers", "Content-Type");

        if (req.HttpMethod == "OPTIONS") { Send(resp, "{}"); return; }

        switch (req.Url.AbsolutePath)
        {
            case "/state":
                Send(resp, _stateJson);
                break;

            case "/action":
                if (req.HttpMethod != "POST")
                {
                    resp.StatusCode = 405;
                    Send(resp, "{\"error\":\"POST required\"}");
                    return;
                }
                string body;
                using (var sr = new StreamReader(req.InputStream)) body = sr.ReadToEnd();
                lock (_lock) { _pending.Enqueue(body); }
                if (logActions) Debug.Log($"[AgentBridge] queued: {body}");
                Send(resp, "{\"ok\":true}");
                break;

            case "/actions":
                Send(resp, _actionsJson);
                break;

            case "/ping":
                Send(resp, "{\"status\":\"ok\"}");
                break;

            default:
                resp.StatusCode = 404;
                Send(resp, "{\"error\":\"not found\"}");
                break;
        }
    }

    void Send(HttpListenerResponse resp, string json)
    {
        resp.ContentType = "application/json";
        byte[] buf = Encoding.UTF8.GetBytes(json);
        resp.OutputStream.Write(buf, 0, buf.Length);
        resp.Close();
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  ACTION DISPATCH  (main thread)
    // ─────────────────────────────────────────────────────────────────────────

    void Dispatch(ActionRequest req)
    {
        switch (req.action)
        {
            // ── Intentional pause ────────────────────────────────────────────
            case "wait":
                return;

            // ── NavMesh navigation (high-level intent) ───────────────────────
            case "go_to":
                if (aiControl != null)
                    aiControl.SetDestination(new Vector3(req.x, req.y, req.z));
                else
                    Debug.LogWarning("[AgentBridge] go_to: MAnimalAIControl not wired.");
                break;

            case "follow":
                if (aiControl == null)
                    Debug.LogWarning("[AgentBridge] follow: MAnimalAIControl not wired.");
                else if (_targetMap.TryGetValue(req.target, out var followTarget))
                    aiControl.SetTarget(followTarget, true);
                else
                    Debug.LogWarning($"[AgentBridge] follow: unknown target '{req.target}'. Registered: {string.Join(", ", _targetMap.Keys)}");
                break;

            case "wander":
                if (aiControl == null)
                    Debug.LogWarning("[AgentBridge] wander: MAnimalAIControl not wired.");
                else if (_targetMap.TryGetValue("HomeArea", out var homeArea))
                    aiControl.SetTarget(homeArea, true);
                else
                    Debug.LogWarning("[AgentBridge] wander: 'HomeArea' not registered in namedTargets.");
                break;

            // ── Stop all movement ────────────────────────────────────────────
            case "stop":
                _moveAxis  = Vector2.zero;
                _moveTimer = 0f;
                ApplyMoveAxis(Vector2.zero);
                if (aiControl != null) aiControl.Stop();
                break;

            // ── Legacy axis input (micro-adjustments only) ───────────────────
            case "move":
                _moveAxis  = new Vector2(req.x, req.y);
                _moveTimer = req.hold > 0 ? req.hold : 0.3f;
                ApplyMoveAxis(_moveAxis);
                break;

            // ── Button inputs via MInputLink ─────────────────────────────────
            default:
                PressButton(req.action, req.hold > 0 ? req.hold : 0.3f);
                break;
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  MOVE AXIS HELPER  (legacy)
    // ─────────────────────────────────────────────────────────────────────────

    void ApplyMoveAxis(Vector2 axis)
    {
        var v = new Vector3(axis.x, 0f, axis.y);
        if (logActions && axis != Vector2.zero)
            Debug.Log($"[AgentBridge] ApplyMoveAxis v={v}");
        if (animal    != null) animal.SetInputAxis(v);
        if (inputLink != null) inputLink.MoveAxis = v;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  BUTTON PRESS HELPER
    //  Fires OnInputDown → waits hold seconds → fires OnInputUp.
    // ─────────────────────────────────────────────────────────────────────────

    void PressButton(string inputName, float hold)
    {
        if (inputLink == null)
        {
            Debug.LogWarning($"[AgentBridge] No MInputLink — cannot press '{inputName}'.");
            return;
        }

        MInputAction btn = FindButton(inputName);
        if (btn == null)
        {
            Debug.LogWarning($"[AgentBridge] Button '{inputName}' not found in active map.");
            return;
        }

        btn.OnInputDown.Invoke();
        btn.OnInputChanged.Invoke(true);
        StartCoroutine(ReleaseAfter(btn, hold));
    }

    System.Collections.IEnumerator ReleaseAfter(MInputAction btn, float delay)
    {
        yield return new WaitForSeconds(delay);
        btn.OnInputUp.Invoke();
        btn.OnInputChanged.Invoke(false);
    }

    MInputAction FindButton(string inputName)
    {
        if (inputLink.ActiveMActionMap != null)
        {
            var b = inputLink.ActiveMActionMap.buttons.Find(x => x.name == inputName);
            if (b != null) return b;
        }
        foreach (var map in inputLink.m_MapButtons)
        {
            var b = map.buttons.Find(x => x.name == inputName);
            if (b != null) return b;
        }
        return null;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  ACTIONS CACHE  (built once on Start)
    // ─────────────────────────────────────────────────────────────────────────

    void CacheActions()
    {
        // Core actions always available — nav first so they appear prominently
        var names = new List<string> { "go_to", "follow", "wander", "stop", "wait", "move" };

        if (inputLink != null)
        {
            foreach (var map in inputLink.m_MapButtons)
                foreach (var btn in map.buttons)
                    if (!string.IsNullOrEmpty(btn.name) && !names.Contains(btn.name))
                        names.Add(btn.name);
        }

        var sb = new System.Text.StringBuilder("{\"actions\":[");
        for (int i = 0; i < names.Count; i++)
        {
            if (i > 0) sb.Append(',');
            sb.Append('"').Append(names[i]).Append('"');
        }
        sb.Append("]}");
        _actionsJson = sb.ToString();
        Debug.Log($"[AgentBridge] Registered actions: {_actionsJson}");
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  STATE CACHE  (main thread, called every frame)
    // ─────────────────────────────────────────────────────────────────────────

    void CacheState()
    {
        var s = new GameState
        {
            posX  = transform.position.x,
            posY  = transform.position.y,
            posZ  = transform.position.z,
            rotY  = transform.eulerAngles.y,
            moveX = _moveAxis.x,
            moveY = _moveAxis.y,
        };

        if (animal != null)
        {
            s.activeState  = animal.ActiveState != null ? animal.ActiveState.name : "none";
            s.activeStance = animal.ActiveStance.ToString();
            s.grounded     = animal.Grounded;
            s.speed        = animal.HorizontalSpeed;
            s.sprint       = animal.Sprint;
        }

        if (aiControl != null)
        {
            s.aiActive      = aiControl.Active;
            s.hasArrived    = aiControl.HasArrived;
            s.remainingDist = aiControl.RemainingDistance;
            s.currentTarget = aiControl.Target != null ? aiControl.Target.name : "";
        }

        _stateJson = JsonUtility.ToJson(s);
    }
}
