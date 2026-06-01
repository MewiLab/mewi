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
    public NavigationContextData navigation_context;
    public string[]       available_intents;
    public AffordanceTargetData[] targets;
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
    public float fullness;
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
public class NavigationContextData
{
    public ZoneRouteEntry[] zone_routes;
}

[Serializable]
public class ZoneRouteEntry
{
    public string id;
    public string status;      // "safe" | "risky" | "blocked"
    public string reason;      // empty when safe
    public float distance;
    public float path_length;
}

[Serializable]
public class AffordanceTargetData
{
    public string id;
    public string[] supports;
    public string[] tags;
    public float distance;
    public string status;
    public string path_status;
    public float path_length;
    public string reason;
}

[Serializable]
public class FeelingsData
{
    public string summary;
    public string[] smells;
    public string[] sounds;
    public string[] signals;
}
