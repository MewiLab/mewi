using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Shared data bus — every layer reads/writes here, no layer talks to another directly.
/// 
/// Ownership convention:
///   Perception  → writes: sensory fields (closestPlayer, heardSound, etc.)
///   Reflex      → writes: reflex override flags (isStartled, gazeOverrideTarget)
///   Tactical    → writes: currentIntent (via intent queue from Mind)
///   Mind        → writes: mood, trust, curiosity (slow update)
///   Animation   → reads only (drives Malbers / Animator)
/// </summary>
public class CreatureBlackBoard : MonoBehaviour
{
    // ─────────────────────────────────────────────
    // EXISTING — your original fields, unchanged
    // ─────────────────────────────────────────────
    
    string _currentIntent = "idle";
    float  _hunger = 0.1f;

    public Queue<string> recent_events = new Queue<string>();

    public void SetCurrentIntent(string newIntent) => _currentIntent = newIntent;
    public string GetCurrentIntent() => _currentIntent;

    public void SetCurrentHunger(float h) => _hunger = h;
    public float GetCurrentHunger() => _hunger;

    public void LogEvent(string e)
    {
        recent_events.Enqueue(e);
        if (recent_events.Count > 10) recent_events.Dequeue();
    }

    // ─────────────────────────────────────────────
    // PERCEPTION — written by CreaturePerception
    // ─────────────────────────────────────────────

    [HideInInspector] public Transform closestPlayer;
    [HideInInspector] public float     closestPlayerDist = Mathf.Infinity;
    [HideInInspector] public Vector3   lastHeardSoundDir;
    [HideInInspector] public float     lastHeardSoundTime = -999f;
    [HideInInspector] public bool      playerInSight;
    [HideInInspector] public bool      playerApproachingFast;

    /// <summary>Recent sensory events for this frame, cleared each tick.</summary>
    public List<SensoryEvent> sensorEvents = new List<SensoryEvent>();

    // ─────────────────────────────────────────────
    // REFLEX — written by ReflexRunner
    // ─────────────────────────────────────────────

    [HideInInspector] public bool    isStartled;
    [HideInInspector] public float   startleEndTime;
    [HideInInspector] public Vector3 gazeOverrideTarget;
    [HideInInspector] public bool    hasGazeOverride;
    [HideInInspector] public bool    reflexBlocksTactical;  // reflex wants to override brain

    // ─────────────────────────────────────────────
    // MOOD — written by PeriodicMind
    // ─────────────────────────────────────────────

    public MoodModel mood = new MoodModel();

    // ─────────────────────────────────────────────
    // HELPERS
    // ─────────────────────────────────────────────

    /// <summary>
    /// Snapshot of recent events as a single string, for LLM prompt building.
    /// </summary>
    public string GetRecentEventsSummary()
    {
        if (recent_events.Count == 0) return "nothing notable";
        return string.Join("; ", recent_events);
    }

    /// <summary>Reset per-frame transient flags. Called at start of each tick.</summary>
    public void ClearFrameFlags()
    {
        sensorEvents.Clear();
        reflexBlocksTactical = false;
        hasGazeOverride      = false;
        playerApproachingFast = false;
    }
}
