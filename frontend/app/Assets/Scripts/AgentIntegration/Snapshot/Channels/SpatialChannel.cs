// SpatialChannel.cs
//
// Spatial-context channel: reads the sorted ZoneVolume list from the blackboard
// and projects it to the zones[] wire array.
//
// Each ZoneEntry carries only the properties meaningful for that zone —
// confinement and surface are empty string when not set on the ZoneVolume.
// Python reads zones[-1] for current state, zones[0] for broad context.

using UnityEngine;
using UnityEngine.AI;
using System;
using System.Collections.Generic;

public sealed class SpatialChannel : ISnapshotChannel
{
    struct ZoneCandidate
    {
        public string id;
        public float sqrDistance;
        public bool hasCompletePath;
    }

    readonly int _maxReachableZones;
    readonly float _reachableZoneRadius;
    readonly bool _requireNavMeshPath;

    public SpatialChannel(
        int maxReachableZones = 12,
        float reachableZoneRadius = 60f,
        bool requireNavMeshPath = true)
    {
        _maxReachableZones = Mathf.Max(0, maxReachableZones);
        _reachableZoneRadius = Mathf.Max(0f, reachableZoneRadius);
        _requireNavMeshPath = requireNavMeshPath;
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
        payload.spatial_context = new SpatialData { zones = entries.ToArray() };
        payload.place_context = new PlaceContextData
        {
            current_zone_id = entries.Count > 0 ? entries[entries.Count - 1].id : "",
            active_zone_ids = activeZoneIds,
            reachable_zone_ids = ReachableZoneIds(self, activeZoneIds),
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

    string[] ReachableZoneIds(Transform self, string[] activeZoneIds)
    {
        if (self == null || _maxReachableZones <= 0)
            return new string[0];

        var active = new HashSet<string>(activeZoneIds ?? Array.Empty<string>(), StringComparer.OrdinalIgnoreCase);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var candidates = new List<ZoneCandidate>();
        ZoneVolume[] zones = UnityEngine.Object.FindObjectsByType<ZoneVolume>(FindObjectsSortMode.None);
        float radiusSqr = _reachableZoneRadius * _reachableZoneRadius;

        for (int i = 0; i < zones.Length; i++)
        {
            ZoneVolume zone = zones[i];
            if (zone == null) continue;

            string id = zone.EffectiveZoneId;
            if (string.IsNullOrWhiteSpace(id) || !seen.Add(id))
                continue;
            if (active.Contains(id))
                continue;

            Vector3 center = ZoneVolumeUtility.CenterOrTransform(zone);
            float sqrDistance = (center - self.position).sqrMagnitude;
            if (_reachableZoneRadius > 0f && sqrDistance > radiusSqr)
                continue;

            bool hasCompletePath = !_requireNavMeshPath || HasCompleteNavMeshPath(self.position, center);
            candidates.Add(new ZoneCandidate
            {
                id = id,
                sqrDistance = sqrDistance,
                hasCompletePath = hasCompletePath,
            });
        }

        candidates.Sort((a, b) =>
        {
            int byPath = b.hasCompletePath.CompareTo(a.hasCompletePath);
            if (byPath != 0) return byPath;
            return a.sqrDistance.CompareTo(b.sqrDistance);
        });

        int count = Mathf.Min(_maxReachableZones, candidates.Count);
        var ids = new string[count];
        for (int i = 0; i < count; i++)
            ids[i] = candidates[i].id;
        return ids;
    }

    static bool HasCompleteNavMeshPath(Vector3 from, Vector3 to)
    {
        if (!NavMesh.SamplePosition(from, out NavMeshHit start, 3f, NavMesh.AllAreas))
            return false;
        if (!NavMesh.SamplePosition(to, out NavMeshHit end, 6f, NavMesh.AllAreas))
            return false;

        var path = new NavMeshPath();
        if (!NavMesh.CalculatePath(start.position, end.position, NavMesh.AllAreas, path))
            return false;

        return path.status == NavMeshPathStatus.PathComplete;
    }
}
