using System;
using UnityEngine;

/// <summary>
/// One Unity-validated reachable action candidate.
/// This is descriptive only; CreatureMotorWorker remains the only executor.
/// </summary>
[Serializable]
public class ReachableAffordance
{
    public string id = "";
    public string action = "go_to";
    public string target_id = "";
    public string label = "";
    public string[] tags = Array.Empty<string>();
    public float distance;
    public float path_length;
    public string path_status = "";
    public string reason = "";
    public float cost;
    public float utility;
    public Vector3 position;

    [NonSerialized] public SmartObject smartObject;
    [NonSerialized] public ZoneVolume zone;
    [NonSerialized] public Transform target;
}
