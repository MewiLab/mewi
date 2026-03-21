using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Shared data bus — every layer reads/writes here, no layer talks to another directly.
///
/// UPGRADE from MVP:
///   Replaced flat `currentIntent` string + `reflexBlocksTactical` bool with three
///   typed IntentSlot? fields. Each layer owns exactly one slot. The output consumer
///   (animation, movement, Malbers bridge) calls ResolveActiveIntent() each frame
///   to get the single authoritative "what should I be doing."
///
///   Read order: reflexOverride → tacticalCurrent → mindSuggestion.
///   First non-null active slot wins. This is Brooks' subsumption (1986) expressed
///   as three named slots instead of a wire-suppression graph.
///
/// Ownership convention:
///   Perception  → writes: sensory fields (closestPlayer, heardSound, etc.)
///   Reflex      → writes: reflexOverride slot, gaze override
///   Tactical    → writes: tacticalCurrent slot; reads mindSuggestion
///   Mind        → writes: mindSuggestion slot, mood
///   Animation   → reads: ResolveActiveIntent(), gaze override
/// </summary>
public class CreatureBlackBoard : MonoBehaviour
{
    // ─────────────────────────────────────────────
    // INTENT SLOTS — the core of the typed-slot system
    // ─────────────────────────────────────────────
    //
    // Three nullable slots in priority order. Null = "this layer has nothing to say."
    // Struct + nullable avoids per-frame GC allocation (no class, no queue).
    //
    // Reflex:   auto-expires (flinch = 0.3s). When expired, falls through to tactical.
    // Tactical: indefinite duration, replaced on FSM state transition.
    // Mind:     indefinite duration, advisory — tactical reads and may adopt or ignore.

    [Header("Intent slots (read-only in Inspector)")]
    [SerializeField] string _debugReflexSlot   = "—";
    [SerializeField] string _debugTacticalSlot  = "—";
    [SerializeField] string _debugMindSlot      = "—";
    [SerializeField] string _debugResolved      = "—";

    IntentSlot? _reflexOverride;
    IntentSlot? _tacticalCurrent;
    IntentSlot? _mindSuggestion;

    /// <summary>Current reflex override, if active. Null when no reflex is firing.</summary>
    public IntentSlot? ReflexOverride  => _reflexOverride?.IsActive == true ? _reflexOverride : null;

    /// <summary>Current tactical behavior. Null only before first FSM transition.</summary>
    public IntentSlot? TacticalCurrent => _tacticalCurrent?.IsActive == true ? _tacticalCurrent : null;

    /// <summary>Latest mind suggestion. Null when mind hasn't produced anything yet.</summary>
    public IntentSlot? MindSuggestion  => _mindSuggestion?.IsActive == true ? _mindSuggestion : null;


    // ── Slot writers (each layer calls exactly one of these) ──

    /// <summary>
    /// Called by IReflex implementations when they fire.
    /// Duration is mandatory — reflexes must declare how long they last.
    /// </summary>
    public void SetReflexOverride(string intent, float duration, Vector3 directionHint = default)
    {
        _reflexOverride = IntentSlot.Create(intent, LayerSource.Reflex, duration, directionHint);
        LogEvent($"reflex: {intent} ({duration:F1}s)");
    }

    /// <summary>
    /// Called by CreatureBrain on FSM state transitions.
    /// Duration is -1 (indefinite) — tactical owns its slot until the next transition.
    /// </summary>
    public void SetTacticalCurrent(string intent, Vector3 directionHint = default)
    {
        _tacticalCurrent = IntentSlot.Create(intent, LayerSource.Tactical, -1f, directionHint);
    }

    /// <summary>
    /// Called by PeriodicMind when a think cycle completes.
    /// This is advisory — CreatureBrain reads it and decides whether to adopt.
    /// </summary>
    public void SetMindSuggestion(string intent)
    {
        _mindSuggestion = IntentSlot.Create(intent, LayerSource.Mind, -1f);
        LogEvent($"mind suggests: {intent}");
    }

    /// <summary>
    /// Called by CreatureBrain after it reads and processes the mind suggestion.
    /// Prevents the same suggestion from being re-evaluated every tick.
    /// </summary>
    public void ConsumeMindSuggestion()
    {
        _mindSuggestion = null;
    }

    /// <summary>
    /// Force-clear the reflex slot. Called when a reflex explicitly ends early
    /// (e.g., avoidance reflex clears when threat leaves range).
    /// Normally not needed — reflexes auto-expire via duration.
    /// </summary>
    public void ClearReflexOverride()
    {
        _reflexOverride = null;
    }


    // ── Arbitration — the single read point for output consumers ──

    /// <summary>
    /// Returns the highest-priority active intent. This is the ONE method that
    /// the animation/movement system calls each frame.
    ///
    /// Read order: reflex → tactical → mind → fallback idle.
    /// First non-null active slot wins.
    ///
    /// This implements Brooks' subsumption: reflex suppresses tactical suppresses mind,
    /// but none of them modify each other — the lower-priority slot is still there
    /// when the higher one expires.
    /// </summary>
    public IntentSlot ResolveActiveIntent()
    {
        // Check reflex — auto-expires based on duration
        if (_reflexOverride.HasValue && _reflexOverride.Value.IsActive)
            return _reflexOverride.Value;

        // Reflex expired? Clear it so we don't re-check a stale struct
        if (_reflexOverride.HasValue && !_reflexOverride.Value.IsActive)
            _reflexOverride = null;

        // Check tactical — indefinite duration, always active until replaced
        if (_tacticalCurrent.HasValue && _tacticalCurrent.Value.IsActive)
            return _tacticalCurrent.Value;

        // Check mind — shouldn't normally reach here (tactical should always have something)
        if (_mindSuggestion.HasValue && _mindSuggestion.Value.IsActive)
            return _mindSuggestion.Value;

        // Fallback: nothing is set yet (first frame, or everything cleared)
        return IntentSlot.Create("idle", LayerSource.Tactical);
    }

    /// <summary>
    /// Is a reflex currently overriding tactical? Convenience check for layers
    /// that need to know if they're being suppressed.
    /// </summary>
    public bool IsReflexActive => _reflexOverride.HasValue && _reflexOverride.Value.IsActive;


    // ─────────────────────────────────────────────
    // LEGACY COMPAT — kept during migration, will remove
    // ─────────────────────────────────────────────

    public float hunger = 0.1f;

    public void SetCurrentHunger(float h) => hunger = h;
    public float GetCurrentHunger() => hunger;


    // ─────────────────────────────────────────────
    // EVENT LOG
    // ─────────────────────────────────────────────

    public Queue<string> recent_events = new Queue<string>();

    public void LogEvent(string e)
    {
        recent_events.Enqueue(e);
        if (recent_events.Count > 10) recent_events.Dequeue();
    }

    public string GetRecentEventsSummary()
    {
        if (recent_events.Count == 0) return "nothing notable";
        return string.Join("; ", recent_events);
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
    // REFLEX — gaze override (not an intent, a parallel channel)
    // ─────────────────────────────────────────────

    [HideInInspector] public bool    isStartled;
    [HideInInspector] public float   startleEndTime;
    [HideInInspector] public Vector3 gazeOverrideTarget;
    [HideInInspector] public bool    hasGazeOverride;


    // ─────────────────────────────────────────────
    // MOOD — written by PeriodicMind
    // ─────────────────────────────────────────────

    public MoodModel   mood   = new MoodModel();
    public HealthModel health = new HealthModel();


    // ─────────────────────────────────────────────
    // FRAME MANAGEMENT
    // ─────────────────────────────────────────────

    /// <summary>
    /// Reset per-frame transient data. Called at start of each tick.
    /// NOTE: Intent slots are NOT cleared here — they persist across frames.
    /// Only per-frame sensor data is cleared.
    /// </summary>
    public void ClearFrameFlags()
    {
        sensorEvents.Clear();
        hasGazeOverride       = false;
        playerApproachingFast = false;
    }

    /// <summary>Update Inspector debug strings. Call at end of frame.</summary>
    public void UpdateDebugDisplay()
    {
        _debugReflexSlot  = ReflexOverride.HasValue  ? ReflexOverride.Value.ToString()  : "—";
        _debugTacticalSlot = TacticalCurrent.HasValue ? TacticalCurrent.Value.ToString() : "—";
        _debugMindSlot    = MindSuggestion.HasValue  ? MindSuggestion.Value.ToString()  : "—";

        var resolved = ResolveActiveIntent();
        _debugResolved = resolved.ToString();
    }
}
