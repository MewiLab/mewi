# FeelingEmitter Implementation Guide

## Summary

This guide describes how to implement the general `FeelingEmitter` system in
the current Unity codebase.

The intended data flow is:

```text
FeelingEmitter on objects/zones
  -> CreaturePerception scans active detectable aspects
  -> CreatureBlackboard.feelingEvents
  -> FeelingsChannel
  -> SnapshotPayload.feelings
  -> LLM tick envelope
```

The implementation should not replace existing sight and spatial channels.
`entities` and `spatial_context` stay stable. `feelings` is a new snapshot
channel beside them.

## Current Architecture Touchpoints

Relevant existing systems:

- `CreaturePerception`: already scans creatures and `SmartObject` semantic
  props on a tick.
- `CreatureBlackboard`: stores per-tick `sensorEvents` and spatial state.
- `SnapshotPayload`: defines the JSON payload sent to the backend.
- `SnapshotManager`: registers ordered `ISnapshotChannel` instances.
- `EntitiesChannel`: summarizes current `sensorEvents` for visible/nearby
  entities.
- `SpatialChannel`: summarizes current `ZoneVolume` context.
- `SmartObject`: semantic identity for props and targets.
- `ZoneVolume`: authored place volumes.

Add feelings by following the same pattern instead of special-casing transport
or backend networking.

## Files To Add

Add authored feeling types under `Assets/Scripts/Semantics/Markup/Feelings/`:

- `FeelingSense.cs`
- `FeelingTriggerMode.cs`
- `FeelingAspect.cs`

Add the detected runtime model under `Assets/Scripts/Creature/Core/models/`:

- `FeelingEvent.cs`

Add emitter/relay files under `Assets/Scripts/Semantics/Markup/Feelings/`:

- `Assets/Scripts/Semantics/Markup/Feelings/FeelingEmitter.cs`
- `Assets/Scripts/Semantics/Markup/Feelings/FeelingCollisionRelay.cs`
- `Assets/Scripts/Semantics/Markup/Feelings/FeelingContactRelay.cs`

Add snapshot channel:

- `Assets/Scripts/AgentIntegration/Snapshot/Channels/FeelingsChannel.cs`

Modify existing files:

- `CreatureBlackBoard.cs`
- `CreaturePerception.cs`
- `SnapshotPayload.cs`
- `SnapshotManager.cs`
- `CreatureConfig.cs`

## Public Types

### FeelingSense

```csharp
public enum FeelingSense
{
    Smell,
    Sound,
    Texture,
    Temperature,
    Moisture,
    Vibration,
    Taste,
    Comfort,
    Danger
}
```

### FeelingTriggerMode

```csharp
public enum FeelingTriggerMode
{
    AlwaysOn,
    StateBased,
    TimedEvent,
    Collision,
    Kick,
    Fall,
    EatenOrUsed,
    EnvironmentModified,
    ContactOnly
}
```

`Collision`, `Kick`, `Fall`, and `EatenOrUsed` can be implemented as named
timed triggers internally. Keep the enum because it makes authoring clear in
the Inspector.

### FeelingAspect

Serializable authored data on a `FeelingEmitter`.

Fields:

- `FeelingSense sense`
- `string description`
- `float radius`
- `float strength`
- `FeelingTriggerMode trigger`
- `string triggerName`
- `string requiredState`
- `float duration`
- `string meaning`
- `bool includeInSummary`

Validation rules:

- Clamp `strength` to 0..1.
- Distance senses use `radius > 0`.
- Contact-only aspects can use radius 0.
- Timed/event aspects should have a positive `duration`.
- Empty `description` aspects should be ignored.

### FeelingEvent

Runtime event detected by the cat.

Fields:

- `FeelingSense sense`
- `Vector3 position`
- `float intensity`
- `float timestamp`
- `Transform source`
- `string sourceLabel`
- `string description`
- `string meaning`
- `string triggerName`
- `bool contact`

Add helper methods:

- `Create(...)` factory.
- `ToSnapshotString(Transform self)` or equivalent formatting helper.

The snapshot string should include:

- Strength bucket: `strong`, `clear`, `soft`, `faint`.
- Direction bucket: same 8-way style as `EntitiesChannel`, plus `below`,
  `above`, `contact`, or `all_around` when appropriate.
- Distance bucket: `contact`, `near`, `mid`, `far`, or `ambient`.
- Description, source label, and meaning.

Example:

```text
strong front_left near: old fish oil from FishCrate; edible and interesting
```

### FeelingEmitter

Passive component attached to objects or zones.

Responsibilities:

- Store authored `FeelingAspect` entries.
- Store lightweight active states such as `wet`, `burning`, `fresh`, `rotten`,
  `moving`, `broken`, or `familiar`.
- Store timed trigger expirations by trigger name.
- Expose query methods for `CreaturePerception`.

Recommended API:

```csharp
public class FeelingEmitter : MonoBehaviour
{
    public string label;
    public Transform perceptionCenter;
    public List<FeelingAspect> aspects;

    public Vector3 Position { get; }
    public string Label { get; }

    public void SetState(string state, bool active);
    public bool HasState(string state);
    public void EmitTrigger(string triggerName);
    public void EmitTrigger(string triggerName, float durationOverride);
    public bool TryBuildEvent(
        FeelingAspect aspect,
        Transform self,
        CreatureConfig config,
        out FeelingEvent evt);
}
```

Implementation notes:

- `FeelingEmitter` should not scan for cats.
- It should not write to the blackboard directly.
- It should not allocate every frame when idle.
- If `label` is empty, prefer `SmartObject.Label`, then parent name, then own
  GameObject name.
- If `perceptionCenter` is empty, prefer `SmartObject.Position`, then own
  transform position.

## Blackboard Changes

Add to `CreatureBlackboard`:

```csharp
public List<FeelingEvent> feelingEvents = new List<FeelingEvent>();
```

Clear this list in `CreaturePerception.ScanEnvironment()` at the same time
`sensorEvents` is cleared.

Keep feelings separate from `sensorEvents`. The existing `EntitiesChannel`
should continue to summarize object/entity perception only.

## CreatureConfig Changes

Add tunables:

```csharp
[Header("Feelings")]
public float feelingScanRadius = 12f;
public int maxFeelingEvents = 16;
public int maxSmellStrings = 4;
public int maxSoundStrings = 4;
public int maxSignalStrings = 6;
```

Use `feelingScanRadius` as the broad scan radius. Individual aspect radii still
decide whether a specific aspect is detectable.

## CreaturePerception Changes

Add a new serialized layer mask and scan buffer:

```csharp
[Header("Feeling Scan")]
public LayerMask feelingLayer;
readonly Collider[] _feelingBuffer = new Collider[64];
```

Recommended layer setup:

- Use `SemanticProp` for prop feeling emitters when they live beside
  `SmartObject`.
- Use `SemanticZone` for zone ambient feelings when they live on `ZoneVolume`.
- If a dedicated `Feeling` layer is added later, include it in `feelingLayer`.

Call `ScanFeelings()` after `ScanSmartObjects()`.

`ScanFeelings()` should:

- Overlap sphere around the cat using `feelingScanRadius`.
- Find `FeelingEmitter` with `GetComponentInParent<FeelingEmitter>()`.
- Dedupe by emitter instance.
- Ask each emitter for active aspects.
- Convert detectable aspects into `FeelingEvent`s.
- Sort by intensity and priority.
- Cap to `maxFeelingEvents`.
- Write to `_board.feelingEvents`.

Contact-only aspects:

- V1 uses relay-maintained contact state on `FeelingEmitter`.
- `FeelingContactRelay` calls `MarkContact(other.transform, true/false)`.
- Only emit contact-only aspects when the current cat is touching the object or
  is inside the contact volume.

Important fix:

The existing `CreaturePerception.OnSoundHeard(Vector3 soundPos, float loudness)`
calls `EmitEvent(..., null, ...)`, but `EmitEvent` dereferences `src.position`.
When updating sound support, either remove this path or change it to create an
event directly from the provided position. Do not keep a null `Transform`
path that can throw.

## Snapshot Payload Changes

Add to `SnapshotPayload`:

```csharp
public FeelingsData feelings;
```

Add serializable payload classes:

```csharp
[Serializable]
public class FeelingsData
{
    public string summary;
    public string[] smells;
    public string[] sounds;
    public string[] signals;
}
```

Keep these as strings for v1. The backend can read them immediately, and the
Unity side can still preserve structure internally with `FeelingEvent`.

## FeelingsChannel

Add `FeelingsChannel : ISnapshotChannel`.

Responsibilities:

- Read `board.feelingEvents`.
- Sort by priority.
- Convert events into compact strings.
- Split strings by sense:
  - `Smell` -> `smells`
  - `Sound` -> `sounds`
  - all other senses -> `signals`
- Apply caps from `CreatureConfig` or constructor arguments.
- Build one `summary` string from the strongest few events.

Register in `SnapshotManager.RegisterDefaultChannels()` after
`SpatialChannel()`:

```csharp
Register(new FeelingsChannel(maxSmellStrings, maxSoundStrings, maxSignalStrings));
```

If keeping channel constructors simple, expose the caps on `SnapshotManager`
instead of passing all of `CreatureConfig`.

## Trigger Relays

### FeelingCollisionRelay

Attach to objects that should produce impact, kick, or fall feelings.

Behavior:

- On collision above a velocity/impulse threshold, call `EmitTrigger("impact")`.
- If the collider belongs to the player/cat and horizontal impact is high,
  call `EmitTrigger("kicked")`.
- If the object was falling and then hits the ground, call `EmitTrigger("fell")`.

Keep thresholds serialized so designers can tune them per prefab.

### FeelingContactRelay

Attach to contact volumes for texture, taste, temperature, danger, and comfort.

Behavior:

- On trigger enter by the cat, mark contact active on the emitter.
- On trigger exit, clear contact.
- V1 can support one controlled cat; multi-creature support can store contact
  by `CreatureBlackboard.CreatureId` later.

## Scene Authoring

### Props

Attach `FeelingEmitter` to the existing `SemanticProp` child beside
`SmartObject` when the feeling belongs to a prop.

Examples:

- Fish basket: smell, taste, food comfort.
- Rope: texture, rope scrape sound, dry/wet smell.
- Barrel: hollow wood smell, impact sound, vibration.
- Lantern: warm metal, faint oil smell, danger if hot.

### Zones

Attach `FeelingEmitter` to `ZoneVolume` objects for ambient place context.

Examples:

- Harbor: salt water, damp wood, water lapping, humid air.
- Boat deck: swaying vibration, creaking wood, fish traces.
- Cabin: confined warm air, old fabric, safe hiding comfort.
- Market: mixed food smell, voices/footsteps, busy danger/curiosity.

### Dynamic Sources

Attach dynamic sound/impact feelings to the physical source:

- Water edge for splashes and lapping.
- Boat hull for creaks and knocks.
- Rope/chain for scraping or clinking.
- Player movement source for footsteps.
- Creature root for vocalization, fur smell, movement sounds.

## Presets

After the runtime model works, add authoring presets or ScriptableObjects for
common categories. This avoids hand-writing every common aspect.

Recommended v1 presets:

- Fish
- Water
- WetWood
- DryWood
- Rope
- Fire
- Lantern
- Fabric
- Metal
- Food
- Creature
- HumanPlayer
- Shelter

Presets can be copied into a `FeelingEmitter` at authoring time. Runtime should
not need to resolve name patterns every tick.

## Acceptance Tests

Manual Play Mode scenarios:

- Fish behind the cat still appears in `feelings.smells`.
- A kicked barrel produces temporary `sound` and `vibration` strings, then
  expires.
- A wet dock zone strengthens damp wood smell and produces a slick texture
  signal on contact.
- Fire nearby produces heat and danger, but no taste unless contact/eating logic
  explicitly asks for it.
- Existing `entities` and `spatial_context` JSON remain unchanged.

Suggested debug checks:

- Enable `SnapshotManager.logPayload`.
- Stand near a `FeelingEmitter` and verify `feelings` appears in the JSON.
- Rotate the cat away from a smell source and verify smell still appears.
- Move outside an aspect radius and verify it disappears.
- Trigger `EmitTrigger("kicked")` from a context menu or relay and verify the
  event expires after its duration.

## Rollout Order

1. Add model types and `FeelingEmitter`.
2. Add `CreatureBlackboard.feelingEvents`.
3. Add `CreaturePerception.ScanFeelings()`.
4. Add `FeelingsData` to `SnapshotPayload`.
5. Add and register `FeelingsChannel`.
6. Add simple collision/contact relays.
7. Author a few emitters in the main URP scene: fish, rope, water/harbor zone,
   wet dock, and fire/lantern.
8. Verify snapshot JSON in Play Mode.
9. Add presets only after the first authored examples feel right.

## Non-Goals For V1

- No full item state machine.
- No realistic fluid, smell diffusion, or acoustic simulation.
- No backend prompt rewrite required in Unity; Unity only sends the new
  `feelings` payload.
- No replacement of `SmartObject`, `ZoneVolume`, or existing `entities`.
- No requirement that every scene object has a `FeelingEmitter`.
