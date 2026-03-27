using UnityEngine;

public enum LayerSource
{
    Mind     = 0,
    Tactical = 1,
    Reflex   = 2,
}

public struct IntentMessage
{
    [Tooltip("e.g. 'flinch', 'wander', 'flee', 'eat'")]
    public string Intent;  

    [Tooltip("Which layer generated this intent")]
    public LayerSource Source;  

    [Tooltip("Time.time when this intent was created")]
    public float SetTime; 

    /// <summary>
    /// How long this slot stays active. Negative = indefinite (tactical, mind).
    /// Positive = auto-expires after this many seconds (reflex).
    /// </summary>
    public float Duration;
    
    /// <summary>
    /// A spatial hint for the motor (e.g., where to look, where to move, where to flee from).
    /// </summary>
    public Vector3 DirectionHint; 

    /// <summary>
    /// Is this slot still active? Checks expiry if duration is positive.
    /// </summary>
    public bool IsActive => Duration < 0f || (Time.time - SetTime) < Duration; 
    
    /// <summary>
    /// How many seconds remain before this slot expires. -1 if indefinite.
    /// </summary>
    public float TimeRemaining =>
        Duration < 0f ? -1f : Mathf.Max(0f, Duration - (Time.time - SetTime)); 

    /// <summary>
    /// Factory method to cleanly generate an IntentMessage.
    /// </summary>
    public static IntentMessage Create(string intent, LayerSource source, float duration = -1f, Vector3 directionHint = default)
    {
        return new IntentMessage
        {
            Intent        = intent,
            Source        = source,
            SetTime       = Time.time,
            Duration      = duration,
            DirectionHint = directionHint,
        };
    }

    public override string ToString()
    {
        string dur = Duration < 0f ? "∞" : $"{TimeRemaining:F1}s";
        return $"[{Source}] {Intent} ({dur})";
    }
}