using System.Collections;
using UnityEngine;

/// <summary>
/// The "slow mind" — runs on a timer (every few seconds), not every frame.
/// Reads recent events and perception from blackboard, updates mood, produces intent.
///
/// MVP: rule-based mood shifts + simple intent selection.
/// Upgrade path: send blackboard summary to LLM backend, parse response into mood + intent.
///
/// Uses WaitForSecondsRealtime so it keeps ticking even if Time.timeScale changes.
/// </summary>
public class PeriodicMind : MonoBehaviour
{
    CreatureBlackBoard _board;
    CreatureConfig     _config;
    
    bool _running;
    public void Init(CreatureBlackBoard board, CreatureConfig config)
    {
        _board = board;
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
        //StopCoroutine(ThinkLoop());
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

    // TODO: Make this call the backend agent to think and make it not concurrency but async probabily
    // One "thought cycle." Reads blackboard state, updates mood, picks intent.
    // This runs on a slow timer — never blocks the main thread.
    void Think()
    {
        MoodModel mood = _board.mood;

        // ── 1. Mood decay toward neutral ──
        mood.fear  = Mathf.MoveTowards(mood.fear, 0.2f, _config.fearDecayRate);
        mood.trust = Mathf.MoveTowards(mood.trust, 0.3f, _config.trustDecayRate);

        // ── 2. React to recent events ──
        string summary = _board.GetRecentEventsSummary();

        if (summary.Contains("startled"))
        {
            mood.fear += 0.15f;
            mood.trust -= 0.1f;
        }

        if (summary.Contains("fed") || summary.Contains("food"))
        {
            mood.trust += 0.1f;
            mood.social += 0.05f;
        }

        // ── 3. React to current perception ──
        if (_board.playerInSight && _board.closestPlayerDist < _config.personalSpaceRadius)
        {
            // Someone is very close — if trust is low, get more fearful
            if (mood.trust < 0.4f)
                mood.fear += 0.1f;
            else
                mood.social += 0.05f;
        }

        // Energy drains slowly, hunger makes it worse
        mood.energy -= 0.02f;
        if (_board.GetCurrentHunger() > 0.7f)
            mood.energy -= 0.03f;

        mood.Clamp();

        // ── 4. Select intent based on mood ──
        string intent = SelectIntent(mood);
        _board.SetMindIntent(intent);

        Debug.Log($"[PeriodicMind] intent={intent} | {mood}");
    }

    // TODO: Replace this with LLM call for richer behavior.
    // MVP intent selection — simple priority rules based on mood.
    string SelectIntent(MoodModel mood)
    {
        // High fear → flee
        if (mood.fear > 0.7f)
            return "flee";

        // High curiosity + player visible → investigate
        if (mood.curiosity > 0.6f && _board.playerInSight)
            return "investigate";

        // Hungry → wander (looking for food)
        if (_board.GetCurrentHunger() > 0.5f)
            return "wander";

        // Social + trusting + player nearby → approach (future behavior)
        if (mood.social > 0.6f && mood.trust > 0.5f && _board.playerInSight)
            return "investigate"; // closest to "approach" in current FSM

        // Low energy → idle / rest
        if (mood.energy < 0.3f)
            return "idle";

        // Default: light wander
        return "wander";
    }
}
