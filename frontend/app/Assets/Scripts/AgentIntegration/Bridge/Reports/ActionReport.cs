using System;

[Serializable]
public class ActionReport
{
    public string agent_id;
    public string commandId;
    public string requestId;
    public string action;
    public string status;
    public string reason;
    public float time;
}
