using UnityEngine;

public enum LayerSource
{
    Mind = 0,
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
    /// LLM command correlation id. Empty for local/reflex/tactical intents.
    /// </summary>
    public string CommandId;

    /// <summary>
    /// Backend tick request that produced this command. Empty for local intents.
    /// </summary>
    public string RequestId;

    /// <summary>
    /// Original named target key from the backend, if any.
    /// </summary>
    public string TargetKey;

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
    public static IntentMessage Create(
        string intent,
        LayerSource source,
        float duration = -1f,
        Vector3 directionHint = default,
        string commandId = "",
        string requestId = "",
        string targetKey = "")
    {
        return new IntentMessage
        {
            Intent        = intent,
            Source        = source,
            SetTime       = Time.time,
            Duration      = duration,
            DirectionHint = directionHint,
            CommandId     = commandId ?? "",
            RequestId     = requestId ?? "",
            TargetKey     = targetKey ?? "",
        };
    }

    public override string ToString()
    {
        string dur = Duration < 0f ? "∞" : $"{TimeRemaining:F1}s";
        string target = string.IsNullOrEmpty(TargetKey) ? "" : $" -> {TargetKey}";
        return $"[{Source}] {Intent}{target} ({dur})";
    }
}
