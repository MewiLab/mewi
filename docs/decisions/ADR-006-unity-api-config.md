# ADR-006: Unity API Configuration — BackendConfig + ApiRoutes

**Status:** Accepted <br>
**Date:** 2026-05-04 <br>
**Deciders:** vanillasky <br>
**Relates to:** ADR-005 (Unity client architecture), ADR-003 (FastAPI backend)



## Context

`AgentMindBridge` previously held two independent `public string` Inspector fields carrying full hardcoded URLs:

```csharp
public string backendUrl    = "http://localhost:8000/api/v1/agent/tick";
public string resultBaseUrl = "http://localhost:8000/api/v1/agent/tick/result/";
```

This has three practical problems:

1. **No single source of truth for the host.** Changing environments (dev → staging → prod) requires editing two fields, on a per-component basis in the Inspector. Easy to miss one.
2. **Route paths are scattered.** If a backend route is renamed, there is no central place to find every reference — each caller buries the full URL string.
3. **Network tuning params are co-located with component logic.** `pollIntervalSeconds` and `maxPollAttempts` lived on `AgentMindBridge`, but they are environment-level concerns (prod may need higher retries or shorter intervals than local dev).

The team asked about industry-standard solutions. Two paths are credible at scale:

- **API Gateway (Backend-for-Frontend):** A proxy (Nginx, Kong, cloud API Management) sits in front of the backend. The Unity client knows one URL; routing, versioning, and service discovery are handled server-side. Unity never changes when the backend is restructured.
- **OpenAPI / auto-generated SDK:** FastAPI emits an OpenAPI spec; a tool (NSwag, Speakeasy, OpenAPI Generator) ingests it and produces a C# client library. URLs, serialization, and error handling disappear from handwritten Unity code entirely.

Both are the right answer at larger scale. At Mewi's current stage — a 1–2 person team, a single FastAPI monolith, and fewer than five endpoints — the setup cost of either approach is not justified. The priority is to reach the correct shape cheaply so the upgrade path to either option stays open.



## Decision

Introduce two new types in `AgentIntegration/Bridge/`:

### 1. `BackendConfig` (ScriptableObject)

Holds everything that varies between environments:

```csharp
[CreateAssetMenu(menuName = "Mewi/Backend Config")]
public class BackendConfig : ScriptableObject
{
    public string baseUrl = "http://localhost:8000";  // no trailing slash
    public float  pollIntervalSeconds = 1.5f;
    public int    maxPollAttempts     = 20;
    public float  requestTimeoutSeconds = 30f;
}
```

Create one asset per environment in `Assets/Settings/`:

| Asset | `baseUrl` |
|---|---|
| `BackendConfig_Dev.asset` | `http://localhost:8000` |
| `BackendConfig_Prod.asset` | `https://api.mewi.game` |

Swap the Inspector reference on `AgentMindBridge` to switch environments. No code changes, no recompile.

### 2. `ApiRoutes` (static class)

Owns every path string. Never holds a URL — only paths:

```csharp
public static class ApiRoutes
{
    public const string AgentTick       = "/api/v1/agent/tick";
    public const string AgentTickResult = "/api/v1/agent/tick/result/"; // append job_id

    public static string Resolve(BackendConfig cfg, string path) =>
        cfg.baseUrl.TrimEnd('/') + path;
}
```

Adding a new endpoint is one line here. No grep required to find every caller.

### 3. `AgentMindBridge` — updated Inspector surface

```csharp
[Header("Backend")]
public BackendConfig config;
```

Usage inside coroutines:
```csharp
// Outbound POST
var req = new UnityWebRequest(ApiRoutes.Resolve(config, ApiRoutes.AgentTick), "POST");

// Poll URL
string pollUrl = ApiRoutes.Resolve(config, ApiRoutes.AgentTickResult) + jobId;

// Polling params from config
var wait = new WaitForSecondsRealtime(config.pollIntervalSeconds);
for (int attempt = 0; attempt < config.maxPollAttempts; attempt++) { ... }
```



## Migration Path

### To a real API Gateway (when the backend splits into microservices)

1. Stand up the gateway (Nginx/Kong/cloud) in front of all services.
2. Update `BackendConfig_Prod.asset → baseUrl` to the gateway URL.
3. **No Unity code changes.** Routes in `ApiRoutes.cs` remain identical because the gateway handles internal routing.

### To OpenAPI auto-generated SDK (when boilerplate becomes painful)

1. Export FastAPI's `/openapi.json`.
2. Run OpenAPI Generator to produce a C# client into `Assets/Scripts/Generated/`.
3. Replace `ApiRoutes.Resolve(...)` call sites with the generated client methods.
4. `ApiRoutes.cs` can be deleted; `BackendConfig.baseUrl` is fed to the generated client's `Configuration.BasePath`.

The generated SDK slot exactly where `ApiRoutes + UnityWebRequest` sits now — the rest of the architecture is untouched.



## Consequences

**Positive:**
- One `baseUrl` field to change when switching environments.
- All route paths are findable in one file.
- Network tuning (polling interval, timeout) lives in the config asset, not scattered across components.
- No new dependencies; pure C#/Unity ScriptableObject.
- The migration paths to API Gateway and OpenAPI SDK are clear and low-friction.

**Negative / trade-offs:**
- The Inspector reference `AgentMindBridge.config` must be wired manually per-scene (null check added in `Init()`). Forgetting to assign the asset will surface at runtime, not compile time.
- ScriptableObject assets must be committed to version control and kept in sync across team members. Use `Assets/Settings/` and check them in.



## Alternatives Considered

### A. Keep two `public string` URL fields with better defaults
**Rejected.** Doesn't solve route scattering and still requires two edits per environment switch. Marginal improvement over the original.

### B. Scripting Define Symbols for compile-time URL switching
**Rejected for primary config.** Works for dev/prod but requires a rebuild to change the URL. Cannot be tweaked at runtime in a deployed build.

### C. `StreamingAssets` JSON file
**Deferred.** Good if the game is deployed on a desktop machine where ops must edit the URL post-build without a full rebuild. Not needed while the team controls the build pipeline. Upgrade: add a `BackendConfigLoader` that reads `StreamingAssets/backend_config.json` and overrides `BackendConfig.baseUrl` on `Awake`.

### D. API Gateway now
**Deferred.** Right answer when the backend has multiple services. Today the backend is a single FastAPI process. Adding Nginx/Kong for one service adds infra overhead with no routing benefit.

### E. OpenAPI auto-generated SDK now
**Deferred.** FastAPI already emits the spec. The blocker is setup time (generator config, C# template customization, CI regeneration step) relative to the 2–3 endpoints currently in use. Upgrade when the number of endpoints or team size makes the boilerplate cost visible.
