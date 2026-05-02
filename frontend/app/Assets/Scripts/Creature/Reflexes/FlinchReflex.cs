using UnityEngine;

/// <summary>
/// Sudden proximity → cat startles, freezes briefly, backs up.
/// This BLOCKS tactical for the startle duration.
///
/// With Malbers: you'd trigger a Mode (e.g., ModeID.Action with a "startle" ability).
/// For MVP: just sets flags; CreatureController reads them.
/// </summary>
public class FlinchReflex : MonoBehaviour, IReflex
{
    public int Priority => 100; // high priority — fires before gaze

    float _lastFlinchTime = -999f;

    public bool Evaluate(CreatureBlackboard board, CreatureConfig config)
    {
        // Already flinching? IntentMessage handles expiry automatically.
        if (board.IsReflexActive)
            return true;

        // Check: is player approaching fast AND inside flinch distance?
        if (!board.playerApproachingFast) return false;
        if (board.closestPlayerDist > config.flinchDistance) return false;
        if (Time.time - _lastFlinchTime < config.flinchCooldown) return false;

        // Trigger flinch — duration handles expiry, no manual flags needed
        board.SetReflexIntent("flinch", config.startleDuration);
        _lastFlinchTime = Time.time;

        board.LogEvent("startled by sudden approach");
        Debug.Log("[Reflex] Flinch triggered!");

        return true;
    }
}
