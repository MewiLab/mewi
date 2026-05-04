# Snapshot Refactor + Spatial Channel — Done

This document summarises the snapshot decoupling refactor and the new spatial-context
channel that lands the **Spatial** semantic channel from `planning.md`.

---

## 1. Why this refactor

Before:

- `AgentMindBridge` (in `Creature/Layers/Mind/`) was doing **three** jobs:
  1. Reading the blackboard
  2. Building the wire-format JSON (knew about `self`, `mood`, `health`, `entities`)
  3. POSTing + polling + parsing the response
- Adding a new perception channel meant editing `AgentMindBridge`. That file is
  the wrong place — the bridge should not know what is in the snapshot.

After (3-way responsibility split):

| Concern | Owner |
|---|---|
| **When** to send | `PeriodicMind` (timer) |
| **What** to build | `SnapshotManager` (channel registry) |
| **How** to send  | `AgentMindBridge` (POST + poll + parse) |

Adding a new channel = implement `ISnapshotChannel` + register. Bridge is untouched.

---

## 2. Files added

### `AgentIntegration/Snapshot/`
- `SnapshotPayload.cs` — wire format DTOs (`SelfData`, `MoodData`, `HealthData`,
  `EntityData`, `SpatialData`). Lifted out of `AgentMindBridge` and made
  top-level so channels can populate them.
- `ISnapshotChannel.cs` — channel contract:
  ```csharp
  string ChannelId { get; }
  void Write(SnapshotPayload payload, CreatureBlackboard board, Transform self);
  ```
- `SnapshotManager.cs` — `MonoBehaviour` that holds an ordered list of channels
  and produces JSON. `Register(ISnapshotChannel)` is public for future channels
  registered from elsewhere. `BuildJson(requestId)` iterates channels.

### `AgentIntegration/Snapshot/Channels/`
- `SelfChannel.cs` — writes flat `location` (joins `currentZones`) +
  `current_action` from `ResolveActiveIntent`.
- `MoodChannel.cs` — copies `MoodModel` into the wire DTO.
- `HealthChannel.cs` — copies `health.hunger`.
- `EntitiesChannel.cs` — eye-perception summariser. Took the
  `SummariseEntities` + `DirectionBucket` logic out of `AgentMindBridge`. Sort
  by intensity, cap per-category, take top N.
- `SpatialChannel.cs` — **new**. Reads the hierarchical zone state from the
  blackboard and writes `spatial_context = { location_hierarchy, confinement,
  surface_material }`.

### `AgentIntegration/Perception/Spatial/  (ZoneScanner)  +  Semantics/Markup/Spatial/  (ZoneVolume, ConfinementLevel)`
- `ConfinementLevel.cs` — `Open | Semi | Confined`.
- `ZoneVolume.cs` — hand-authored marker for a hierarchical place
  (Harbor / Boat_03 / Deck). Carries `zoneId`, `ZoneLayer` (`District / Area /
  Surface`), `confinement`, `surfaceMaterial`. `RequireComponent(typeof(Collider))`.
- `ZoneScanner.cs` — trigger-driven (`OnTriggerEnter` / `OnTriggerExit`)
  membership tracker. On `Init()` it does a one-shot `OverlapSphere` to seed
  zones the cat already stands inside. On `Tick()` it sorts the active set
  (by `ZoneLayer` then collider volume) and writes `locationHierarchy`,
  `confinement`, `surfaceMaterial` to the blackboard.

## 3. Files changed

### `AgentIntegration/Bridge/AgentMindBridge.cs`
Now transport-only:
- `Init(SnapshotManager snapshot)` — new signature; takes the manager.
- `SendTick(board)` — delegates to `_snapshot.BuildJson(id)` and POSTs.
- Removed: `TickPayload`, `SelfData`, `MoodData`, `HealthData`, `EntityData`
  nested types (now top-level under `Snapshot/`), `BuildSnapshotJson`,
  `SummariseEntities`, `DirectionBucket`, `JoinZones`, `maxEntities`,
  `maxPerCategory` Inspector fields.
- Kept: `LLMIntent` output type, all polling + response-parsing code,
  `namedTargets` resolver, target-resolve coroutine.

### `Creature/Core/CreatureBlackBoard.cs`
Added the spatial slice (alongside, not replacing, the existing flat
`currentZones` HashSet from `SmartZoneTracker`):
```csharp
[HideInInspector] public List<string>     locationHierarchy = new List<string>();
[HideInInspector] public ConfinementLevel confinement       = ConfinementLevel.Open;
[HideInInspector] public string           surfaceMaterial   = "";
```

### `Creature/Core/CreatureController.cs`
Wires up the two new components:
- `GetComponent<SnapshotManager>()` and `GetComponent<ZoneScanner>()` in `Awake()`.
- `_snapshot.Init(_board)` runs **before** `_mindBridge.Init(_snapshot)` so the
  bridge gets a non-null reference.
- `_zoneScanner.Tick()` runs in `Update()` between perception and reflex —
  spatial state is fresh before any layer reads it.

### `AgentIntegration/Bridge/PeriodicMind.cs`
Doc-comment updated to describe the new responsibility split. No code change —
it still calls `bridge.SendTick(_board)` and `bridge.TryConsumeResponse(...)`,
both unchanged at the bridge boundary.

## 4. Files NOT changed (intentionally)

- `AgentIntegration/Perception/CreaturePerception.cs` — already separates
  eye perception cleanly. No coupling to fix.
- `AgentIntegration/Perception/SmartZoneTracker.cs` — kept as-is. Writes flat
  `currentZones` from `zone.*`-prefixed `SmartObject` tags. Still consumed by
  `SelfChannel` for the legacy `self.location` field.
- `Semantics/Markup/SmartObject.cs`, `SemanticCategoryConfig.cs`, baker —
  eye perception infra is separate from the new spatial channel.
- `Semantics/SemanticZone.cs` — deprecated by `SmartObject` (per
  `planning.md`); deleted as part of the structural move.
- `CreatureMotor.cs`, `CreatureBrain.cs`, reflex layers — nothing in the
  motor / tactical / reflex layers cares how the snapshot is built.

## 5. Wire-format change (Unity → backend)

The POST body now has one extra top-level field:

```json
{
  "requestId": "...",
  "time": 12.4,
  "self":  { "location": "harbor", "current_action": "wander" },
  "mood":  { "fear": 0.1, "trust": 0.4, "curiosity": 0.6, "social": 0.3, "energy": 0.8 },
  "health": { "hunger": 0.2 },
  "entities": [ ... ],
  "spatial_context": {
    "location_hierarchy": ["Harbor", "Boat_03", "Deck"],
    "confinement": "Semi",
    "surface_material": "Wood"
  }
}
```

The previous wire format also had a top-level `self` with `x/y/z/rotY/...` —
that's been gone since the move to the layered architecture. This refactor
does not regress that.

> **Backend follow-up (out of scope here):**
> `backend/app/agent/perceive*.py` should accept (and ignore, until needed)
> the new `spatial_context` field. Adding a Pydantic model for it on the
> Python side is the natural next step.

## 6. Unity Inspector migration steps

The cat prefab needs two new components added in the Inspector:

1. **`SnapshotManager`** on the cat root (same GameObject as
   `AgentMindBridge` / `PeriodicMind`).
   - `maxEntities` and `maxPerCategory` moved here from `AgentMindBridge`.
     Defaults: 8 / 2. **If you had non-default values on the bridge, copy
     them to `SnapshotManager`.** The fields no longer exist on the bridge.
2. **`ZoneScanner`** on the cat root.
   - Set `zoneLayers` to the new `SemanticZone` layer (or whichever you use
     for `ZoneVolume` triggers).
   - The cat already has a trigger collider for `SmartZoneTracker`; the
     same collider serves `ZoneScanner` (Unity forwards trigger callbacks
     to all `MonoBehaviour`s on the Rigidbody root).

To author zones in the scene:

3. Create empty GameObjects inside parent areas; for each, add a trigger
   `Collider` sized to its footprint, set the layer to `SemanticZone`,
   add `ZoneVolume`, fill in `zoneId` (Harbor / Boat_03 / Deck), pick
   `ZoneLayer` (District / Area / Surface), and `confinement`.
4. The hierarchy is automatic: the smallest enclosing zone (`Surface`)
   ends up last in `location_hierarchy`. No parent–child link needed.

## 7. Open items / future channels

The plan calls out three more channels behind this refactor's interface:

- **AmbientChannel** — light, sound, heat. Will read from a future
  `AmbientSampler` perception component and write `payload.ambient`.
- **AffordanceChannel** — what can the cat do here, right now? Reads
  `SmartObject` tags + spatial state.
- **SocialChannel** — who is near, what are they doing? Reads existing
  `closestPlayer`/`playerInSight` + later NPC entries.

Each of these is a one-class addition: implement `ISnapshotChannel`,
register it in `SnapshotManager.RegisterDefaultChannels()`, add a slot to
`SnapshotPayload`. The bridge, the mind, and the rest of the perception
stack do not change.

A second future cleanup: once `ZoneVolume` covers the village, the flat
`currentZones` / `SmartZoneTracker` channel can be retired. For now both
coexist so the existing wire field `self.location` keeps working.

---

## 8. Folder restructure (follow-up move)

The original refactor landed everything under `Creature/Layers/Mind/...` and
`Creature/Layers/Perception/...`, which mixed two responsibilities:
*creature-local logic* and *backend-integration plumbing*. After review the
files were moved to honour the dependency rule: `AgentIntegration` and
`Creature` are peers; both depend on `Semantics/Markup`; neither depends on
the other.

Final layout under `frontend/app/Assets/Scripts/`:

```
AgentIntegration/                 ← talks to the Python backend
├── Bridge/                       ← transport
│   ├── AgentBridge.cs            (was Infrastructure/AgentBridge.cs)
│   ├── AgentMindBridge.cs        (was Creature/Layers/Mind/)
│   └── PeriodicMind.cs           (was Creature/Layers/Mind/)
├── Perception/                   ← reads world markup
│   ├── CreaturePerception.cs     (was Creature/Layers/Perception/)
│   ├── SmartZoneTracker.cs       (was Creature/Layers/Perception/)
│   └── Spatial/
│       └── ZoneScanner.cs        (was Creature/Layers/Perception/Spatial/)
└── Snapshot/                     ← assembles the JSON payload
    ├── Channels/{Self,Mood,Health,Entities,Spatial}Channel.cs
    ├── ISnapshotChannel.cs
    ├── SnapshotManager.cs
    └── SnapshotPayload.cs

Creature/                         ← physical vessel + local logic only
├── Core/                         (unchanged)
├── Motor/CreatureMotor.cs        (was Creature/Layers/Body/)
├── Reflexes/{Avoidance,Flinch,Gaze,IReflex,CreatureReflexRunner}.cs
│                                 (was Creature/Layers/Relax/)
├── Tactical/CreatureBrain.cs     (was Creature/Layers/Tactical/)
└── Navigation/                   (placeholder)

Semantics/                        ← world markup only
├── Editor/SmartObjectBaker.cs
└── Markup/
    ├── SemanticCategoryConfig.cs + .asset
    ├── SmartObject.cs
    └── Spatial/
        ├── ConfinementLevel.cs
        └── ZoneVolume.cs         (designer-placed; ZoneScanner reads it)

Test/                             (unchanged)
```

**Why `ZoneVolume` is in `Semantics/Markup/Spatial/` but `ZoneScanner` is in
`AgentIntegration/Perception/Spatial/`:** `ZoneVolume` is pure data — a
designer drops one in the scene and it has no scanning logic. `ZoneScanner`
is the *reader* that turns those volumes into per-tick perception output.
Keeping them in different folders enforces the "no upward dependencies"
rule: `Semantics` never imports from `AgentIntegration`.

**Cleanup that happened during the move:**
- Deleted deprecated `Semantics/SemanticZone.cs` (superseded by `SmartObject`).
- Resolved the duplicate `SemanticCategoryConfig.asset` — the older tracked
  one in `Semantics/` was removed; the newer working copy in
  `Creature/Layers/Perception/` (richer rules: Boat, fish_net, lantern,
  furniture, etc.) was promoted to `Semantics/Markup/SemanticCategoryConfig.asset`.
- Removed empty `Creature/Layers/` and `Infrastructure/` folder trees plus
  their orphaned `.meta` files.

**Unity import note:** Folder `.meta` files for the new top-level dirs
(`AgentIntegration/`, `Creature/Motor/`, etc.) will be regenerated by Unity
on next refresh. Existing `.cs` and `.asset` `.meta` files moved with their
files, so prefab and scene GUID references stay valid — no broken script
references in the cat prefab.
