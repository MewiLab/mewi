// Central registry of all backend API paths.
// Unity only knows one base URL (BackendConfig.baseUrl); this class owns every path.
// When the backend gains an API Gateway, only baseUrl changes — nothing here moves.
// When routes version up (e.g. /api/v2/...), update once here.
public static class ApiRoutes
{
    public const string AgentTickWs  = "/api/v1/agent/ws/";        // append creature_id
    public const string AgentReport  = "/api/v1/agent/report";
    public const string AttachmentSession = "/api/v1/attachment/session";

    public static string Resolve(BackendConfig cfg, string path) =>
        cfg.baseUrl.TrimEnd('/') + path;

    public static string ResolveWithId(BackendConfig cfg, string path, string id) =>
        Resolve(cfg, path) + System.Uri.EscapeDataString(id ?? "");

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
