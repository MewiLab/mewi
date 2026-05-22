// SnapshotPayload.cs
//
// The full snapshot embedded in the /api/v1/agent/ws/{creature_id} tick envelope.
//
// Each channel owns one slot of this payload. Adding a channel means adding a
// field here AND a class under Snapshot/Channels/.
//
// Note on optional zone properties: JsonUtility always emits all declared
// fields. ZoneEntry.confinement and ZoneEntry.surface will appear as "" when
// not set. Python treats empty string as absent: `zone.get('confinement') or None`.

using System;

[Serializable]
public class SnapshotPayload
{
    public string         agent_id;
    public string         requestId;
    public string         commandId;
    public float          time;

    public SelfData       self;
    public MoodData       mood;
    public HealthData     health;
    public EntityData[]   entities;
    public SpatialData    spatial_context;
    public PlaceContextData place_context;
    public FeelingsData   feelings;
}

[Serializable]
public class SelfData
{
    public string location;
    public string current_action;
}

[Serializable]
public class MoodData
{
    public float fear, trust, curiosity, social, energy;
}

[Serializable]
public class HealthData
{
    public float hunger;
}

[Serializable]
public class EntityData
{
    public string   id;
    public string[] tags;
    public float    distance;
    public string   direction;
}

// Each entry in the zones array.
// confinement / surface are optional — empty string means "not specified for this zone".
[Serializable]
public class ZoneEntry
{
    public string id;
    public string type;
    public string confinement;  // "Open" | "Semi" | "Confined" | ""
    public string surface;      // material string | ""
}

[Serializable]
public class SpatialData
{
    public ZoneEntry[] zones;
}

[Serializable]
public class PlaceContextData
{
    public string current_zone_id;
    public string[] active_zone_ids;
    public string[] reachable_zone_ids;
}

[Serializable]
public class FeelingsData
{
    public string summary;
    public string[] smells;
    public string[] sounds;
    public string[] signals;
}
