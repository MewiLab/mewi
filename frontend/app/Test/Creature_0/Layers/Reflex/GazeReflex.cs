using UnityEngine;

/// <summary>
/// The cat's head/eyes turn toward the most interesting stimulus.
/// Writes to blackboard.gazeOverrideTarget — the animation layer reads this
/// and uses Malbers' Look At or procedural IK to aim the head.
///
/// Does NOT block tactical — the cat can look at something while walking.
/// </summary>
public class GazeReflex : MonoBehaviour, IReflex
{
    public int Priority => 10; // low priority, doesn't interrupt anything

    public bool Evaluate(CreatureBlackBoard board, CreatureConfig config)
    {
        // Priority 1: recent sound
        if (Time.time - board.lastHeardSoundTime < 2f)
        {
            board.gazeOverrideTarget = transform.position + board.lastHeardSoundDir * 3f;
            board.hasGazeOverride    = true;
            return false; // gaze never blocks tactical
        }

        // Priority 2: player in sight and close enough to be interesting
        if (board.playerInSight && board.closestPlayerDist < config.personalSpaceRadius * 4f)
        {
            board.gazeOverrideTarget = board.closestPlayer.position;
            board.hasGazeOverride    = true;
            return false;
        }

        // No interesting target — let animation layer handle default gaze
        board.hasGazeOverride = false;
        return false;
    }
}
