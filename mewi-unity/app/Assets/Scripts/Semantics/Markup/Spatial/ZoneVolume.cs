// Hand-authored marker for a named semantic place.
// Distinct from SmartObject (name-pattern baked): zones are designer intent.
//
// Authoring:
//   1. Create a GameObject for the semantic place (e.g. ZV_Harbor).
//   2. Add ZoneVolume to that semantic place object.
//   3. Put one or more trigger Collider children under it for the footprint.
//   4. Set the collider children to the "SemanticZone" layer when possible.
//   5. Fill in zoneId, zoneType, and optionally confinement / surface.
//
// Parent/container zones (e.g. ZV_Harbor) need no collider. ZoneScanner samples
// the cat's current position, finds trigger collider children, and walks the
// ancestor chain, so Harbor is included whenever the cat is inside a descendant
// zone such as Harbor/Bamboo_Boardwalk.
//
// Hierarchy is implicit: active zones are sent broadest first, most specific
// last. No manual ordering needed.
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
        // If this ZoneVolume shares a GameObject with a Collider, ensure it is
        // a trigger. Child footprint colliders should also be triggers.
        var c = GetComponent<Collider>();
        if (c != null && !c.isTrigger) c.isTrigger = true;
    }

    public string EffectiveZoneId =>
        string.IsNullOrEmpty(zoneId) ? gameObject.name : zoneId;

    // Lowercase type string for the wire format. Matches the Python enum.
    public string TypeString => zoneType.ToString().ToLower();
}
