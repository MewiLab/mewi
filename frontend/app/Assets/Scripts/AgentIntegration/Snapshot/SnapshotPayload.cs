// SnapshotPayload.cs
//
// The wire format sent to POST /api/v1/agent/tick.
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
    public string         requestId;
    public float          time;

    public SelfData       self;
    public MoodData       mood;
    public HealthData     health;
    public EntityData[]   entities;
    public SpatialData    spatial_context;
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
