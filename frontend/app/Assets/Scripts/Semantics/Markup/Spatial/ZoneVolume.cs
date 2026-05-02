// Hand-authored marker for a named semantic place.
// Distinct from SmartObject (name-pattern baked): zones are designer intent.
//
// Authoring:
//   1. Create a GameObject for the zone (e.g. ZV_Sea_1).
//   2. Add a trigger Collider sized to the zone's footprint on THE SAME object.
//   3. Set the GameObject's Layer to "SemanticZone".
//   4. Fill in zoneId, zoneType, and optionally confinement / surface.
//
// Container zones (e.g. ZV_Harbor) need NO collider. ZoneScanner walks the
// ancestor chain of every triggered collider, so ZV_Harbor is included in the
// snapshot automatically whenever any of its descendants (ZV_Sea_1 etc.) are active.
//
// Hierarchy is implicit: zones are sorted by hierarchy depth — shallowest
// (broadest) first, deepest (most specific) last. No manual ordering needed.
//
// For moving objects (boats): parent ZoneVolume children to the vessel root
// so they follow its position. The scanner sees updated world positions automatically.
//
// Per-zone optional properties:
//   confinement — only meaningful for vessel, building, courtyard, surface
//   surface     — only meaningful for path, surface, yard types
//   Leave at defaults (Open / "") for district, water, etc.

using UnityEngine;

[DisallowMultipleComponent]
public class ZoneVolume : MonoBehaviour
{
    [Tooltip("Human-readable identifier sent to the agent. e.g. 'Harbor', 'Boat_03', 'Deck'.")]
    public string zoneId = "";

    [Tooltip("What kind of place this is. Serialised to lowercase in the snapshot.")]
    public ZoneType zoneType = ZoneType.District;

    [Tooltip("How enclosed this place feels. Only set for vessel / building / surface zones.")]
    public ConfinementLevel confinement = ConfinementLevel.Open;

    [Tooltip("Material the cat stands on. Set for path / surface zones. Leave empty elsewhere.")]
    public string surface = "";

    void Awake()
    {
        // If this ZoneVolume shares a GameObject with a Collider (leaf zone),
        // ensure it is a trigger. Container zones with no direct Collider are left alone.
        var c = GetComponent<Collider>();
        if (c != null && !c.isTrigger) c.isTrigger = true;
    }

    public string EffectiveZoneId =>
        string.IsNullOrEmpty(zoneId) ? gameObject.name : zoneId;

    // Lowercase type string for the wire format. Matches the Python enum.
    public string TypeString => zoneType.ToString().ToLower();
}
