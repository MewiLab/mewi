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
public enum MindMode { Simulated, LLM }

public class PeriodicMind : MonoBehaviour
{
    CreatureBlackboard _board;
    CreatureConfig     _config;
    CreatureAgent      _creatureAgent;
    
    [Header("Mind Mode")]
    public MindMode mode = MindMode.Simulated;

    bool _running;
    bool _waitingForLLM;  // guard against re-entrant calls while tick is in-flight

    public void Init(CreatureBlackboard board, CreatureConfig config)
    {
        _board = board;
        _config = config;
        _creatureAgent = GetComponent<CreatureAgent>();
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

    void Think()
    {
        ResolveMood();
        ResolveIntent();
    }

    void ResolveMood()
    {
        switch (mode)
        {
            case MindMode.Simulated:
                UpdateMoodLocal();
                break;
            case MindMode.LLM:
                // LLM response will include mood shifts — applied in RequestLLMIntent callback
                // Still run local decay as baseline so mood doesn't freeze between LLM ticks
                UpdateMoodDecayOnly();
                break;
        }
    }

    void UpdateMoodLocal()
    {
        MoodModel mood = _board.mood;
        
        // Decay toward neutral
        mood.fear  = Mathf.MoveTowards(mood.fear, 0.2f, _config.fearDecayRate);
        mood.trust = Mathf.MoveTowards(mood.trust, 0.3f, _config.trustDecayRate);

        // React to events
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

        // React to perception
        if (_board.playerInSight && _board.closestPlayerDist < _config.personalSpaceRadius)
        {
            if (mood.trust < 0.4f) mood.fear += 0.1f;
            else mood.social += 0.05f;
        }

        mood.energy -= 0.02f;
        if (_board.GetCurrentHunger() > 0.7f) mood.energy -= 0.03f;
        mood.Clamp();
    }

    void UpdateMoodDecayOnly()
    {
        MoodModel mood = _board.mood;
        mood.fear  = Mathf.MoveTowards(mood.fear, 0.2f, _config.fearDecayRate);
        mood.trust = Mathf.MoveTowards(mood.trust, 0.3f, _config.trustDecayRate);
        mood.energy -= 0.02f;
        mood.Clamp();
    }

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
                RequestLLMIntent();
                break;
        }
    }

    string SelectIntentLocal(MoodModel mood)
    {
        if (mood.fear > 0.7f) return "flee";
        if (mood.curiosity > 0.6f && _board.playerInSight) return "investigate";
        if (_board.GetCurrentHunger() > 0.5f) return "wander";
        if (mood.social > 0.6f && mood.trust > 0.5f && _board.playerInSight) return "investigate";
        if (mood.energy < 0.3f) return "idle";
        return "wander";
    }

    void RequestLLMIntent()
    {
        if (_waitingForLLM) return;

        if (_creatureAgent == null)
        {
            Debug.LogWarning("[Mind/LLM] No CreatureAgent found — falling back to local");
            UpdateMoodLocal();
            _board.SetMindIntent(SelectIntentLocal(_board.mood));
            return;
        }

        // CreatureAgent sends the full perception snapshot to /agent/tick.
        // The backend runs LangGraph and calls back to AgentBridge to execute the action.
        // No response parsing needed here.
        _waitingForLLM = true;
        _creatureAgent.TriggerTick();
        _waitingForLLM = false;

        // Run local mood decay while waiting for backend to respond.
        UpdateMoodDecayOnly();
    }

}
