// ZoneVolume.cs
//
// Hand-authored marker for a hierarchical semantic place — Harbor, Boat_03,
// Deck, Cabin, etc. Distinct from SmartObject (which is name-pattern baked):
// zones are *designer intent*, not *asset metadata*.
//
// Authoring:
//   1. Create an empty GameObject inside the parent area.
//   2. Add a trigger Collider sized to the zone's footprint.
//   3. Set the GameObject's Layer to "SemanticZone".
//   4. Add this component, set zoneId, layer, confinement, surface.
//
// Hierarchy is computed at scan time by sorting overlapping ZoneVolumes —
// see ZoneScanner. A single point in space typically overlaps three:
//   District (Harbor) > Area (Boat_03) > Surface (Deck).
//
// If a parent (Boat_03) moves, all child ZoneVolumes move with it. The
// hierarchy stays consistent without any extra wiring.

using UnityEngine;

[DisallowMultipleComponent]
[RequireComponent(typeof(Collider))]
public class ZoneVolume : MonoBehaviour
{
    public enum ZoneLayer
    {
        District = 0,   // largest — whole Harbor, whole Market
        Area     = 1,   // mid     — Boat_03, Marketplace
        Surface  = 2,   // smallest — Deck, Cabin floor, Counter top
    }

    [Tooltip("Human-readable identifier sent to the agent. e.g. 'Harbor', 'Boat_03', 'Deck'.")]
    public string zoneId = "";

    [Tooltip("Hierarchy layer — controls sort order in location_hierarchy.")]
    public ZoneLayer layer = ZoneLayer.Area;

    [Tooltip("How enclosed this place feels. Used by reason node.")]
    public ConfinementLevel confinement = ConfinementLevel.Open;

    [Tooltip("Surface material the agent stands on. Empty inherits from parent zone.")]
    public string surfaceMaterial = "";

    Collider _collider;

    public Collider Collider
    {
        get
        {
            if (_collider == null) _collider = GetComponent<Collider>();
            return _collider;
        }
    }

    void Awake()
    {
        // Trigger volumes only — never block the cat physically.
        var c = GetComponent<Collider>();
        if (c != null && !c.isTrigger) c.isTrigger = true;
    }

    public string EffectiveZoneId =>
        string.IsNullOrEmpty(zoneId) ? gameObject.name : zoneId;
}
