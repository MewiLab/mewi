// AgentBridge.cs — Attach to your cat GameObject in Unity
// Receives HTTP commands from Python and fires them through the Malbers
// MInputLink event system — exactly as if the player pressed a key.
//
// Python sends POST /action  {"action":"Sprint","hold":0.2}
//                  GET /state  → JSON with current animal state
//                  GET /actions → list of valid action names
//
// Movement is a special case: POST /action {"action":"move","x":0,"y":1}
// sets MoveAxis directly on MInputLink so the animal walks/runs.

using UnityEngine;
using System.Net;
using System.Threading;
using System.Text;
using System.IO;
using System.Collections.Generic;
using MalbersAnimations;
using MalbersAnimations.Controller;
using MalbersAnimations.InputSystem;

public class AgentBridge : MonoBehaviour
{
    [Header("Settings")]
    public int port = 8080;
    public bool logActions = true;

    [Header("References (auto-found if empty)")]
    public MAnimal   animal;
    public MInputLink inputLink;

    // ─── HTTP Listener ───────────────────────────────────────────────────────
    private HttpListener  _listener;
    private readonly object _lock = new object();
    private Queue<string>  _pending = new Queue<string>();

    // ─── State + actions list cached on the main thread ─────────────────────
    private volatile string _stateJson   = "{}";
    private volatile string _actionsJson = "{\"actions\":[\"move\",\"stop\",\"wait\"]}";

    // ─── Active move axis (persists until a stop/move overrides it) ──────────
    private Vector2 _moveAxis  = Vector2.zero;
    private float   _moveTimer = 0f;     // seconds remaining for timed moves

    // ─────────────────────────────────────────────────────────────────────────
    //  DATA CLASSES
    // ─────────────────────────────────────────────────────────────────────────

    [System.Serializable]
    private class ActionRequest
    {
        public string action  = "";
        public float  hold    = 0.3f;   // seconds to hold button (button actions)
        public float  x       = 0f;     // horizontal axis  (move action)
        public float  y       = 0f;     // forward/back axis (move action)
    }

    [System.Serializable]
    private class GameState
    {
        public float  posX, posY, posZ;
        public float  rotY;
        public string activeState;
        public string activeStance;
        public bool   grounded;
        public float  speed;
        public bool   sprint;
        public float  moveX, moveY;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  UNITY LIFECYCLE
    // ─────────────────────────────────────────────────────────────────────────

    void Start()
    {
        if (animal    == null) animal    = GetComponentInParent<MAnimal>();
        if (inputLink == null) inputLink = GetComponentInParent<MInputLink>();
        if (inputLink == null) inputLink = GetComponent<MInputLink>();

        if (animal    == null) Debug.LogError("[AgentBridge] MAnimal not found!");
        if (inputLink == null) Debug.LogWarning("[AgentBridge] MInputLink not found — button actions disabled.");

        // Allow Unity to keep running (and receiving HTTP commands) even when
        // the Editor/Player window is not focused.
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

        // Feed move axis every frame while timer is running
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
            if (logActions) Debug.Log($"[AgentBridge] dequeued: {raw} | animal={animal != null} inputLink={inputLink != null}");
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
            catch (System.Exception e)   { Debug.LogError($"[AgentBridge] {e.Message}"); }
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
                if (req.HttpMethod != "POST") { resp.StatusCode = 405; Send(resp, "{\"error\":\"POST required\"}"); return; }
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
        if (req.action == "wait") return;

        // ── Movement (axis-based, not a button) ──────────────────────────────
        if (req.action == "move")
        {
            _moveAxis  = new Vector2(req.x, req.y);
            _moveTimer = req.hold > 0 ? req.hold : 0.3f;
            ApplyMoveAxis(_moveAxis);
            return;
        }

        if (req.action == "stop")
        {
            _moveAxis  = Vector2.zero;
            _moveTimer = 0f;
            ApplyMoveAxis(Vector2.zero);
            return;
        }

        // ── Button inputs via MInputLink ─────────────────────────────────────
        PressButton(req.action, req.hold > 0 ? req.hold : 0.3f);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  MOVE AXIS HELPER
    //  Feeds the Vector2 into MInputLink so Malbers treats it as joystick input.
    // ─────────────────────────────────────────────────────────────────────────

    void ApplyMoveAxis(Vector2 axis)
    {
        // Drive the animal directly — MInputLink.MoveAxis is just a stored value
        // and does not forward to the animal unless its own InputAction callbacks fire.
        var v = new Vector3(axis.x, 0f, axis.y);
        if (logActions && axis != Vector2.zero)
            Debug.Log($"[AgentBridge] ApplyMoveAxis v={v} animal={animal != null} inputLink={inputLink != null}");
        if (animal != null)
            animal.SetInputAxis(v);
        if (inputLink != null)
            inputLink.MoveAxis = v;   // keep in sync so Malbers HUD / other listeners see it
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  BUTTON PRESS HELPER
    //
    //  Fires OnInputDown → waits `hold` seconds → fires OnInputUp.
    //  This matches exactly what Malbers expects from a physical key press.
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

        // Press
        btn.OnInputDown.Invoke();
        btn.OnInputChanged.Invoke(true);

        // Release after hold duration
        StartCoroutine(ReleaseAfter(btn, hold));
    }

    System.Collections.IEnumerator ReleaseAfter(MInputAction btn, float delay)
    {
        yield return new WaitForSeconds(delay);
        btn.OnInputUp.Invoke();
        btn.OnInputChanged.Invoke(false);
    }

    // Search the current active map, then fall back to all maps
    MInputAction FindButton(string inputName)
    {
        if (inputLink.ActiveMActionMap != null)
        {
            var b = inputLink.ActiveMActionMap.buttons.Find(x => x.name == inputName);
            if (b != null) return b;
        }

        // Try every map in case the active map is wrong
        foreach (var map in inputLink.m_MapButtons)
        {
            var b = map.buttons.Find(x => x.name == inputName);
            if (b != null) return b;
        }
        return null;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  ACTIONS CACHE  (built once on Start — button names are stable at runtime)
    // ─────────────────────────────────────────────────────────────────────────

    void CacheActions()
    {
        var names = new System.Collections.Generic.List<string> { "move", "stop", "wait" };

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
            s.activeState  = animal.ActiveState  != null ? animal.ActiveState.name  : "none";
            s.activeStance = animal.ActiveStance.ToString();
            s.grounded     = animal.Grounded;
            s.speed        = animal.HorizontalSpeed;
            s.sprint       = animal.Sprint;
        }

        _stateJson = JsonUtility.ToJson(s);
    }
}
