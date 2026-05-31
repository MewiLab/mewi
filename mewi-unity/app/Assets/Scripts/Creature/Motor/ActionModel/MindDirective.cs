using UnityEngine;

/// <summary>
/// A long-lived, high-level directive authored by the slow mind (EXPLORE,
/// SEEK_FOOD, …). It is NOT a body action. The worker orchestrates it by asking
/// <see cref="CatBehaviorFSM.TryNextAction"/> for one low-level action at a time
/// until <see cref="ExpiresAt"/> (the TTL), then flushes a
/// <see cref="PlanExecutionReport"/> so the slow mind can re-bias.
///
/// TTL is set to the cat's mind-tick interval so directive lifetime and snapshot
/// cadence stay in lockstep.
/// </summary>
public struct MindDirective
{
    public string Intent;     // EXPLORE, SEEK_FOOD, INVESTIGATE, …
    public string TargetKey;  // named target from the backend, may be empty
    public string RequestId;  // backend tick that produced this directive
    public float  ExpiresAt;  // Time.time deadline

    public bool HasValue => !string.IsNullOrWhiteSpace(Intent);
    public bool IsActive => HasValue && Time.time < ExpiresAt;

    /// <summary>
    /// Build the source IntentMessage the FSM reads — it carries the directive's
    /// intent, target, and request id so emitted micro-actions inherit them.
    /// </summary>
    public IntentMessage AsSource(LayerSource source)
        => IntentMessage.Create(
            Intent,
            source,
            -1f,
            Vector3.zero,
            "",
            RequestId ?? "",
            TargetKey ?? "");
}
