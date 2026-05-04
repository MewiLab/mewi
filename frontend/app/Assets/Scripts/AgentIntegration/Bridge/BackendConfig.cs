using UnityEngine;

// ScriptableObject holding all connection parameters for the Mewi backend.
// Create separate assets per environment (BackendConfig_Dev, BackendConfig_Prod)
// and swap the reference on AgentMindBridge in the Inspector.
// Unity only ever needs to know one URL — the base. Routes live in ApiRoutes.cs.
[CreateAssetMenu(fileName = "BackendConfig_Dev", menuName = "Mewi/Backend Config")]
public class BackendConfig : ScriptableObject
{
    [Header("Environment")]
    [Tooltip("Base URL with no trailing slash, e.g. http://localhost:8000 or https://api.mewi.game")]
    public string baseUrl = "http://localhost:8000";

    [Header("Polling")]
    public float pollIntervalSeconds = 1.5f;
    public int   maxPollAttempts     = 20;   // ~30 s cap at default interval

    [Header("Network")]
    [Tooltip("Per-request timeout in seconds. 0 = no timeout.")]
    public float requestTimeoutSeconds = 30f;
}
