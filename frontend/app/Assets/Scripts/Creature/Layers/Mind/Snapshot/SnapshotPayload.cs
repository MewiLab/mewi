// SnapshotPayload.cs
//
// The wire format sent to POST /api/v1/agent/tick.
//
// Each channel owns one slot of this payload (e.g. SelfChannel writes `self`,
// SpatialChannel writes `spatial_context`). Adding a channel means adding a
// field here AND a class under Snapshot/Channels/.
//
// Kept in the Snapshot folder — neither AgentMindBridge nor PeriodicMind
// reference these types directly. Only channels and SnapshotManager do.

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

[Serializable]
public class SpatialData
{
    public string[] location_hierarchy;
    public string   confinement;
    public string   surface_material;
}
