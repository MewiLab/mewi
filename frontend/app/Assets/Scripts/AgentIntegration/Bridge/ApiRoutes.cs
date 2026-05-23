// Central registry for the backend websocket path.
// Unity only knows one base URL (BackendConfig.baseUrl); this class owns the route.
// When the backend gains an API Gateway, only baseUrl changes — nothing here moves.
// When routes version up (e.g. /api/v2/...), update once here.
public static class ApiRoutes
{
    public const string AgentTickWs  = "/api/v1/agent/ws/";        // append creature_id

    public static string ResolveWebSocketWithId(BackendConfig cfg, string path, string id) =>
        ToWebSocketBaseUrl(cfg.baseUrl) + path + System.Uri.EscapeDataString(id ?? "");

    static string ToWebSocketBaseUrl(string baseUrl)
    {
        string trimmed = (baseUrl ?? "").TrimEnd('/');
        if (trimmed.StartsWith("https://", System.StringComparison.OrdinalIgnoreCase))
            return "wss://" + trimmed.Substring("https://".Length);
        if (trimmed.StartsWith("http://", System.StringComparison.OrdinalIgnoreCase))
            return "ws://" + trimmed.Substring("http://".Length);
        return trimmed;
    }
}
