using System.Collections;
using UnityEngine;

/// <summary>
/// The "slow mind" — runs on a timer (every few seconds), not every frame.
/// Reads recent events and perception from blackboard, updates mood, produces intent.
///
/// UPGRADE from MVP:
///   Replaced _brain.EnqueueIntentQueue(intent) with board.SetMindSuggestion(intent).
///
///   This means:
///   - Mind no longer needs a reference to CreatureBrain. Layers don't talk to each
///     other — they only talk through the blackboard. (Hayes-Roth, 1985)
///   - The suggestion is advisory. CreatureBrain reads it on its next tick and
///     decides whether to adopt it based on its interrupt threshold.
///   - If a reflex fired while we were thinking, our suggestion still lands in the
///     slot — but CreatureBrain won't read it until the reflex expires and tactical
///     resumes. By then, the suggestion may be stale. That's OK — the next think
///     cycle will produce a fresh one. (Park et al. 2023 — cached plan continuation)
///
/// MVP: rule-based mood shifts + simple intent selection.
/// Upgrade path: send blackboard summary to LLM backend, parse response into mood + intent.
/// </summary>
public class PeriodicMind : MonoBehaviour
{
    CreatureBlackBoard _board;
    CreatureConfig     _config;

    bool _running;

    /// <summary>
    /// CHANGE from MVP: No longer takes CreatureBrain reference.
    /// Mind → Blackboard → Brain. No direct coupling.
    /// </summary>
    public void Init(CreatureBlackBoard board, CreatureConfig config)
    {
        _board  = board;
        _config = config;
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
            yield return new WaitForSecondsRealtime(_config.mindTickInterval);
            Think();
        }
    }

    /// <summary>
    /// One "thought cycle." Reads blackboard state, updates mood, posts suggestion.
    ///
    /// TODO: Replace rule-based logic with async backend call:
    ///   1. Serialize blackboard snapshot (mood, recent events, perception summary)
    ///   2. POST to FastAPI /think endpoint
    ///   3. Parse response intent + mood deltas
    ///   4. Apply mood deltas, write suggestion to slot
    ///   The coroutine-based structure already supports this — just yield the HTTP call.
    /// </summary>
    void Think()
    {
        MoodModel mood = _board.mood;

        // ── 1. Mood decay toward neutral ──
        mood.fear   = Mathf.MoveTowards(mood.fear,  0.2f, _config.fearDecayRate);
        mood.trust  = Mathf.MoveTowards(mood.trust, 0.3f, _config.trustDecayRate);

        // ── 2. React to recent events ──
        string summary = _board.GetRecentEventsSummary();

        if (summary.Contains("startled"))
        {
            mood.fear  += 0.15f;
            mood.trust -= 0.1f;
        }

        if (summary.Contains("fed") || summary.Contains("food"))
        {
            mood.trust  += 0.1f;
            mood.social += 0.05f;
        }

        // ── 3. React to current perception ──
        if (_board.playerInSight && _board.closestPlayerDist < _config.personalSpaceRadius)
        {
            if (mood.trust < 0.4f)
                mood.fear += 0.1f;
            else
                mood.social += 0.05f;
        }

        mood.energy -= 0.02f;
        if (_board.GetCurrentHunger() > 0.7f)
            mood.energy -= 0.03f;

        mood.Clamp();

        // ── 4. Select intent and post as suggestion ──
        string intent = SelectIntent(mood);

        // Write to mind suggestion slot — advisory, not authoritative.
        // CreatureBrain will read this and decide whether to adopt.
        _board.SetMindSuggestion(intent);

        Debug.Log($"[PeriodicMind] suggests={intent} | {mood}");
    }

    /// <summary>
    /// MVP intent selection — simple priority rules based on mood.
    /// Replace this with LLM call for richer behavior.
    /// </summary>
    string SelectIntent(MoodModel mood)
    {
        if (mood.fear > 0.7f)
            return "flee";

        if (mood.curiosity > 0.6f && _board.playerInSight)
            return "investigate";

        if (_board.GetCurrentHunger() > 0.5f)
            return "wander";

        if (mood.social > 0.6f && mood.trust > 0.5f && _board.playerInSight)
            return "investigate";

        if (mood.energy < 0.3f)
            return "idle";

        return "wander";
    }
}
