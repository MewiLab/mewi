using System;
using System.Collections.Generic;

/// <summary>
/// Data contract for LLM backend responses.
/// The backend returns a sequence of actions (function calls) for the creature to execute.
/// </summary>
[Serializable]
public class LLMResponse
{
    // ── Mood update (optional — backend may or may not adjust mood) ──
    public MoodUpdate mood;

    // ── Ordered list of actions the LLM wants executed ──
    public List<LLMAction> actions;

    // ── Debug ──
    public string reasoning;
}

[Serializable]
public class MoodUpdate
{
    public float fear;
    public float trust;
    public float curiosity;
    public float social;
    public float energy;
}

[Serializable]
public class LLMAction
{
    public string function;             // "set_intent", "play_action", "log_event", "set_mood", etc.
    public Dictionary<string, string> args;  // flexible key-value params
}




// Example
// {
//   "mood": {
//     "fear": 0.1,
//     "trust": 0.7,
//     "curiosity": 0.8,
//     "social": 0.5,
//     "energy": 0.6
//   },
//   "actions": [
//     { "function": "set_intent", "args": { "intent": "investigate" } },
//     { "function": "play_action", "args": { "action_id": "302" } },
//     { "function": "log_event", "args": { "message": "curious about player, sniffing" } }
//   ],
//   "reasoning": "player nearby, trust high, investigate and sniff"
// }