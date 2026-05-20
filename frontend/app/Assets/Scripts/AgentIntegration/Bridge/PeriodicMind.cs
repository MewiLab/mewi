/*
    The "slow mind": fires on a timer, updates mood, drives the Mind intent slot.

    Modes:
      Simulated — rule-based mood + intent, fully local.
      LLM       — every tick:
                    1. consume any pending response plan from the bridge
                    2. build a fresh snapshot via SnapshotManager
                    3. hand it to AgentNetworkManager.SendTick when no plan is running
                  mood decay still runs each tick so it never freezes between replies.

    Responsibility split (Option A — orchestrator-knows-all):
      PeriodicMind    — WHEN  (timer, owns the loop)
      SnapshotManager — WHAT  (channel registry → JSON)
      AgentNetworkManager — HOW   (websocket + parse, async)

    PeriodicMind is the sole writer to CreatureBlackboard's mind plan queue.
*/
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public enum MindMode { Simulated, LLM }

[RequireComponent(typeof(AgentNetworkManager))]
public class PeriodicMind : MonoBehaviour
{
    CreatureBlackboard _board;
    CreatureConfig     _config;
    [SerializeField] AgentNetworkManager _bridge;
    [SerializeField] SnapshotManager _snapshotManager;
    [SerializeField] CreatureWorker _worker;

    [Header("Mind Mode")]
    public MindMode mode = MindMode.Simulated;

    [Header("Debug")]
    [SerializeField] bool logLLMTicks = true;

    bool _running;
    int  _tickCounter;
    int  _commandCounter;
    int  _lastObservedBridgeFailureCount;
    string _lastRequestId = "";
    PlanExecutionReport _pendingPlanReport;

    public void Init(CreatureBlackboard board, CreatureConfig config)
    {
        _board  = board;
        _config = config;
        if (_bridge == null)          _bridge          = GetComponent<AgentNetworkManager>();
        if (_snapshotManager == null) _snapshotManager = GetComponent<SnapshotManager>();
        if (_worker == null)          _worker          = GetComponent<CreatureWorker>();

        if (logLLMTicks)
        {
            string baseUrl = _bridge != null && _bridge.config != null ? _bridge.config.baseUrl : "(missing config)";
            string tickInterval = _config != null ? _config.mindTickInterval.ToString("F1") : "(missing config)";
            Debug.Log($"[PeriodicMind] init mode={mode} tickInterval={tickInterval}s backend={baseUrl}");
        }

        if (mode == MindMode.LLM)
        {
            if (_bridge == null)
                Debug.LogError("[PeriodicMind] LLM mode needs AgentNetworkManager on the same GameObject.");
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
        // 1. Drain any completed backend plan.
        // 2. Let the motor finish the queued plan before asking the backend
        //    for another one.
        // 3. Build a fresh snapshot and hand it off. If the bridge is still
        //    waiting on the backend, it will drop this tick and keep polling.
    */
    void TickLLM()
    {
        if (_bridge == null || _snapshotManager == null)
        {
            Debug.LogWarning("[PeriodicMind] LLM tick skipped: missing AgentNetworkManager or SnapshotManager.");
            return;
        }

        if (_bridge.TryConsumePlan(out var plan))
            ApplyLLMPlan(plan);

        if (_board.TryPopPlanExecutionReport(out var completedReport))
            _pendingPlanReport = completedReport;

        bool bodyBusy = _worker != null && _worker.IsBusy;
        if (_board.HasMindPlan || bodyBusy)
        {
            if (logLLMTicks)
            {
                IntentMessage? current = _board.MindIntent;
                string currentIntent = current.HasValue ? current.Value.Intent : "none";
                Debug.Log($"[PeriodicMind] waiting for local plan current={currentIntent} queued={_board.QueuedMindIntentCount} bodyBusy={bodyBusy}");
            }
            LogBridgeFailures();
            return;
        }

        string requestId = $"t{_tickCounter++:X8}";
        _lastRequestId   = requestId;
        SnapshotPayload payload = _snapshotManager.BuildPayload(requestId);
        if (logLLMTicks)
            Debug.Log($"[PeriodicMind] LLM tick requestId={requestId} previousReport={(_pendingPlanReport != null ? _pendingPlanReport.status : "none")}");
        if (_bridge.SendTick(_board.CreatureId, payload, _pendingPlanReport))
            _pendingPlanReport = null;

        LogBridgeFailures();
    }

    void ApplyLLMPlan(AgentNetworkManager.LLMPlan plan)
    {
        if (plan == null || plan.steps == null || plan.steps.Length == 0)
            return;

        string requestId = string.IsNullOrWhiteSpace(plan.requestId) ? _lastRequestId : plan.requestId;
        var messages = new List<IntentMessage>(plan.steps.Length);

        for (int i = 0; i < plan.steps.Length; i++)
        {
            var step = plan.steps[i];
            if (!TryBuildMindIntent(step, requestId, out var message, out string rejectedReason))
            {
                Debug.LogWarning($"[Mind/LLM] rejected plan step {i}: {rejectedReason}");
                continue;
            }

            messages.Add(message);
        }

        if (messages.Count == 0)
        {
            if (logLLMTicks)
                Debug.LogWarning("[Mind/LLM] backend plan had no executable steps");
            return;
        }

        _board.ReplaceMindPlan(messages);

        if (logLLMTicks)
            Debug.Log($"[Mind/LLM] queued {messages.Count} step(s): {PlanSummary(messages)}");
    }

    bool TryBuildMindIntent(
        AgentNetworkManager.LLMIntent step,
        string requestId,
        out IntentMessage message,
        out string rejectedReason)
    {
        message = default;
        rejectedReason = "";

        if (step == null)
        {
            rejectedReason = "missing step";
            return false;
        }

        string action = NormalizeAction(step.intent);
        string targetKey = NormalizeKey(step.targetKey);

        if (string.IsNullOrWhiteSpace(action))
        {
            rejectedReason = "missing action";
            return false;
        }

        string commandId = $"{_board.CreatureId}:{_commandCounter++:X8}";
        message = IntentMessage.Create(
            action,
            LayerSource.Mind,
            -1f,
            step.destination,
            commandId,
            requestId,
            targetKey);
        return true;
    }

    static string NormalizeAction(string action)
    {
        if (string.IsNullOrWhiteSpace(action)) return "";
        action = action.Trim().ToLowerInvariant();
        if (action == "wait") return "idle";
        if (action == "stop") return "stop_moving";
        if (action == "move") return "go_to";
        return action;
    }

    static string NormalizeKey(string key) => string.IsNullOrWhiteSpace(key) ? "" : key.Trim();

    static string PlanSummary(List<IntentMessage> messages)
    {
        var parts = new List<string>(messages.Count);
        foreach (var message in messages)
        {
            string target = string.IsNullOrWhiteSpace(message.TargetKey) ? "" : $"->{message.TargetKey}";
            parts.Add($"{message.Intent}{target}");
        }
        return string.Join(", ", parts);
    }

    void LogBridgeFailures()
    {
        if (_bridge == null) return;

        int failed = _bridge.FailedTickCount;
        if (failed <= _lastObservedBridgeFailureCount) return;

        Debug.LogWarning($"[PeriodicMind] observed {failed - _lastObservedBridgeFailureCount} new LLM bridge failure(s); total={failed}");
        _lastObservedBridgeFailureCount = failed;
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
