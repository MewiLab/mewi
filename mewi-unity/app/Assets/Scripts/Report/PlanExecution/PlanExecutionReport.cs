using System;

/// <summary>
/// Live tick feedback for the backend mind loop.
/// This reports the micro-actions the cat body actually attempted/completed
/// since the previous snapshot. It is sent over the agent websocket with
/// SnapshotPayload and is not the persisted mewi-report session JSON.
/// </summary>
[Serializable]
public class PlanExecutionReport
{
    public string agent_id;
    public string requestId;
    public string planId;
    public string status;
    public float startedAt;
    public float completedAt;
    public PlanStepExecutionReport[] steps;
}

/// <summary>
/// One executed body step inside a live plan execution report.
/// </summary>
[Serializable]
public class PlanStepExecutionReport
{
    public string commandId;
    public string requestId;
    public string action;
    public string target;
    public string status;
    public string reason;
    public float startedAt;
    public float endedAt;
}
