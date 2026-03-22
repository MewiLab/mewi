using System.Collections;
using UnityEngine;
using Newtonsoft.Json;
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
    CreatureBlackBoard _board;
    CreatureConfig     _config;
    
    [Header("Mind Mode")]
    public MindMode mode = MindMode.Simulated;

    bool _running;
    bool _waitingForLLM;

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

    async void RequestLLMIntent()
    {
        if (_waitingForLLM) return;
        _waitingForLLM = true;

        string snapshot = BuildSnapshot();
        string response = await CreatureAgent.PostAsync(snapshot);
        _waitingForLLM = false;

        if (response == null)
        {
            Debug.LogWarning("[Mind/LLM] Backend failed, falling back to local");
            UpdateMoodLocal();
            _board.SetMindIntent(SelectIntentLocal(_board.mood));
            return;
        }

        var parsed = Newtonsoft.Json.JsonConvert.DeserializeObject<LLMResponse>(response);
        ExecuteLLMActions(parsed);
    }

    void ExecuteLLMActions(LLMResponse response)
    {
        ApplyLLMMood(response.mood);

        if (response.actions == null || response.actions.Count == 0)
        {
            Debug.LogWarning("[Mind/LLM] No actions returned, falling back to local");
            _board.SetMindIntent(SelectIntentLocal(_board.mood));
            return;
        }

        foreach (var action in response.actions)
        {
            switch (action.function)
            {
                case "set_intent":
                    if (action.args.TryGetValue("intent", out var intent))
                        _board.SetMindIntent(intent);
                    break;

                case "play_action":
                    if (action.args.TryGetValue("action_id", out var idStr) && int.TryParse(idStr, out var id))
                        _board.pendingActionId = id; // add this field to blackboard
                    break;

                case "log_event":
                    if (action.args.TryGetValue("message", out var msg))
                        _board.LogEvent(msg);
                    break;

                default:
                    Debug.LogWarning($"[Mind/LLM] Unknown function: {action.function}");
                    break;
            }
        }

        if (response.reasoning != null)
            Debug.Log($"[Mind/LLM] reasoning: {response.reasoning}");
    }

    [System.Serializable]
    public class MindSnapshot
    {
        public MoodModel mood;
        public float hunger;
        public string events;
        public bool playerInSight;
        public float playerDist;
    }

    string BuildSnapshot()
    {
        var snapshot = new MindSnapshot
        {
            mood = _board.mood,
            hunger = _board.GetCurrentHunger(),
            events = _board.GetRecentEventsSummary(),
            playerInSight = _board.playerInSight,
            playerDist = _board.closestPlayerDist
        };
        return Newtonsoft.Json.JsonConvert.SerializeObject(snapshot);
    }

    void ApplyLLMMood(MoodUpdate moodUpdate)
    {
        if (moodUpdate == null) return;
        MoodModel mood = _board.mood;
        mood.fear      = Mathf.Clamp01(moodUpdate.fear);
        mood.trust     = Mathf.Clamp01(moodUpdate.trust);
        mood.curiosity = Mathf.Clamp01(moodUpdate.curiosity);
        mood.social    = Mathf.Clamp01(moodUpdate.social);
        mood.energy    = Mathf.Clamp01(moodUpdate.energy);
    }
}
