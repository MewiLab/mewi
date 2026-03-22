using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Shared data bus using Brooks' Subsumption Architecture. 
/// Layers read/write to typed Intent slots in a fixed priority: Reflex (highest) -> Tactical -> Mind (lowest).
/// </summary>
public class CreatureBlackBoard : MonoBehaviour
{
    public string currentIntent = "idle";
    public float  hunger = 0.1f;

    public Queue<string> recent_events = new Queue<string>();

    public void SetCurrentIntent(string newIntent) => currentIntent = newIntent;
    public string GetCurrentIntent() => currentIntent;

    public void SetCurrentHunger(float h) => hunger = h;
    public float GetCurrentHunger() => hunger;

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

    public MoodModel mood     = new MoodModel();
    public HealthModel health = new HealthModel(); // just a dummy

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
