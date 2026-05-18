/*
    The "slow mind": fires on a timer, updates mood, drives the Mind intent slot.

    Modes:
      Simulated — rule-based mood + intent, fully local.
      LLM       — every tick:
                    1. consume any pending response from the bridge
                    2. build a fresh snapshot via SnapshotManager
                    3. hand it to AgentMindBridge.SendTick (latest-wins backpressure)
                  mood decay still runs each tick so it never freezes between replies.

    Responsibility split (Option A — orchestrator-knows-all):
      PeriodicMind    — WHEN  (timer, owns the loop)
      SnapshotManager — WHAT  (channel registry → JSON)
      AgentMindBridge — HOW   (POST + poll + parse, async)

    PeriodicMind is the sole writer to CreatureBlackboard.SetMindIntent().
*/
using System.Collections;
using UnityEngine;

public enum MindMode { Simulated, LLM }

[RequireComponent(typeof(AgentMindBridge))]
[RequireComponent(typeof(HttpActionReporter))]
public class PeriodicMind : MonoBehaviour
{
    CreatureBlackboard _board;
    CreatureConfig     _config;
    [SerializeField] AgentMindBridge _bridge;
    [SerializeField] SnapshotManager _snapshotManager;
    [SerializeField] NamedTargetRegistry _targetRegistry;
    [SerializeField] HttpActionReporter _reporter;

    [Header("Mind Mode")]
    public MindMode mode = MindMode.Simulated;

    [Header("Debug")]
    [SerializeField] bool logLLMTicks = true;

    bool _running;
    int  _tickCounter;
    int  _commandCounter;
    int  _lastObservedBridgeFailureCount;
    string _lastRequestId = "";

    public void Init(CreatureBlackboard board, CreatureConfig config)
    {
        _board  = board;
        _config = config;
        if (_bridge == null)          _bridge          = GetComponent<AgentMindBridge>();
        if (_snapshotManager == null) _snapshotManager = GetComponent<SnapshotManager>();
        if (_targetRegistry == null)  _targetRegistry  = FindFirstObjectByType<NamedTargetRegistry>();
        if (_reporter == null)        _reporter        = GetComponent<HttpActionReporter>();
        if (_reporter != null && _bridge != null)
            _reporter.UseConfig(_bridge.config);

        if (logLLMTicks)
        {
            string baseUrl = _bridge != null && _bridge.config != null ? _bridge.config.baseUrl : "(missing config)";
            string tickInterval = _config != null ? _config.mindTickInterval.ToString("F1") : "(missing config)";
            Debug.Log($"[PeriodicMind] init mode={mode} tickInterval={tickInterval}s backend={baseUrl}");
        }

        if (mode == MindMode.LLM)
        {
            if (_bridge == null)
                Debug.LogError("[PeriodicMind] LLM mode needs AgentMindBridge on the same GameObject.");
            if (_snapshotManager == null)
                Debug.LogError("[PeriodicMind] LLM mode needs SnapshotManager on the same GameObject.");
        }
    }

    public void StartThinking()
    {
        if (_running) return;
        if (_config == null)
        {
            Debug.LogError("[PeriodicMind] StartThinking failed: Init was not called or CreatureConfig is missing.");
            return;
        }

        _running = true;
        if (logLLMTicks)
            Debug.Log($"[PeriodicMind] StartThinking mode={mode}");
        StartCoroutine(ThinkLoop());
    }

    public void StopThinking()
    {
        _running = false;
        StopAllCoroutines();
    }

    IEnumerator ThinkLoop()
    {
        var wait = new WaitForSecondsRealtime(_config.mindTickInterval);
        while (_running)
        {
            yield return wait;
            Think();
        }
    }

    void Think()
    {
        UpdateMood();
        ResolveIntent();
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  MOOD
    // ─────────────────────────────────────────────────────────────────────────

    void UpdateMood()
    {
        switch (mode)
        {
            case MindMode.Simulated: UpdateMoodFull();      break;
            case MindMode.LLM:       UpdateMoodDecayOnly(); break;
        }
    }

    void UpdateMoodFull()
    {
        MoodModel mood = _board.mood;

        mood.fear  = Mathf.MoveTowards(mood.fear,  0.2f, _config.fearDecayRate);
        mood.trust = Mathf.MoveTowards(mood.trust, 0.3f, _config.trustDecayRate);

        string events = _board.GetRecentEventsSummary();
        if (events.Contains("startled")) { mood.fear += 0.15f; mood.trust -= 0.1f; }
        if (events.Contains("fed") || events.Contains("food")) { mood.trust += 0.1f; mood.social += 0.05f; }

        if (_board.playerInSight && _board.closestPlayerDist < _config.personalSpaceRadius)
        {
            if (mood.trust < 0.4f) mood.fear   += 0.1f;
            else                   mood.social += 0.05f;
        }

        mood.energy -= 0.02f;
        if (_board.GetCurrentHunger() > 0.7f) mood.energy -= 0.03f;
        mood.Clamp();
    }

    void UpdateMoodDecayOnly()
    {
        MoodModel mood = _board.mood;
        mood.fear   = Mathf.MoveTowards(mood.fear,  0.2f, _config.fearDecayRate);
        mood.trust  = Mathf.MoveTowards(mood.trust, 0.3f, _config.trustDecayRate);
        mood.energy -= 0.02f;
        mood.Clamp();
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  INTENT
    // ─────────────────────────────────────────────────────────────────────────

    void ResolveIntent()
    {
        switch (mode)
        {
            case MindMode.Simulated:
                string intent = SelectIntentLocal(_board.mood);
                _board.SetMindIntent(intent);
                Debug.Log($"[Mind/Sim] {intent}");
                break;

            case MindMode.LLM:
                TickLLM();
                break;
        }
    }

    /*
        // 1. Drain any response the bridge has waiting.
        // 2. Build a fresh snapshot and hand it off. If the bridge is still
        //    waiting on the backend, it will drop this tick and keep polling.
    */
    void TickLLM()
    {
        if (_bridge == null || _snapshotManager == null)
        {
            Debug.LogWarning("[PeriodicMind] LLM tick skipped: missing AgentMindBridge or SnapshotManager.");
            return;
        }

        if (_bridge.TryConsume(out var intent))
            ApplyLLMResponse(intent);

        string requestId = $"t{_tickCounter++:X8}";
        _lastRequestId   = requestId;
        string json      = _snapshotManager.BuildJson(requestId);
        if (logLLMTicks)
            Debug.Log($"[PeriodicMind] LLM tick requestId={requestId} bytes={json.Length}");
        _bridge.SendTick(_board.CreatureId, json);

        LogBridgeFailures();
    }

    void ApplyLLMResponse(AgentMindBridge.LLMIntent intent)
    {
        if (intent == null || string.IsNullOrWhiteSpace(intent.intent))
            return;

        string action = intent.intent.Trim().ToLowerInvariant();
        string targetKey = NormalizeKey(intent.targetKey);
        Vector3 destination = intent.destination;
        Transform resolvedTarget = null;

        if (!string.IsNullOrWhiteSpace(targetKey))
        {
            if (_targetRegistry == null || !_targetRegistry.TryResolve(targetKey, out resolvedTarget))
            {
                Report("", action, "rejected", $"unknown target '{targetKey}'");
                Debug.LogWarning($"[Mind/LLM] rejected {action}: unknown target '{targetKey}'");
                return;
            }

            if (action == "go_to")
                destination = resolvedTarget.position;
        }

        if (action == "follow" && resolvedTarget == null)
        {
            Report("", action, "rejected", "follow requires a named target");
            Debug.LogWarning("[Mind/LLM] rejected follow: missing target");
            return;
        }

        if (action == "go_to" && resolvedTarget == null && destination == Vector3.zero)
        {
            Report("", action, "rejected", "go_to requires a target or non-zero destination");
            Debug.LogWarning("[Mind/LLM] rejected go_to: missing target and destination");
            return;
        }

        var previous = _board.MindIntent;
        if (IsDuplicate(previous, action, targetKey, destination))
            return;

        if (previous.HasValue && !string.IsNullOrEmpty(previous.Value.CommandId))
            Report(
                previous.Value.CommandId,
                previous.Value.Intent,
                "cancelled",
                "replaced by newer LLM command",
                previous.Value.RequestId);

        string commandId = $"{_board.CreatureId}:{_commandCounter++:X8}";

        // LLM-only phase: do not let old tactical decisions mask accepted LLM commands.
        _board.ClearTacticalIntent();
        _board.followTarget = action == "follow" ? resolvedTarget : null;
        _board.SetMindIntent(action, destination, commandId, _lastRequestId, targetKey);

        Report(commandId, action, "accepted", "");
        Debug.Log($"[Mind/LLM] accepted {action} ({commandId})");
    }

    bool IsDuplicate(IntentMessage? current, string action, string targetKey, Vector3 destination)
    {
        if (!current.HasValue || !current.Value.IsActive) return false;

        var existing = current.Value;
        if (!string.Equals(existing.Intent, action, System.StringComparison.OrdinalIgnoreCase))
            return false;

        if (!string.Equals(NormalizeKey(existing.TargetKey), targetKey, System.StringComparison.OrdinalIgnoreCase))
            return false;

        return Vector3.SqrMagnitude(existing.DirectionHint - destination) < 0.01f;
    }

    static string NormalizeKey(string key) => string.IsNullOrWhiteSpace(key) ? "" : key.Trim();

    void LogBridgeFailures()
    {
        if (_bridge == null) return;

        int failed = _bridge.FailedTickCount;
        if (failed <= _lastObservedBridgeFailureCount) return;

        Debug.LogWarning($"[PeriodicMind] observed {failed - _lastObservedBridgeFailureCount} new LLM bridge failure(s); total={failed}");
        _lastObservedBridgeFailureCount = failed;
    }

    void Report(string commandId, string action, string status, string reason, string requestId = null)
    {
        if (_reporter == null || _board == null) return;

        _reporter.Report(new ActionReport
        {
            agent_id  = _board.CreatureId,
            commandId = commandId ?? "",
            requestId = requestId ?? _lastRequestId,
            action    = action ?? "",
            status    = status,
            reason    = reason ?? "",
            time      = Time.time,
        });
    }

    string SelectIntentLocal(MoodModel mood)
    {
        if (mood.fear > 0.7f)                                                return "flee";
        if (mood.curiosity > 0.6f && _board.playerInSight)                   return "investigate";
        if (_board.GetCurrentHunger() > 0.5f)                                return "wander";
        if (mood.social > 0.6f && mood.trust > 0.5f && _board.playerInSight) return "investigate";
        if (mood.energy < 0.3f)                                              return "idle";
        return "wander";
    }
}
