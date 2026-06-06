using System;

/// <summary>
/// Closed-session behavioral report DTOs for mewi-report.
/// This payload is persisted and processed after a play session. It is
/// intentionally separate from SnapshotPayload and PlanExecutionReport, which
/// are live LLM tick feedback contracts.
/// </summary>
[Serializable]
public class ReportSessionPayload
{
    public const string RawSchemaV1 = "mewi.report.raw.v1";
    public const string RawSchemaV2 = "mewi.report.raw.v2";

    public string schema_version = RawSchemaV2;
    public string user_id;
    public ReportSource source;
    public ReportSession session;
}

[Serializable]
public class ReportSource
{
    public string app = "mewi-unity";
    public string build;
    public string platform;
    public string scene;
}

[Serializable]
public class ReportSession
{
    public string session_id;
    public int session_index;
    public string timestamp_start;
    public string timestamp_end;
    public string close_reason;
    public float duration_seconds;
    public ReportEvent[] events;
    public ReportMultiCatEncounter[] multi_cat_encounters;
}

[Serializable]
public class ReportEvent
{
    public string event_id;
    public string correlation_id;
    public float t;
    public string actor;
    public string actor_id;
    public string action;
    public string cat_id;
    public string target_id;
    public string phase;
    public string status;
    public int trust_before;
    public int trust_after;
    public string trigger;
    public ReportEventParams @params;
    public ReportEventMeta meta;
}

[Serializable]
public class ReportEventParams
{
    public string zone_id;
    public string target_id;
    public string item_id;
    public string subtype;
    public string initiated_by;
    public string behavior_key;
    public string motor_action;
    public string social_act_kind;
    public string source_event_id;
    public float distance_to_player_m = -1f;
    public float distance_to_nearest_cat_m = -1f;
    public float facing_dot = -1f;
    public float confidence = -1f;
    public float speed_mps = -1f;
}

[Serializable]
public class ReportEventMeta
{
    public string source_system;
    public string recorder;
    public string derivation;
    public string note;
}

[Serializable]
public class ReportMultiCatEncounter
{
    public float t;
    public string[] cats_present;
    public string human_action;
    public string outcome;
}

[Serializable]
public class ReportSessionAcceptedResponse
{
    public string status;
    public string user_id;
    public string session_id;
    public bool stored;
    public int session_count;
    public bool processing_queued;
    public string storage_key;
}
