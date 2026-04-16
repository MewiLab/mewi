// PeriodicMind.cs  (Creature/Layers/Mind/)
//
// The "slow mind" — fires on a timer, updates mood, drives the Mind intent slot.
//
// In Simulated mode: rule-based mood + intent, fully local.
// In LLM mode:
//   1. Each tick — send a perception snapshot via AgentMindBridge.SendTick(_board)
//   2. Each tick — check AgentMindBridge.TryConsumeResponse() for a reply
//   3. On reply  — apply the LLMIntent to the blackboard (ONLY place MindIntent is written)
//   Mood decay runs every tick regardless so mood never freezes between LLM responses.
//
// PeriodicMind is the sole writer to CreatureBlackboard.SetMindIntent().
// AgentMindBridge reads the blackboard to build snapshots — it never writes it.

using System.Collections;
using UnityEngine;

public enum MindMode { Simulated, LLM }

public class PeriodicMind : MonoBehaviour
{
    // ─── Injected by CreatureController ──────────────────────────────────────
    CreatureBlackboard _board;
    CreatureConfig     _config;
    AgentMindBridge    _bridge;

    [Header("Mind Mode")]
    public MindMode mode = MindMode.Simulated;

    bool   _running;
    string _pendingId;   // requestId of the last tick sent; null when idle

    // ─────────────────────────────────────────────────────────────────────────
    //  INIT / LIFECYCLE
    // ─────────────────────────────────────────────────────────────────────────

    public void Init(CreatureBlackboard board, CreatureConfig config)
    {
        _board  = board;
        _config = config;
        _bridge = GetComponent<AgentMindBridge>();

        if (_bridge == null && mode == MindMode.LLM)
            Debug.LogWarning("[PeriodicMind] LLM mode requires AgentMindBridge on the same GameObject.");
    }

    public void StartThinking()
    {
        if (_running) return;
        _running = true;
        StartCoroutine(ThinkLoop());
    }

    public void StopThinking()
    {
        _running = false;
        StopAllCoroutines();
    }

    IEnumerator ThinkLoop()
    {
        while (_running)
        {
            // we can cache the obejct
            yield return new WaitForSecondsRealtime(_config.mindTickInterval);
            Think();
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  THINK  (called on timer — not every frame)
    // ─────────────────────────────────────────────────────────────────────────

    void Think()
    {
        UpdateMood();
        ResolveIntent();
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  MOOD  (always runs — keeps mood alive between LLM responses)
    // ─────────────────────────────────────────────────────────────────────────

    void UpdateMood()
    {
        switch (mode)
        {
            case MindMode.Simulated:
                UpdateMoodFull();
                break;
            case MindMode.LLM:
                // Full mood update will come from the LLM response eventually.
                // Decay-only ensures mood doesn't freeze while waiting.
                UpdateMoodDecayOnly();
                break;
        }
    }

    void UpdateMoodFull()
    {
        MoodModel mood = _board.mood;

        mood.fear  = Mathf.MoveTowards(mood.fear,  0.2f, _config.fearDecayRate);
        mood.trust = Mathf.MoveTowards(mood.trust, 0.3f, _config.trustDecayRate);

        string events = _board.GetRecentEventsSummary();
        if (events.Contains("startled"))  { mood.fear += 0.15f; mood.trust -= 0.1f; }
        if (events.Contains("fed") || events.Contains("food")) { mood.trust += 0.1f; mood.social += 0.05f; }

        if (_board.playerInSight && _board.closestPlayerDist < _config.personalSpaceRadius)
        {
            if (mood.trust < 0.4f) mood.fear   += 0.1f;
            else                   mood.social  += 0.05f;
        }

        mood.energy -= 0.02f;
        if (_board.GetCurrentHunger() > 0.7f) mood.energy -= 0.03f;
        mood.Clamp();
    }

    void UpdateMoodDecayOnly()
    {
        MoodModel mood = _board.mood;
        mood.fear  = Mathf.MoveTowards(mood.fear,  0.2f, _config.fearDecayRate);
        mood.trust = Mathf.MoveTowards(mood.trust, 0.3f, _config.trustDecayRate);
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

    // ─────────────────────────────────────────────────────────────────────────
    //  LLM TICK  (send + consume pattern)
    //
    //  Each Think() cycle:
    //    1. Check whether the previous tick got a response → apply to blackboard.
    //    2. Send a fresh tick regardless (always want the latest LLM read).
    //
    //  Sending a new tick replaces _pendingId, so stale responses are naturally
    //  discarded by TryConsumeResponse (latest-wins in v1).
    // ─────────────────────────────────────────────────────────────────────────

    void TickLLM()
    {
        if (_bridge == null) return;

        // 1. Consume response from previous tick (if arrived)
        if (_pendingId != null && _bridge.TryConsumeResponse(_pendingId, out var intent))
        {
            ApplyLLMResponse(intent);
            _pendingId = null;
        }

        // 2. Send a new tick — bridge reads the blackboard and builds the snapshot
        _pendingId = _bridge.SendTick(_board);
    }

    /// <summary>
    /// Apply a validated LLM response to the blackboard.
    /// This is the ONLY place SetMindIntent is called outside Simulated mode.
    /// </summary>
    void ApplyLLMResponse(AgentMindBridge.LLMIntent intent)
    {
        _board.followTarget = intent.target;
        _board.SetMindIntent(intent.intent, intent.destination);
        Debug.Log($"[Mind/LLM] applied: {intent.intent}");
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  LOCAL INTENT SELECTION  (Simulated mode only)
    // ─────────────────────────────────────────────────────────────────────────

    string SelectIntentLocal(MoodModel mood)
    {
        if (mood.fear > 0.7f)                                              return "flee";
        if (mood.curiosity > 0.6f && _board.playerInSight)                 return "investigate";
        if (_board.GetCurrentHunger() > 0.5f)                              return "wander";
        if (mood.social > 0.6f && mood.trust > 0.5f && _board.playerInSight) return "investigate";
        if (mood.energy < 0.3f)                                            return "idle";
        return "wander";
    }
}
