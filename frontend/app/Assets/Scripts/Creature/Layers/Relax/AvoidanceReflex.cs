using UnityEngine;

/// <summary>
/// Stop before walking into obstacles or walls.
/// For MVP this is a simple placeholder — NavMesh already handles pathfinding.
/// This reflex is for cases NavMesh misses: dynamic obstacles, other creatures, etc.
///
/// Upgrade path: SphereCast forward, check for non-NavMesh obstacles.
/// </summary>
public class AvoidanceReflex : MonoBehaviour, IReflex
{
    public int Priority => 50; // between flinch (100) and gaze (10)

    public bool Evaluate(CreatureBlackboard board, CreatureConfig config)
    {
        // MVP: no-op, NavMesh handles avoidance
        // TODO: add SphereCast for dynamic obstacles
        return false;
    }
}
