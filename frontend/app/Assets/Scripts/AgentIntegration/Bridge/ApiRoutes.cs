// Central registry of all backend API paths.
// Unity only knows one base URL (BackendConfig.baseUrl); this class owns every path.
// When the backend gains an API Gateway, only baseUrl changes — nothing here moves.
// When routes version up (e.g. /api/v2/...), update once here.
public static class ApiRoutes
{
    public const string AgentTick    = "/api/v1/agent/tick/";       // append creature_id
    public const string AgentTickJob = "/api/v1/agent/tick/jobs/";  // append job_id
    public const string AgentReport  = "/api/v1/agent/report";

    public static string Resolve(BackendConfig cfg, string path) =>
        cfg.baseUrl.TrimEnd('/') + path;

    public static string ResolveWithId(BackendConfig cfg, string path, string id) =>
        Resolve(cfg, path) + System.Uri.EscapeDataString(id ?? "");
}
