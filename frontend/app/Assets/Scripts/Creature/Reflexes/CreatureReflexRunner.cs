using UnityEngine;
using System.Collections.Generic;
using System.Linq;
/// <summary>
/// Runs all IReflex components in priority order (highest first).
/// If any reflex returns true (wants to block tactical), sets board.reflexBlocksTactical.
/// 
/// Attach this to the same GameObject as the creature.
/// Reflex MonoBehaviours (GazeReflex, FlinchReflex, etc.) should also be on that object.
/// </summary>
public class CreatureReflexRunner : MonoBehaviour
{
    CreatureBlackboard _board;
    CreatureConfig     _config;
    List<IReflex>      _reflexes;

    public void Init(CreatureBlackboard board, CreatureConfig config)
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
   
    public void Tick()
    {
        foreach (var reflex in _reflexes)
        {
            bool blocks = reflex.Evaluate(_board, _config);
            if (blocks)
            {
                // High-priority reflex fired — skip lower ones this frame
                // (e.g., if flinching, don't bother with gaze)
                return;
            }
        }
    }
}
