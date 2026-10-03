using UnityEngine;

/// <summary>
/// Designer-authored hint volume placed on stairs, ledges, jump gaps, drops, or
/// fall hazards. Carries metadata only — it does not move the cat. Consumers
/// such as <see cref="CreatureOffMeshLinkTraversal"/> read the <see cref="kind"/>
/// to decide how to react when the cat enters or exits the trigger.
///
/// See docs/architecture/jump_through_obstacle_proposol.md (Phase 2). Triggers are hints and
/// safety metadata; NavMesh + Malbers remain the primary movement layer.
/// </summary>
public enum TraversalHintKind
{
    Stairs,
    Jump,
    Climb,
    Drop,
    FallHazard,
}

[DisallowMultipleComponent]
public class TraversalHintVolume : MonoBehaviour
{
    [Tooltip("What kind of traversal this volume marks. Consumers branch on this.")]
    public TraversalHintKind kind = TraversalHintKind.Jump;

    [Tooltip("Optional human-readable name for logs and Editor identification.")]
    public string debugName = "";

    public string DisplayName => string.IsNullOrWhiteSpace(debugName) ? gameObject.name : debugName;
}
