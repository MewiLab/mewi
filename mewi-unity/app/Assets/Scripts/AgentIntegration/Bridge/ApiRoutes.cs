// Central registry for the backend websocket path.
// Unity only knows one base URL (BackendConfig.baseUrl)
// When routes version up (e.g. /api/v2/...), update once here.
public static class ApiRoutes
{
    public const string AgentTickWs = "/api/v1/agent/ws";
    public const string ReportSession = "/api/v1/report/session";

    public static string ResolveHttp(BackendConfig cfg, string path) =>
        (cfg != null ? cfg.baseUrl : "").TrimEnd('/') + path;

    public static string ResolveWebSocket(BackendConfig cfg, string path) =>
        ToWebSocketBaseUrl(cfg != null ? cfg.baseUrl : "") + path;

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
