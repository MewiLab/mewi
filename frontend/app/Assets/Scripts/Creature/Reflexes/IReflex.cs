/// <summary>
/// Interface for individual reflex behaviors.
/// Each reflex reads from the blackboard and may write override flags.
/// </summary>
public interface IReflex 
{
    /// <summary>Higher priority fires first. Flinch > Gaze > Avoidance.</summary>
    int Priority { get; }

    /// <summary>
    /// Evaluate and optionally act. Returns true if this reflex wants to
    /// block the tactical layer this frame (e.g., flinch overrides wander).
    /// </summary>
    bool Evaluate(CreatureBlackboard board, CreatureConfig config);
}
