// AgentMindBridge.cs  (Creature/Layers/Mind/)
//
// Pure transport adapter for the PeriodicMind ↔ LLM backend loop.
//
// Responsibilities (and ONLY these):
//   Outbound — SendTick(board)
//              Reads the blackboard, builds + POSTs the perception snapshot.
//              Returns a requestId the caller uses to match the response.
//              Owns the wire format — PeriodicMind never touches JSON.
//
//   Inbound  — HTTP listener on port 8080 receives POST /action from backend.
//              Parses the command into an LLMIntent and stores it.
//
//   Query    — TryConsumeResponse(requestId, out LLMIntent)
//              PeriodicMind polls this each Think() cycle.
//              Returns true and clears the intent on match.
//
//   State    — GET /state serves motor/nav state for backend polling.
//              Reads Malbers components — not the blackboard.
//
// NOT responsible for:
//   • Writing the blackboard  (PeriodicMind is the sole Mind-slot writer)
//   • Deciding which intent to apply  (PeriodicMind owns that)
//
// requestId matching uses "latest wins" for v1 — the backend does not yet echo
// the requestId in its /action callback.
// TODO: tighten to strict ID match once the backend echoes requestId.

using UnityEngine;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Net;
using System.Threading;
using System.Text;
using System.IO;
using UnityEngine.Networking;
using MalbersAnimations;
using MalbersAnimations.Controller;
using MalbersAnimations.Controller.AI;

public class AgentMindBridge : MonoBehaviour
{
    // ─────────────────────────────────────────────────────────────────────────
    //  INSPECTOR
    // ─────────────────────────────────────────────────────────────────────────

    [Header("Backend")]
    public string backendUrl = "http://localhost:8000/api/v1/agent/tick";

    [Header("Inbound Listener")]
    public int  listenerPort = 8080;
    public bool logTraffic   = true;

    [Header("Named Targets (resolved for 'follow' intent)")]
    public List<NamedTarget> namedTargets = new List<NamedTarget>();

    [System.Serializable]
    public class NamedTarget
    {
        public string    key;      // matches "target" field in backend /action callback
        public Transform target;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  OUTPUT TYPE — produced here, consumed by PeriodicMind
    // ─────────────────────────────────────────────────────────────────────────

    public class LLMIntent
    {
        public string    intent;        // blackboard intent string: "go_to", "wander", "sit", …
        public Vector3   destination;   // world position (go_to)
        public Transform target;        // resolved Transform (follow); null otherwise
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  OUTBOUND WIRE FORMAT  (POST /api/v1/agent/tick)
    //  Matches the backend's PerceptionSnapshot schema exactly.
    //  Lives here — PeriodicMind and CreaturePerception are shielded from this.
    // ─────────────────────────────────────────────────────────────────────────

    [Serializable] class TickPayload
    {
        public string     requestId;
        public float      time;
        public SelfData   self;
        public MoodData   mood;
        public HealthData health;
        public EntityData[] entities;
    }
    [Serializable] class SelfData
    {
        public float x, y, z, rotY;
        public bool  playerInSight;
        public float closestPlayerDist;
    }
    [Serializable] class MoodData   { public float fear, trust, curiosity, social, energy; }
    [Serializable] class HealthData { public float hunger; }
    [Serializable] class EntityData
    {
        public string type, label, category;
        public float  intensity, px, py, pz;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  INBOUND WIRE FORMAT  (POST /action from backend)
    // ─────────────────────────────────────────────────────────────────────────

    [Serializable] class ActionCallback
    {
        public string requestId = "";
        public string action    = "";
        public float  x = 0f, y = 0f, z = 0f;
        public string target    = "";
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  STATE WIRE FORMAT  (GET /state)
    // ─────────────────────────────────────────────────────────────────────────

    [Serializable] class MotorState
    {
        public float  posX, posY, posZ, rotY;
        public string activeState, activeStance;
        public bool   grounded;
        public float  speed;
        public bool   sprint;
        public bool   aiActive;
        public bool   hasArrived;
        public float  remainingDist;
        public string currentTarget;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  PRIVATE STATE
    // ─────────────────────────────────────────────────────────────────────────

    MAnimal          _animal;
    MAnimalAIControl _aiControl;

    Dictionary<string, Transform> _targetMap;

    HttpListener    _listener;
    readonly object _lock = new object();

    // Latest response — listener thread writes, main thread reads
    string    _latestResponseId = null;
    LLMIntent _latestIntent     = null;
    string    _pendingTargetKey = "";   // resolved on main thread in Tick()

    volatile string _stateJson = "{}";

    // ─────────────────────────────────────────────────────────────────────────
    //  INIT  (called by CreatureController — no board reference stored here)
    // ─────────────────────────────────────────────────────────────────────────

    public void Init()
    {
        _animal    = GetComponentInParent<MAnimal>();
        _aiControl = GetComponentInParent<MAnimalAIControl>() ?? GetComponent<MAnimalAIControl>();

        if (_animal    == null) Debug.LogWarning("[AgentMindBridge] MAnimal not found — /state will be sparse.");
        if (_aiControl == null) Debug.LogWarning("[AgentMindBridge] MAnimalAIControl not found — nav state omitted.");

        _targetMap = new Dictionary<string, Transform>(StringComparer.OrdinalIgnoreCase);
        foreach (var nt in namedTargets)
            if (nt.target != null)
                _targetMap[nt.key] = nt.target;

        Application.runInBackground = true;
        StartListener();
    }

    void OnDestroy() => _listener?.Stop();

    // ─────────────────────────────────────────────────────────────────────────
    //  TICK  (called by CreatureController.Update — main thread)
    // ─────────────────────────────────────────────────────────────────────────

    public void Tick()
    {
        ResolveFollowTarget();  // Transform lookup must happen on main thread
        CacheMotorState();
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  PUBLIC API — called by PeriodicMind
    // ─────────────────────────────────────────────────────────────────────────

    /// <summary>
    /// Build a perception snapshot from the blackboard, POST it to the backend.
    /// Returns a requestId — store it and pass to TryConsumeResponse() each tick.
    /// </summary>
    public string SendTick(CreatureBlackboard board)
    {
        string id      = Guid.NewGuid().ToString("N")[..8];
        string json    = BuildSnapshotJson(board, id);

        if (logTraffic) Debug.Log($"[AgentMindBridge] SendTick id={id}");
        StartCoroutine(PostToBackend(json));
        return id;
    }

    /// <summary>
    /// Check whether the backend replied to the given tick.
    /// Clears the stored response on success (consume-once).
    ///
    /// v1: "latest wins" — any stored response is returned regardless of ID,
    ///     because the backend does not yet echo requestId in /action.
    /// TODO: replace with strict (_latestResponseId == requestId) once it does.
    /// </summary>
    public bool TryConsumeResponse(string requestId, out LLMIntent intent)
    {
        lock (_lock)
        {
            if (_latestIntent == null) { intent = null; return false; }

            intent            = _latestIntent;
            _latestIntent     = null;
            _latestResponseId = null;
            return true;
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  SNAPSHOT BUILDING  (main thread, called from SendTick)
    //  The only place in the codebase that knows the backend's JSON contract.
    // ─────────────────────────────────────────────────────────────────────────

    string BuildSnapshotJson(CreatureBlackboard board, string requestId)
    {
        var entities = new List<EntityData>();
        foreach (var evt in board.sensorEvents)
        {
            entities.Add(new EntityData
            {
                type      = evt.type.ToString(),
                label     = evt.label,
                category  = evt.category,
                intensity = evt.intensity,
                px        = evt.position.x,
                py        = evt.position.y,
                pz        = evt.position.z,
            });
        }

        var payload = new TickPayload
        {
            requestId = requestId,
            time      = Time.time,
            self      = new SelfData
            {
                x                 = transform.position.x,
                y                 = transform.position.y,
                z                 = transform.position.z,
                rotY              = transform.eulerAngles.y,
                playerInSight     = board.playerInSight,
                closestPlayerDist = board.closestPlayerDist,
            },
            mood = new MoodData
            {
                fear      = board.mood.fear,
                trust     = board.mood.trust,
                curiosity = board.mood.curiosity,
                social    = board.mood.social,
                energy    = board.mood.energy,
            },
            health   = new HealthData { hunger = board.health.hunger },
            entities = entities.ToArray(),
        };

        return JsonUtility.ToJson(payload);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  OUTBOUND HTTP  (coroutine)
    // ─────────────────────────────────────────────────────────────────────────

    IEnumerator PostToBackend(string json)
    {
        var req = new UnityWebRequest(backendUrl, "POST");
        req.uploadHandler   = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
        req.downloadHandler = new DownloadHandlerBuffer();
        req.SetRequestHeader("Content-Type", "application/json");
        yield return req.SendWebRequest();

        if (req.result != UnityWebRequest.Result.Success)
            Debug.LogWarning($"[AgentMindBridge] SendTick failed: {req.error}");
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  INBOUND HTTP LISTENER  (background thread)
    // ─────────────────────────────────────────────────────────────────────────

    void StartListener()
    {
        try
        {
            _listener = new HttpListener();
            _listener.Prefixes.Add($"http://localhost:{listenerPort}/");
            _listener.Start();
            new Thread(Listen) { IsBackground = true }.Start();
            Debug.Log($"[AgentMindBridge] Listening on http://localhost:{listenerPort}/");
        }
        catch (Exception e)
        {
            Debug.LogError($"[AgentMindBridge] Failed to start listener: {e.Message}");
        }
    }

    void Listen()
    {
        while (_listener != null && _listener.IsListening)
        {
            try   { HandleHttp(_listener.GetContext()); }
            catch (HttpListenerException) { break; }
            catch (Exception e)           { Debug.LogError($"[AgentMindBridge] {e.Message}"); }
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
            case "/action":
                if (req.HttpMethod != "POST")
                { resp.StatusCode = 405; Send(resp, "{\"error\":\"POST required\"}"); return; }
                string body;
                using (var sr = new StreamReader(req.InputStream)) body = sr.ReadToEnd();
                if (logTraffic) Debug.Log($"[AgentMindBridge] /action: {body}");
                ParseAndStore(JsonUtility.FromJson<ActionCallback>(body));
                Send(resp, "{\"ok\":true}");
                break;

            case "/state":
                Send(resp, _stateJson);
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
    //  RESPONSE PARSING  (background thread)
    //  Transform lookups must happen on the main thread — store key, resolve in Tick().
    // ─────────────────────────────────────────────────────────────────────────

    void ParseAndStore(ActionCallback cb)
    {
        if (cb == null || string.IsNullOrEmpty(cb.action) || cb.action == "wait")
            return;

        lock (_lock)
        {
            _latestResponseId = string.IsNullOrEmpty(cb.requestId) ? "latest" : cb.requestId;
            _latestIntent     = new LLMIntent
            {
                intent      = cb.action == "stop" ? "idle" : cb.action,
                destination = new Vector3(cb.x, cb.y, cb.z),
                target      = null,     // resolved on main thread
            };
            _pendingTargetKey = cb.target ?? "";
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  MAIN-THREAD HELPERS
    // ─────────────────────────────────────────────────────────────────────────

    void ResolveFollowTarget()
    {
        lock (_lock)
        {
            if (_latestIntent == null || string.IsNullOrEmpty(_pendingTargetKey)) return;
            _targetMap.TryGetValue(_pendingTargetKey, out _latestIntent.target);
            _pendingTargetKey = "";
        }
    }

    void CacheMotorState()
    {
        var s = new MotorState
        {
            posX = transform.position.x,
            posY = transform.position.y,
            posZ = transform.position.z,
            rotY = transform.eulerAngles.y,
        };

        if (_animal != null)
        {
            s.activeState  = _animal.ActiveState != null ? _animal.ActiveState.name : "none";
            s.activeStance = _animal.ActiveStance.ToString();
            s.grounded     = _animal.Grounded;
            s.speed        = _animal.HorizontalSpeed;
            s.sprint       = _animal.Sprint;
        }

        if (_aiControl != null)
        {
            s.aiActive      = _aiControl.Active;
            s.hasArrived    = _aiControl.HasArrived;
            s.remainingDist = _aiControl.RemainingDistance;
            s.currentTarget = _aiControl.Target != null ? _aiControl.Target.name : "";
        }

        _stateJson = JsonUtility.ToJson(s);
    }
}
