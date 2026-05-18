using UnityEngine;
using UnityEngine.Networking;

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

    [Header("Auth")]
    [SerializeField, Tooltip("Header name expected by the backend for API key auth.")]
    string apiKeyHeader = "X-API-Key";

    [SerializeField, Tooltip("API key sent with every backend request. Leave empty to disable auth headers.")]
    string apiKey = "";

    [Header("Polling")]
    public float pollIntervalSeconds = 1.5f;
    public int   maxPollAttempts     = 20;   // ~30 s cap at default interval

    [Header("Network")]
    [Tooltip("Per-request timeout in seconds. 0 = no timeout.")]
    public float requestTimeoutSeconds = 30f;

    public void ApplyAuth(UnityWebRequest request)
    {
        if (request == null) return;
        if (string.IsNullOrWhiteSpace(apiKeyHeader)) return;
        if (string.IsNullOrWhiteSpace(apiKey)) return;

        request.SetRequestHeader(apiKeyHeader, apiKey);
    }
}
