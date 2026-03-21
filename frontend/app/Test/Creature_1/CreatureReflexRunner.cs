using UnityEngine;
using System.Collections.Generic;
using System.Linq;

/// <summary>
/// Runs all IReflex components in priority order (highest first).
///
/// UPGRADE from MVP:
///   Previously set `board.reflexBlocksTactical = true` — a boolean that CreatureBrain
///   checked to skip its tick. Now reflexes write to the `reflexOverride` typed slot
///   on the blackboard. The slot auto-expires based on the reflex's declared duration.
///
///   This means:
///   - CreatureBrain no longer needs to check a flag — it always ticks, and the
///     arbitration in ResolveActiveIntent() handles priority.
///   - Reflexes that need different durations (flinch = 0.3s, avoidance = 1s) are
///     handled naturally by the slot expiry, not by separate timer logic.
///   - Multiple reflexes can still short-circuit (highest priority wins within a frame),
///     but the output is always a single slot write.
///
/// Attach this to the same GameObject as the creature.
/// Reflex MonoBehaviours (GazeReflex, FlinchReflex, etc.) should also be on that object.
/// </summary>
public class CreatureReflexRunner : MonoBehaviour
{
    CreatureBlackBoard _board;
    CreatureConfig     _config;
    List<IReflex>      _reflexes;

    public void Init(CreatureBlackBoard board, CreatureConfig config)
    {
        _board    = board;
        _config   = config;
        // Collect all IReflex on this GameObject, sort by priority descending
        _reflexes = GetComponents<IReflex>()
            .OrderByDescending(r => r.Priority)
            .ToList();

        Debug.Log($"[ReflexRunner] Found {_reflexes.Count} reflexes: " +
                  string.Join(", ", _reflexes.Select(r => r.GetType().Name)));
    }

    /// <summary>
    /// Evaluate all reflexes in priority order.
    /// The first reflex that fires writes to the reflexOverride slot and we stop.
    ///
    /// If no reflex fires and the current override has expired, the slot is already
    /// null (checked by IsActive in the blackboard) — no explicit clear needed.
    /// </summary>
    public void Tick()
    {
        // If a reflex is already active and hasn't expired, don't re-evaluate
        // unless a higher-priority reflex wants to preempt it.
        // For MVP simplicity: always re-evaluate. The highest-priority reflex
        // that fires overwrites the slot regardless.

        foreach (var reflex in _reflexes)
        {
            bool fired = reflex.Evaluate(_board, _config);
            if (fired)
            {
                // Reflex wrote its slot via board.SetReflexOverride() inside Evaluate().
                // Higher-priority reflex wins — skip lower ones this frame.
                return;
            }
        }

        // No reflex fired this frame. If the previous reflex override expired,
        // ResolveActiveIntent() will fall through to tactical automatically.
        // We don't need to explicitly clear it — IsActive handles expiry.
    }
}
