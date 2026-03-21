using UnityEngine;

/// <summary>
/// Flinch reflex — fires when a fast-approaching player enters personal space.
///
/// UPGRADE from MVP:
///   Now writes to board.SetReflexOverride() with a declared duration instead of
///   setting reflexBlocksTactical = true. The duration (default 0.3s) means:
///   - The flinch auto-expires without any timer bookkeeping in this class.
///   - When it expires, ResolveActiveIntent() falls through to tacticalCurrent,
///     resuming whatever the cat was doing (Brooks' subsumption resume).
///
/// The flinch direction is passed via directionHint so the animation system
/// knows which direction to play the flinch animation toward.
/// </summary>
public class FlinchReflex : MonoBehaviour, IReflex
{
    /// <summary>
    /// Higher than GazeReflex (10), lower than AvoidanceReflex if you add one at 30.
    /// Priority only matters within the reflex layer — it determines which reflex
    /// wins when multiple could fire in the same frame.
    /// </summary>
    public int Priority => 20;

    [Tooltip("How long the flinch suppresses tactical behavior (seconds).")]
    [SerializeField] float flinchDuration = 0.3f;

    /// <summary>
    /// Evaluate whether to flinch this frame.
    /// Returns true if the reflex fired (slot was written).
    /// </summary>
    public bool Evaluate(CreatureBlackBoard board, CreatureConfig config)
    {
        // Don't re-trigger if we're already flinching
        if (board.IsReflexActive && board.ReflexOverride.Value.intent == "flinch")
            return true; // Still active, maintain suppression, don't re-write slot

        // Trigger: player approaching fast within personal space
        if (!board.playerApproachingFast) return false;
        if (board.closestPlayerDist > config.personalSpaceRadius) return false;
        if (board.closestPlayer == null) return false;

        // Fire the flinch — write to reflexOverride slot
        Vector3 awayFromThreat = (transform.position - board.closestPlayer.position).normalized;

        board.SetReflexOverride(
            intent:        "flinch",
            duration:      flinchDuration,
            directionHint: awayFromThreat
        );

        board.isStartled    = true;
        board.startleEndTime = Time.time + flinchDuration;
        board.mood.fear     += 0.1f;
        board.mood.Clamp();

        Debug.Log($"[FlinchReflex] FIRED — flinch {flinchDuration}s, away from {board.closestPlayer.name}");
        return true;
    }
}
