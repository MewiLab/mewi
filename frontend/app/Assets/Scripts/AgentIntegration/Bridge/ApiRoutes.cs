// Central registry of all backend API paths.
// Unity only knows one base URL (BackendConfig.baseUrl); this class owns every path.
// When the backend gains an API Gateway, only baseUrl changes — nothing here moves.
// When routes version up (e.g. /api/v2/...), update once here.
public static class ApiRoutes
{
    public const string AgentTick       = "/api/v1/agent/tick";
    public const string AgentTickResult = "/api/v1/agent/tick/result/";  // append job_id
    public const string AgentReport     = "/api/v1/agent/report";

    public static string Resolve(BackendConfig cfg, string path) =>
        cfg.baseUrl.TrimEnd('/') + path;
}
