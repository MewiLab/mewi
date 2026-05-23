# Movement Reliability: Navigation Watchdog + Warp Recovery

## Context

The cat frequently gets stuck on obstacles during NavMesh navigation. `MalbersAnimalAdapter.IsBusy` now includes navigation, action execution, and action cooldown, but the core risk is the same: if Malbers/NavMesh never raises an arrival event and the cat stops getting closer to the destination, the worker can wait forever and the plan stalls (`go_to -> eat` never reaches `eat`).

For this prototype, the user has decided reliability beats naturalism: when the cat is stuck, we should briefly try to repath and then **warp/teleport** to the requested destination so the rest of the plan can continue. This applies to all navigation-style commands (`go_to`, `follow`, `wander`, `flee`).

## Goal

Add a self-recovering navigation watchdog that:

1. Detects "not getting closer to the destination for N seconds" while a navigation command is active.
2. First tries a repath (re-issue destination to Malbers or rebuild the manual NavMesh path).
3. If repath attempts are exhausted, warps the animal to the destination (NavMesh-projected if possible, raw transform position as final fallback) and marks the command complete so the next intent runs.
4. Records *why* the command completed (`Arrived`, `ArrivedAfterRepath`, `WarpedToNavMesh`, `WarpedRaw`, `Failed`) into the plan step report.

## File Layout (split to keep Motor/ maintainable)

`MalbersAnimalAdapter.cs` is already ~590 lines. To avoid bloating it, recovery logic lives in two small, single-purpose files:

- **DONE** [frontend/app/Assets/Scripts/Creature/Motor/NavigationRecoveryConfig.cs](frontend/app/Assets/Scripts/Creature/Motor/NavigationRecoveryConfig.cs)
  - `[Serializable]` class of tunables (intervals, thresholds, sample radius).
  - Exposed once on the adapter via `public NavigationRecoveryConfig recoveryConfig`.

- **DONE** [frontend/app/Assets/Scripts/Creature/Motor/NavigationWatchdog.cs](frontend/app/Assets/Scripts/Creature/Motor/NavigationWatchdog.cs)
  - Pure C# state machine. No Malbers, no NavMesh ops. ~120 lines.
  - Holds: start time, last-progress time, best distance to destination, repath attempt count, completion reason, active flag, destination.
  - Public API:
    - `enum NavigationRecoveryAction { Continue, Repath, Warp }`
    - `enum NavigationCompletionReason { None, Arrived, ArrivedAfterRepath, WarpedToNavMesh, WarpedRaw, Failed, Cancelled }`
    - `void Configure(NavigationRecoveryConfig)`
    - `void Begin(Vector3 destination, Vector3 currentPosition, float now)`
    - `void UpdateDestination(Vector3 destination, Vector3 currentPosition, float now)` — for follow (moving target)
    - `NavigationRecoveryAction Tick(Vector3 currentPosition, float now)` — driven by adapter each frame
    - `void NotifyArrivedNaturally()` / `NotifyWarpedToNavMesh()` / `NotifyWarpedRaw()` / `NotifyFailed()` / `Cancel()`
    - `NavigationCompletionReason CompletionReason { get; }`, `bool IsActive { get; }`, `int RepathAttempts { get; }`

- **EDIT** [frontend/app/Assets/Scripts/Creature/Motor/MalbersAnimalAdapter.cs](frontend/app/Assets/Scripts/Creature/Motor/MalbersAnimalAdapter.cs)
  - Add `public NavigationRecoveryConfig recoveryConfig = new NavigationRecoveryConfig();` (Header "Recovery").
  - Add `NavigationWatchdog _navWatchdog = new NavigationWatchdog();` + public `LastNavigationCompletionReason` getter.
  - In `Init()`: `_navWatchdog.Configure(recoveryConfig)`.
  - In `Apply(...)`: reset `LastNavigationCompletionReason = None`.
  - In `NavigateTo(...)` after `_hasActiveNavigationDestination = true`: `_navWatchdog.Begin(destination, AnimalPosition, Time.time)`.
  - In `NavigateTo` failure path: `_navWatchdog.NotifyFailed()` + mirror to `LastNavigationCompletionReason`.
  - In `ExecuteFollow(...)`: same `Begin(...)` call so follow gets recovery too.
  - In `OnAiArrived` / `OnAiPositionArrived`: `_navWatchdog.NotifyArrivedNaturally()` + mirror.
  - In `UpdateManualNavigation()` arrival branch: same notify + mirror.
  - In `Stop()`: `_navWatchdog.Cancel()`.
  - In `OnPreInput(...)` (existing per-frame hook), after `UpdateManualNavigation()`: call new private `TickNavigationWatchdog()` which:
    - If follow target is non-null, refresh destination via `UpdateDestination(target.position)`.
    - Switch on `_navWatchdog.Tick(AnimalPosition, Time.time)`:
      - `Continue` → nothing
      - `Repath` → reuse existing `TryEnsureMalbersAgentReady` + `aiControl.SetDestination(...)` (Malbers path) or `TryBuildManualPath(...)` (manual path).
      - `Warp` → new private `WarpToActiveDestination()`:
        1. `NavMesh.SamplePosition(_activeNavigationDestination, ..., recoveryConfig.warpNavMeshSampleRadius, AgentAreaMask())`
        2. If hit → `animal.transform.position = hit.position; agent.Warp(hit.position); _navWatchdog.NotifyWarpedToNavMesh()`.
        3. Else → `animal.transform.position = _activeNavigationDestination; _navWatchdog.NotifyWarpedRaw()` (best-effort `agent.Warp` if it's on a mesh nearby).
        4. `StopManualNavigation(true)`, `aiControl?.Stop()`, set `_hasArrived = true`, `_hasActiveNavigationDestination = false`, clear `_activeFollowTarget`. This makes `IsBusy` flip to false → worker advances.
        5. Mirror `LastNavigationCompletionReason`.
  - Augment `BuildNavigationDebug()` with `watchdogActive`, `repathAttempts`, `lastReason`.
  - If NavMesh projection fails for a non-zero destination, raw-warp instead of rejecting the command.
  - Include `ActionWatchdog` busy/cooldown state in `IsBusy` so snapshots wait for full animation/cooldown completion.

- **DONE** [frontend/app/Assets/Scripts/Creature/Motor/ActionExecutionConfig.cs](frontend/app/Assets/Scripts/Creature/Motor/ActionExecutionConfig.cs)
  - Configurable action start timeout, max duration, post-action cooldown, and cleanup behavior.

- **DONE** [frontend/app/Assets/Scripts/Creature/Motor/ActionWatchdog.cs](frontend/app/Assets/Scripts/Creature/Motor/ActionWatchdog.cs)
  - Pure timing state for Malbers action modes. Lets animations finish naturally, but asks the adapter to clean up if they never start or never end.

- **EDIT** [frontend/app/Assets/Scripts/Creature/Motor/CreatureWorker.cs](frontend/app/Assets/Scripts/Creature/Motor/CreatureWorker.cs)
  - In `CompleteActiveIntentIfReady()`, when the adapter reports a non-`None` `LastNavigationCompletionReason`, pass `reason.ToString()` into `RecordStep(... "completed", reason, ...)` so the backend sees `stuck_warped_to_navmesh` etc.
  - No schema change required — `PlanStepExecutionReport.reason` is already a free-form string.

## Reuse / Existing Building Blocks

- `TryEnsureMalbersAgentReady`, `TryProjectDestination`, `TryBuildManualPath`, `StopManualNavigation`, `AgentAreaMask`, `AnimalPosition`, `HorizontalDistance` — already in the adapter and reused by the recovery code.
- `OnPreInput` is already wired and known to fire each frame (it currently powers manual nav). Piggyback on it instead of adding a new `Update()`.
- `PlanStepExecutionReport.reason` already plumbs free-text through the report queue; no protocol changes.

## Default Tunables (initial values, designer-tunable in Inspector)

| Field | Value | Notes |
| --- | --- | --- |
| `progressCheckInterval` | `0.25s` | Sample 4× / sec, cheap. |
| `minProgressMeters` | `0.15m` | Cat must get this much closer to the destination. |
| `destinationMoveResetMeters` | `0.75m` | Moving follow targets can reset the progress reference when they really move. |
| `repathDelaySeconds` | `2s` | Give Malbers a chance to wiggle through. |
| `maxRepathAttempts` | `2` | After two repaths without progress → warp. |
| `hardTimeoutSeconds` | `12s` | Belt-and-suspenders escape even if progress is barely happening. |
| `warpNavMeshSampleRadius` | `2m` | If no NavMesh within 2 m of destination, fall back to raw transform move. |

## Verification

1. **Golden path (still works):**
   - Send `go_to → SM_Fish_1, eat → SM_Fish_1`. Step report shows `Arrived` for go_to, eat completes normally.
2. **Stuck-then-recover:**
   - Block the route between cat and SM_Fish_1 with a static obstacle outside the NavMesh.
   - Watch logs: expect `[MalbersAdapter] Watchdog repath (1/2)`, possibly `(2/2)`, then `Watchdog warped cat to NavMesh-projected destination …`.
   - Plan continues to `eat`; step report reason is `WarpedToNavMesh` (or `WarpedRaw`).
3. **Destination off-NavMesh:**
   - Aim at a point clearly off the NavMesh. Expect a warning + raw warp; cat ends up at requested transform position; plan continues.
4. **Follow / wander / flee:**
   - Force the cat against a wall while following. Expect repath then warp; `bodyBusy=True` never sticks.
5. **Action commands:**
   - eat / sit / sleep complete via `OnAnimalModeEnded` when Malbers emits it.
   - If Malbers loops or never starts the mode, `ActionWatchdog` times out, forces cleanup, waits through cooldown, and releases the queue.

## Out of Scope

- No backend schema changes.
- No tuning of obstacle layout or NavMesh bake settings — recovery is the fallback.
- Cosmetic teleport effects (particles, brief fade) — easy to add later if naturalism becomes a priority.

## Current Companion Docs

- [docs/current_workflow.md](../current_workflow.md) has the current backend/Unity/worker flow.
- [docs/current_need_to_fix.md](../current_need_to_fix.md) has the Unity play-mode verification checklist and remaining risks.
