using UnityEngine;

/// <summary>
/// Which layer produced this intent. Fixed priority order:
/// Reflex (highest) > Tactical > Mind (lowest).
///
/// Integer values encode priority — higher = more urgent.
/// This means you can compare: (LayerSource.Reflex > LayerSource.Mind) == true.
/// </summary>
public enum LayerSource
{
    Mind     = 0,
    Tactical = 1,
    Reflex   = 2,
}

/// <summary>
/// A single intent slot on the blackboard. Nullable via IntentSlot? (it's a struct).
///
/// Each layer owns exactly one slot. The animation/movement system reads all slots
/// top-down (highest priority first) and takes the first active one.
///
/// Struct (not class) to avoid GC allocation on every write. Stored as Nullable<IntentSlot>
/// on the blackboard — null means "this layer has nothing to say."
///
/// Reference: Brooks' subsumption (1986) — lower layers suppress higher layers.
/// The slot system is a minimal implementation of suppression: when reflexOverride
/// is non-null, it suppresses tacticalCurrent without modifying it.
/// </summary>
public struct IntentSlot
{
    /// <summary>The behavior tag this slot requests (e.g., "flinch", "wander", "flee").</summary>
    public string intent;

    /// <summary>Which layer set this slot. Used for debugging and Inspector display.</summary>
    public LayerSource source;

    /// <summary>Time.time when this slot was written. Used for expiry checks.</summary>
    public float setTime;

    /// <summary>
    /// How long this slot stays active. Negative = indefinite (tactical, mind).
    /// Positive = auto-expires after this many seconds (reflex).
    /// </summary>
    public float duration;

    /// <summary>Optional: direction or target associated with this intent.</summary>
    public Vector3 directionHint;

    /// <summary>Is this slot still active? Checks expiry if duration is positive.</summary>
    public bool IsActive => duration < 0f || (Time.time - setTime) < duration;

    /// <summary>How many seconds remain before this slot expires. -1 if indefinite.</summary>
    public float TimeRemaining =>
        duration < 0f ? -1f : Mathf.Max(0f, duration - (Time.time - setTime));

    /// <summary>Create a new intent slot stamped with the current time.</summary>
    public static IntentSlot Create(string intent, LayerSource source, float duration = -1f, Vector3 directionHint = default)
    {
        return new IntentSlot
        {
            intent        = intent,
            source        = source,
            setTime       = Time.time,
            duration      = duration,
            directionHint = directionHint,
        };
    }

    public override string ToString()
    {
        string dur = duration < 0f ? "∞" : $"{TimeRemaining:F1}s";
        return $"[{source}] {intent} ({dur})";
    }
}
