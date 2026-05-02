// SpatialChannel.cs
//
// Spatial-context channel: reads the sorted ZoneVolume list from the blackboard
// and projects it to the zones[] wire array.
//
// Each ZoneEntry carries only the properties meaningful for that zone —
// confinement and surface are empty string when not set on the ZoneVolume.
// Python reads zones[-1] for current state, zones[0] for broad context.

using UnityEngine;
using System.Collections.Generic;
public sealed class SpatialChannel : ISnapshotChannel
{
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

        payload.spatial_context = new SpatialData { zones = entries.ToArray() };
    }
}
