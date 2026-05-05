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
public class PeriodicMind : MonoBehaviour
{
    CreatureBlackboard _board;
    CreatureConfig     _config;
    [SerializeField] AgentMindBridge _bridge;
    [SerializeField] SnapshotManager _snapshotManager;

    [Header("Mind Mode")]
    public MindMode mode = MindMode.Simulated;

    bool _running;
    int  _tickCounter;

    public void Init(CreatureBlackboard board, CreatureConfig config)
    {
        _board  = board;
        _config = config;
        if (_bridge == null)          _bridge          = GetComponent<AgentMindBridge>();
        if (_snapshotManager == null) _snapshotManager = GetComponent<SnapshotManager>();

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
        // 2. Build a fresh snapshot and hand it off — the bridge cancels its
        //    in-flight request, so latest-wins is enforced at the transport layer.
    */
    void TickLLM()
    {
        if (_bridge == null || _snapshotManager == null) return;

        if (_bridge.TryConsume(out var intent))
            ApplyLLMResponse(intent);

        string requestId = $"t{_tickCounter++:X8}";
        string json      = _snapshotManager.BuildJson(requestId);
        _bridge.SendTick(json);
    }

    void ApplyLLMResponse(AgentMindBridge.LLMIntent intent)
    {
        _board.followTarget = intent.target;
        _board.SetMindIntent(intent.intent, intent.destination);
        Debug.Log($"[Mind/LLM] applied: {intent.intent}");
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
