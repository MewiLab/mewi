/// </summary>
// Spatial-context channel: reads the sorted ZoneVolume list from the blackboard
// and projects it to the zones[] wire array.
//
// Each ZoneEntry carries only the properties meaningful for that zone —
// confinement and surface are empty string when not set on the ZoneVolume.
// Python reads zones[-1] for current state, zones[0] for broad context.
/// </summary>
using UnityEngine;
using System;
using System.Collections.Generic;

public sealed class SpatialChannel : ISnapshotChannel
{
    readonly int _maxReachableZones;
    readonly float _reachableZoneRadius;
    readonly bool _requireNavMeshPath;
    readonly NavigationSafetyConfig _navigationSafety;
    readonly List<ReachableAffordance> _reachablePlaceBuffer = new List<ReachableAffordance>();

    public SpatialChannel(
        int maxReachableZones = 12,
        float reachableZoneRadius = 60f,
        bool requireNavMeshPath = true,
        NavigationSafetyConfig navigationSafety = null)
    {
        _maxReachableZones = Mathf.Max(0, maxReachableZones);
        _reachableZoneRadius = Mathf.Max(0f, reachableZoneRadius);
        _requireNavMeshPath = requireNavMeshPath;
        _navigationSafety = navigationSafety ?? new NavigationSafetyConfig();
    }

    public string ChannelId => "spatial_context";

    public void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self)
    {
        var zones = board.activeZones;
        var entries = new List<ZoneEntry>(zones.Count);

        // remove duplicated spatial infos
        // sometimes we need duplication, sometimes do not

        for (int i = 0; i < zones.Count; i++)
        {
            var zv = zones[i];

            // Linear search is extremely fast for small lists (< 10 items)
            if (entries.Exists(e => e.id == zv.EffectiveZoneId))
            {
                continue;
            }

            entries.Add(new ZoneEntry
            {
                id          = zv.EffectiveZoneId,
                type        = zv.TypeString,
                confinement = zv.confinement != ConfinementLevel.Open ? zv.confinement.ToString() : "",
                surface     = zv.surface ?? "",
            });
        }

        string[] activeZoneIds = ActiveZoneIds(entries);
        List<ReachableAffordance> reachablePlaces = BuildReachablePlaces(self, activeZoneIds);
        payload.spatial_context = new SpatialData { zones = entries.ToArray() };
        payload.place_context = new PlaceContextData
        {
            current_zone_id = entries.Count > 0 ? entries[entries.Count - 1].id : "",
            active_zone_ids = activeZoneIds,
            reachable_zone_ids = CandidateZoneIds(reachablePlaces),
        };
        payload.navigation_context = new NavigationContextData
        {
            zone_routes = ZoneRouteEntries(reachablePlaces),
        };
    }

    static string[] ActiveZoneIds(List<ZoneEntry> entries)
    {
        var ids = new List<string>(entries.Count);
        for (int i = 0; i < entries.Count; i++)
        {
            if (!string.IsNullOrWhiteSpace(entries[i].id))
                ids.Add(entries[i].id);
        }
        return ids.ToArray();
    }

    List<ReachableAffordance> BuildReachablePlaces(Transform self, string[] activeZoneIds)
    {
        if (self == null || _maxReachableZones <= 0)
        {
            _reachablePlaceBuffer.Clear();
            return _reachablePlaceBuffer;
        }

        var active = new HashSet<string>(activeZoneIds ?? Array.Empty<string>(), StringComparer.OrdinalIgnoreCase);
        ZoneVolume[] zones = UnityEngine.Object.FindObjectsByType<ZoneVolume>(FindObjectsSortMode.None);

        ReachableAffordanceScanner.ScanPlaces(
            self,
            zones,
            active,
            _reachablePlaceBuffer,
            _maxReachableZones,
            _reachableZoneRadius,
            _requireNavMeshPath,
            ResolveNavigationSafety(self) ?? _navigationSafety);

        return _reachablePlaceBuffer;
    }

    string[] CandidateZoneIds(List<ReachableAffordance> candidates)
    {
        int count = Mathf.Min(_maxReachableZones, candidates.Count);
        var ids = new string[count];
        for (int i = 0; i < count; i++)
            ids[i] = candidates[i].target_id;
        return ids;
    }

    static ZoneRouteEntry[] ZoneRouteEntries(List<ReachableAffordance> candidates)
    {
        int count = candidates != null ? candidates.Count : 0;
        var entries = new ZoneRouteEntry[count];

        for (int i = 0; i < count; i++)
        {
            ReachableAffordance candidate = candidates[i];
            entries[i] = new ZoneRouteEntry
            {
                id = candidate.target_id,
                status = candidate.path_status ?? "",
                reason = candidate.reason ?? "",
                distance = candidate.distance,
                path_length = candidate.path_length,
            };
        }

        return entries;
    }

    static NavigationSafetyConfig ResolveNavigationSafety(Transform self)
    {
        MalbersAnimalAdapter adapter = ResolveAdapter(self);
        return adapter != null ? adapter.navigationSafety : null;
    }

    static MalbersAnimalAdapter ResolveAdapter(Transform self)
    {
        if (self == null) return null;

        return self.GetComponent<MalbersAnimalAdapter>()
            ?? self.GetComponentInParent<MalbersAnimalAdapter>()
            ?? self.GetComponentInChildren<MalbersAnimalAdapter>();
    }
}
