// SelfChannel.cs
//
// Writes "where I am" + "what I'm currently doing" — the basic self-context.
// Reads currentZones (flat tag set from SmartZoneTracker) for `location`;
// hierarchical "I'm in Harbor > Boat_03 > Deck" lives on the Spatial channel.

using System.Collections.Generic;
using UnityEngine;

public sealed class SelfChannel : ISnapshotChannel
{
    public string ChannelId => "self";

    public void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self)
    {
        payload.self = new SelfData
        {
            location       = JoinZones(board.currentZones),
            current_action = board.ResolveActiveIntent().Intent,
        };
    }

    static string JoinZones(HashSet<string> zones)
    {
        if (zones == null || zones.Count == 0) return "";
        return string.Join(",", zones);
    }
}
