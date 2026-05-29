# Spatial Location Debug Note

## What Was Confusing

The project had two different zone systems that looked similar but wrote to
different blackboard fields.

- `SmartZoneTracker` writes flat tag names into `CreatureBlackboard.currentZones`.
- `ZoneScanner` writes real `ZoneVolume` objects into `CreatureBlackboard.activeZones`.

The active scene is using `ZoneScanner`, but `SelfChannel.location` was still
reading `currentZones`. That means the detailed `spatial_context.zones` payload
could be correct while `self.location` stayed empty.

## Current Source Of Truth

Use `ZoneScanner.activeZones` as the main spatial source of truth.

`currentZones` is now only a legacy fallback for old scenes that still use
`SmartZoneTracker`.

```mermaid
flowchart TD
    Cat[Cat / CreatureController] --> ZoneScanner[ZoneScanner]
    ZoneScanner --> TriggerScan[Zone trigger colliders]
    TriggerScan --> ZoneVolumes[ZoneVolume hierarchy]
    ZoneVolumes --> ActiveZones[CreatureBlackboard.activeZones]

    ActiveZones --> SpatialChannel[SpatialChannel]
    ActiveZones --> SelfChannel[SelfChannel]

    SpatialChannel --> SpatialPayload[spatial_context.zones]
    SelfChannel --> SelfPayload[self.location]

    SmartZoneTracker[SmartZoneTracker legacy path] -.-> CurrentZones[CreatureBlackboard.currentZones]
    CurrentZones -. fallback only .-> SelfChannel
```

## Why The Bug Happened

Before the fix:

```mermaid
flowchart LR
    ZoneScanner --> ActiveZones[activeZones]
    ActiveZones --> SpatialChannel
    SpatialChannel --> Good[spatial_context works]

    SelfChannel --> CurrentZones[currentZones]
    CurrentZones --> Empty[self.location empty]

    SmartZoneTrackerMissing[No SmartZoneTracker in scene] -. does not write .-> CurrentZones
```

So the LLM could receive:

```json
{
  "self": {
    "location": ""
  },
  "spatial_context": {
    "zones": [
      { "id": "Harbor", "type": "district" },
      { "id": "Bamboo_Boardwalk", "type": "path", "surface": "Wood" }
    ]
  }
}
```

That is inconsistent: `spatial_context` says where the cat is, but
`self.location` says nothing.

## What Changed

`SelfChannel` now reads:

1. `board.activeZones`
2. most-specific zone: `activeZones[activeZones.Count - 1]`
3. `ZoneVolume.EffectiveZoneId`
4. fallback to `board.currentZones` only if `activeZones` is empty

```mermaid
flowchart TD
    Start[SelfChannel.Write] --> HasActive{activeZones has zones?}
    HasActive -- yes --> LastZone[Take last zone]
    LastZone --> Location[location = EffectiveZoneId]
    HasActive -- no --> Legacy[currentZones fallback]
    Legacy --> Location
```

Example after the fix:

```json
{
  "self": {
    "location": "Bamboo_Boardwalk"
  },
  "spatial_context": {
    "zones": [
      { "id": "Harbor", "type": "district" },
      { "id": "Bamboo_Boardwalk", "type": "path", "surface": "Wood" }
    ]
  }
}
```

## ZoneScanner Behavior

`ZoneScanner` tracks colliders, not zones directly. This is intentional.

When the cat is inside a child zone collider, `ZoneScanner` walks up the parent
chain and collects every `ZoneVolume` it finds. That allows broad container
zones like `Harbor` to be included automatically when the cat enters a more
specific child zone.

```mermaid
flowchart BT
    Collider[Triggered collider] --> ChildZone[ZoneVolume: Bamboo_Boardwalk]
    ChildZone --> ParentZone[ZoneVolume: Harbor]
    ParentZone --> ZonesRoot[Zones root]

    Collider --> Walk[Walk parent chain]
    Walk --> ActiveList[activeZones = Harbor, Bamboo_Boardwalk]
```

The order is broadest to most-specific:

```text
activeZones[0]  = Harbor
activeZones[-1] = Bamboo_Boardwalk
```

So:

- `spatial_context.zones` sends the full hierarchy.
- `self.location` sends the most-specific current place.

## Recovery Logic

Unity trigger enter/exit can be missed when:

- the cat starts already inside a zone,
- the cat teleports,
- colliders resize,
- objects are enabled late,
- zone layers are authored inconsistently.

`ZoneScanner` now has two safety paths:

```mermaid
flowchart TD
    Tick[ZoneScanner.Tick] --> RecoverEntries[Recover missed entries]
    Tick --> RecoverExits[Recover missed exits]

    RecoverEntries --> Overlap[Overlap around cat]
    Overlap --> Filter[Keep colliders with ZoneVolume]
    Filter --> ActiveZones[Add to active collider set]

    RecoverExits --> Bounds[XZ bounds check]
    Bounds --> Remove[Remove colliders no longer containing cat]
```

The broad fallback scan filters by `ZoneVolume`, so it can still detect zone
colliders even if some are on `Default` or `SemanticProp` instead of
`SemanticZone`.

## Practical Rule

For new spatial work:

- Use `ZoneVolume` for authored places.
- Use `ZoneScanner` on the cat.
- Read `CreatureBlackboard.activeZones`.
- Treat `CreatureBlackboard.currentZones` as old compatibility data.

For LLM snapshots:

- `self.location` = the most-specific active zone.
- `spatial_context.zones` = full broad-to-specific zone hierarchy.
