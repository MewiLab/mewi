# ADR-036: Cat NavMesh Corridor Stability

## Status

Proposed

## Date

2026-06-06

## Context

The Unity cat navigation stack uses Unity NavMesh for route planning and Malbers for animal locomotion. In practice this means the NavMeshAgent and the visible cat body do not have the same authority:

- The NavMeshAgent computes a path and tracks an internal simulated position.
- Malbers moves the rendered animal body through animation/root-motion-style movement.
- `MAnimalAIControl` disables direct NavMeshAgent transform updates with `Agent.updatePosition = false` and `Agent.updateRotation = false`.
- The cat prefab keeps the NavMeshAgent on an `AI Core` child object rather than on the animal root.
- `MalbersAnimalAdapter` samples destinations, validates path safety, and may fall back to manual navigation or teleport backup.

This creates a common failure mode: the path can be valid on the NavMesh, while the visible cat appears to walk on uncolored or unbaked ground. The blue NavMesh overlay in the Unity Scene view is only a visualization, not the rule that physically constrains the rendered animal. If the movement controller is decoupled from the NavMeshAgent, the cat can drift, overshoot corners, or be nudged outside the intended road corridor even while the planner still believes the route is valid.

Project inspection found several risk factors:

- `MAnimalAIControl` sets `updatePosition = false`, so Unity does not automatically keep the transform on the NavMesh.
- Current manual fallback movement drives `animal.Move(...)` along calculated path corners, but does not explicitly clamp the body back to the NavMesh corridor.
- Cat prefabs use `m_WalkableMask: 4294967295`, allowing all NavMesh areas unless overridden at runtime.
- The NavMesh area setup includes `Walkable`, `Not Walkable`, `Jump`, `EdgeDanger`, and `Safe`, but the cat agent is not yet using a narrow road-only area policy.
- The active NavMeshSurface in `Fishing_Village.unity` collects all objects and all layers, which can bake adjacent geometry unless constrained by modifiers, layers, or surface settings.
- Some unreachable `go_to` cases can use teleport backup, which can hide route quality problems during testing.

Unity's own guidance matches this diagnosis:

- When `NavMeshAgent.updatePosition` is false, the transform and simulated agent position are not synchronized automatically.
- `NavMeshAgent.nextPosition` is the bridge between the internal agent position and the externally moved body.
- Unity recommends choosing one movement authority when mixing NavMeshAgent, Animator, Rigidbody, or custom movement.
- For animation-driven agents, Unity shows patterns where the character follows the agent, or the agent is pulled toward the character when drift exceeds the agent radius.
- `NavMesh.CalculatePath` and `NavMeshAgent.CalculatePath` may produce partial paths, so callers must check `path.status`, not only the boolean return value.
- `NavMesh.SamplePosition` finds the nearest NavMesh point but does not guarantee that the result is on the intended road or visible path.
- Area masks and area costs are the intended way to make agents prefer or reject different baked regions.

## Decision

Adopt a corridor-authoritative navigation policy for cats.

For normal cat `go_to` behavior, the NavMesh path corridor is the source of truth. Malbers remains the locomotion and animation layer, but it must be continuously reconciled with the NavMesh planner so the visible cat cannot silently drift away from the planned road corridor.

The cat navigation pipeline will use these rules:

1. Road paths must be represented as explicit NavMesh policy, not inferred from blue Scene-view color.
2. The cat agent must plan only through allowed areas for normal walking.
3. The visible cat body and the NavMeshAgent internal position must be synchronized every navigation tick.
4. Drift outside the path corridor must be detected and corrected.
5. Fallback movement must obey the same corridor policy as Malbers-driven movement.
6. Teleport fallback must be treated as an exceptional recovery path, not a normal solution for bad routes.
7. Navigation debugging must show both the planned path and the body/agent divergence.

## Implementation Plan

### 1. Define Cat Navigation Areas

Add or formalize NavMesh areas for cat movement:

- `CatRoad` or `Safe`: normal walkable road/path area.
- `EdgeDanger`: high-cost or forbidden area near cliffs, water edges, roof edges, and visual-road boundaries.
- `Not Walkable`: forbidden for normal cat `go_to`.
- Optional `CatShortcut`: explicitly allowed shortcuts if design wants cats to use them.

Normal `go_to` should use an area mask that allows only intended cat walking areas. It should not use `NavMesh.AllAreas` by default.

Recommended default:

```csharp
var catAreaMask =
    (1 << NavMesh.GetAreaFromName("CatRoad")) |
    (1 << NavMesh.GetAreaFromName("Safe"));

agent.areaMask = catAreaMask;
```

If `Safe` is already the intended road area, use `Safe` as the first implementation and add `CatRoad` only when the level design needs clearer separation.

### 2. Bake Roads Deliberately

The NavMeshSurface should collect only intended navigation geometry where possible:

- Prefer a dedicated navigation layer for road/path meshes.
- Configure `NavMeshSurface.Include Layers` to include that layer instead of everything.
- Use `NavMeshModifier` and `NavMeshModifierVolume` to mark adjacent risky areas as `Not Walkable` or `EdgeDanger`.
- Avoid relying on the visual material color of a mesh to imply navigation behavior.

Scene-view blue color should be treated as a debug overlay only. The contract should be: if cats may walk there, it must be in the cat area mask; if cats may not walk there, it must be excluded or marked forbidden/high-cost.

### 3. Synchronize Agent And Body Each Tick

Because Malbers owns the visible animal movement, the adapter should continuously reconcile the NavMeshAgent with the animal body.

At minimum, after Malbers moves the animal:

```csharp
if (agent != null && agent.isOnNavMesh)
{
    agent.nextPosition = animal.transform.position;
}
```

However, synchronization should not blindly accept any off-mesh body position. The preferred approach is:

- Sample the animal body position against the allowed cat area mask.
- If the body is still inside the allowed corridor, sync `agent.nextPosition` to the body.
- If the body has drifted outside the allowed corridor, pull the body back toward the last valid NavMesh point or toward `agent.nextPosition`.

Example policy:

```csharp
var bodyPosition = animal.transform.position;

if (NavMesh.SamplePosition(bodyPosition, out var hit, bodySampleRadius, catAreaMask))
{
    lastValidNavMeshPosition = hit.position;
    agent.nextPosition = hit.position;
}
else
{
    var corrected = Vector3.MoveTowards(bodyPosition, lastValidNavMeshPosition, correctionSpeed * Time.deltaTime);
    animal.transform.position = corrected;
    agent.nextPosition = corrected;
}
```

### 4. Clamp Drift By Corridor Distance

Add drift checks during active navigation:

- Distance between `animal.transform.position` and `agent.nextPosition`.
- Distance between `animal.transform.position` and the nearest allowed NavMesh point.
- Distance to the closest NavMesh edge using `NavMesh.FindClosestEdge`.
- Distance from the body to the current path segment.

If drift exceeds a soft threshold, steer back toward the corridor. If it exceeds a hard threshold, warp or reposition to the last valid point.

Suggested defaults:

- Soft drift threshold: `agent.radius * 0.5f` to `agent.radius`.
- Hard drift threshold: `agent.radius * 2f`.
- Edge clearance threshold: at least the existing `NavPathSafety.minNavMeshEdgeDistance` value, currently around `0.25`.

### 5. Make Manual Fallback Corridor-Aware

The manual navigation fallback currently follows calculated path corners through `animal.Move(...)`. It should use the same allowed area mask and drift correction as normal Malbers navigation.

Manual fallback should:

- Calculate paths with the cat area mask.
- Reject `NavMeshPathStatus.PathPartial` and `PathInvalid` for normal movement.
- Snap each path corner to the allowed cat area before use.
- Clamp the body to the allowed NavMesh during movement.
- Repath if the body leaves the corridor or if the next corner becomes invalid.

Manual fallback should not become a bypass that lets the body walk over geometry the NavMeshAgent would reject.

### 6. Harden Destination Sampling

Before any `SetDestination` or manual path request:

- Sample the requested destination using the cat area mask, not `NavMesh.AllAreas`.
- Use a bounded radius appropriate to the cat and level scale.
- Validate that the resulting path is complete.
- Reject sampled points that land on forbidden or risky areas.

Important: `NavMesh.SamplePosition` returns the nearest NavMesh point, not necessarily the nearest intended road. Large sample radii can snap a target to the wrong surface, nearby roof, bridge, or off-road island. Destination sampling should be small by default and design-controlled through anchors when the requested target is not directly reachable.

### 7. Restrict Teleport Backup

Teleport fallback is useful as a recovery tool, but it should not hide navigation bugs.

Change normal `go_to` behavior so teleport backup is disabled by default during navigation validation and QA. Keep it available for emergency recovery states such as:

- Cat is permanently stuck.
- Cat falls out of world.
- Current position is not on any allowed NavMesh after repeated correction attempts.
- Player action requires a scripted reposition.

When teleport fallback occurs, emit a clear navigation diagnostic event with:

- Requested destination.
- Sampled destination.
- Last complete path status.
- Agent position.
- Animal body position.
- Last valid NavMesh position.
- Reason teleport was selected.

### 8. Add Debug Visualization

Add a runtime debug mode for cat navigation:

- Draw the planned NavMesh path corners.
- Draw the current steering target.
- Draw `agent.nextPosition` and the animal body position separately.
- Draw a line between `agent.nextPosition` and `animal.transform.position` to show divergence.
- Draw nearest allowed NavMesh sample point.
- Color paths by status: complete, partial, invalid, fallback, teleport.

The first diagnostic question should be:

- If the debug path stays on the road but the cat body leaves it, the problem is movement synchronization/drift.
- If the debug path itself leaves the road, the problem is NavMesh bake, area mask, costs, or destination sampling.

## Consequences

### Positive

- Cats will stop silently walking outside intended road/path corridors.
- Visual movement will match the route planned by NavMesh.
- Navigation bugs become easier to classify as either bake/policy problems or movement-coupling problems.
- Designers can control cat walkability through NavMesh areas, modifiers, and layers instead of relying on visual color.
- Teleport fallback will no longer mask ordinary route failures.

### Negative

- More runtime checks are needed during navigation.
- Some previously accepted destinations may now be rejected if they are not on allowed cat navigation areas.
- Levels may need NavMeshModifier cleanup or road-layer authoring.
- Tight paths may need wider bakes, bigger edge margins, or better corner smoothing.

### Neutral

- Malbers remains the locomotion system.
- Unity NavMesh remains the planner.
- The blue NavMesh overlay remains useful for debugging, but it is not treated as the behavioral contract.

## Alternatives Considered

### Let NavMeshAgent Directly Move The Cat

This would restore Unity's built-in transform clamping, but it would fight Malbers animation and movement. Unity recommends avoiding competing movement authorities. This option would likely reduce animation quality and create new controller conflicts.

### Keep Current Behavior And Increase Agent Radius Only

Increasing bake radius is still useful because it gives the cat more clearance from edges. However, radius alone does not solve the core decoupling problem when the visible body is moved outside the agent corridor.

### Use Teleport Whenever The Path Is Unstable

Teleporting avoids visible navigation failures, but it breaks player trust and hides the underlying route problem. Teleport should remain a recovery mechanism, not a normal navigation strategy.

### Trust Scene-View Blue NavMesh Color

The blue overlay is useful for human inspection, but it does not prove the runtime agent's area mask, sampled destination, path status, or body position. Runtime diagnostics are required.

## Validation

A navigation test scene or play-mode test should verify:

- Cat can complete `go_to` on connected road paths.
- Cat refuses or reroutes when destination is outside allowed cat areas.
- Cat does not walk across unallowed adjacent ground when a connected road route exists.
- Cat body and `agent.nextPosition` divergence stays under the configured soft threshold during normal movement.
- Manual fallback obeys the same area mask and drift correction as normal navigation.
- Teleport fallback emits diagnostics and does not trigger in ordinary connected-road routes.

Manual QA should include:

- Draw path-corner debug lines during `go_to`.
- Compare planned path against visible cat body path.
- Test narrow turns, bridges, slopes, and road edges.
- Temporarily disable teleport backup while validating route quality.

## References

- Unity Scripting API: `NavMeshAgent.updatePosition`
- Unity Scripting API: `NavMeshAgent.nextPosition`
- Unity Manual: Coupling Animation and Navigation
- Unity Manual: Using NavMesh Agent with Other Components
- Unity AI Navigation package manual: `NavMeshSurface`
- Unity Manual: Navigation Areas and Costs
- Unity Scripting API: `NavMesh.CalculatePath`
- Unity Scripting API: `NavMeshAgent.CalculatePath`
- Unity Scripting API: `NavMeshAgent.pathStatus`
- Unity Scripting API: `NavMesh.SamplePosition`
- Unity Scripting API: `NavMesh.FindClosestEdge`
- Unity AI Navigation package manual: `NavMeshModifier`
