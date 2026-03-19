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

    public bool Evaluate(CreatureBlackBoard board, CreatureConfig config)
    {
        // Already startled? Stay startled until duration expires.
        if (board.isStartled)
        {
            if (Time.time < board.startleEndTime)
            {
                board.reflexBlocksTactical = true;
                return true;
            }
            // Startle expired
            board.isStartled = false;
            return false;
        }

        // Check: is player approaching fast AND inside flinch distance?
        if (!board.playerApproachingFast) return false;
        if (board.closestPlayerDist > config.flinchDistance) return false;
        if (Time.time - _lastFlinchTime < config.flinchCooldown) return false;

        // Trigger flinch
        board.isStartled           = true;
        board.startleEndTime       = Time.time + config.startleDuration;
        board.reflexBlocksTactical = true;
        _lastFlinchTime            = Time.time;

        board.LogEvent("startled by sudden approach");
        Debug.Log("[Reflex] Flinch triggered!");

        return true; // blocks tactical this frame
    }
}
