using System;

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
