using System;

/// <summary>
/// Live tick feedback for the backend mind loop.
/// This reports the micro-actions the cat body actually attempted/completed
/// since the previous snapshot plus live social micro-events that caused those
/// body actions. It is sent over the agent websocket with SnapshotPayload and
/// is not the persisted mewi-report session JSON.
/// </summary>
[Serializable]
public class PlanExecutionReport
{
    public string agent_id;
    public string requestId;
    public string planId;
    public string correlationId;
    public string status;
    public float startedAt;
    public float completedAt;
    public PlanMicroActionEvent[] events;
    public PlanStepExecutionReport[] steps;

    public bool HasContent =>
        (steps != null && steps.Length > 0) ||
        (events != null && events.Length > 0);

    public static PlanExecutionReport Merge(PlanExecutionReport older, PlanExecutionReport newer)
    {
        if (older == null || !older.HasContent)
            return newer;
        if (newer == null || !newer.HasContent)
            return older;

        return new PlanExecutionReport
        {
            agent_id = string.IsNullOrWhiteSpace(newer.agent_id) ? older.agent_id : newer.agent_id,
            requestId = string.IsNullOrWhiteSpace(newer.requestId) ? older.requestId : newer.requestId,
            planId = string.IsNullOrWhiteSpace(newer.planId) ? older.planId : newer.planId,
            correlationId = string.IsNullOrWhiteSpace(newer.correlationId) ? older.correlationId : newer.correlationId,
            status = string.IsNullOrWhiteSpace(newer.status) ? older.status : newer.status,
            startedAt = older.startedAt > 0f ? older.startedAt : newer.startedAt,
            completedAt = newer.completedAt > 0f ? newer.completedAt : older.completedAt,
            events = MergeArrays(older.events, newer.events),
            steps = MergeArrays(older.steps, newer.steps),
        };
    }

    static T[] MergeArrays<T>(T[] older, T[] newer)
    {
        int olderCount = older != null ? older.Length : 0;
        int newerCount = newer != null ? newer.Length : 0;
        if (olderCount == 0)
            return newer;
        if (newerCount == 0)
            return older;

        T[] merged = new T[olderCount + newerCount];
        Array.Copy(older, 0, merged, 0, olderCount);
        Array.Copy(newer, 0, merged, olderCount, newerCount);
        return merged;
    }
}

/// <summary>
/// One live causal event that may or may not have a body motor step.
/// Field names mirror backend MicroActionEvent / report v2 JSON names.
/// </summary>
[Serializable]
public class PlanMicroActionEvent
{
    public string event_id;
    public string correlation_id;
    public string request_id;
    public string actor_type;
    public string actor_id;
    public string target_type;
    public string target_id;
    public string direction;
    public string action;
    public string behavior_key;
    public string motor_action;
    public string phase;
    public string status;
    public string source_event_id;
    public float timestamp;
    public float distance_m;
    public float facing_dot;
    public float confidence;
}

/// <summary>
/// One executed body step inside a live plan execution report.
/// </summary>
[Serializable]
public class PlanStepExecutionReport
{
    public string commandId;
    public string requestId;
    public string correlationId;
    public string action;
    public string target;
    public string status;
    public string reason;
    public float startedAt;
    public float endedAt;
}
