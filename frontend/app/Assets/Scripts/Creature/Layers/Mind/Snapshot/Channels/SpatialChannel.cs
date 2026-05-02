// SpatialChannel.cs
//
// Spatial-context channel: reads hierarchical zone data written by
// ZoneScanner (Perception/Spatial) and writes it to the snapshot.
//
// Eye perception answers "what's near me?" — this answers "where am I?".
// The hierarchy comes from largest enclosing volume to smallest:
//   ["Harbor", "Boat_03", "Deck"]

using UnityEngine;

public sealed class SpatialChannel : ISnapshotChannel
{
    public string ChannelId => "spatial_context";

    public void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self)
    {
        payload.spatial_context = new SpatialData
        {
            location_hierarchy = board.locationHierarchy != null
                ? board.locationHierarchy.ToArray()
                : System.Array.Empty<string>(),
            confinement      = board.confinement.ToString(),
            surface_material = board.surfaceMaterial ?? "",
        };
    }
}
