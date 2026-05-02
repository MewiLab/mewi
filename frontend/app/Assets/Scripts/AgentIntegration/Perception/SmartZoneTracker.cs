using UnityEngine;

/// <summary>
/// Maintains the cat's "where am I?" state as a set of zone tags.
///
/// Zones are SmartObjects carrying a tag prefixed "zone.*" (e.g. zone.harbor)
/// attached to a large trigger collider that encompasses the area.
///
/// Physics setup:
///   - This component requires a trigger collider on the same GameObject (the cat),
///     OR a trigger collider anywhere in its hierarchy — Unity forwards trigger
///     callbacks up to the Rigidbody. MAnimal already supplies the Rigidbody.
///   - The Layer Collision Matrix must allow the cat's layer to interact with
///     the zone layer (default is allow-all; only check if you've been editing it).
///
/// Zone specificity is stored as the tag's most-specific segment:
///   "zone.harbor.dock" → "dock" lands in currentZones.
/// </summary>
public class SmartZoneTracker : MonoBehaviour
{
    [Tooltip("Layers containing zone trigger volumes. Used only for the startup seed.")]
    public LayerMask zoneLayers = ~0; // default: all layers

    readonly Collider[] _seedBuffer = new Collider[16];

    CreatureBlackboard _board;

    public void Init(CreatureBlackboard board)
    {
        _board = board;
        SeedCurrentZones();
    }

    // OnTriggerEnter only fires on a transition — if the cat starts INSIDE a
    // zone (common for a spawn in the harbor), we'd never learn about it.
    // This one-shot probe at Init time fills that gap.
    void SeedCurrentZones()
    {
        int n = Physics.OverlapSphereNonAlloc(transform.position, 0.05f, _seedBuffer, zoneLayers, QueryTriggerInteraction.Collide);
        for (int i = 0; i < n; i++)
        {
            var so = _seedBuffer[i].GetComponentInParent<SmartObject>();
            if (so == null || !so.HasTag("zone")) continue;
            _board.currentZones.Add(so.SpecificCategory);
        }
    }

    void OnTriggerEnter(Collider other)
    {
        if (_board == null) return;
        var so = other.GetComponentInParent<SmartObject>();
        if (so == null || !so.HasTag("zone")) return;
        _board.currentZones.Add(so.SpecificCategory);
    }

    void OnTriggerExit(Collider other)
    {
        if (_board == null) return;
        var so = other.GetComponentInParent<SmartObject>();
        if (so == null || !so.HasTag("zone")) return;
        _board.currentZones.Remove(so.SpecificCategory);
    }
}
