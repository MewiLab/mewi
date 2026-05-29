# FeelingEmitter Sensory Design

## Purpose

The current creature snapshot gives the LLM useful visible context through
`entities` and place context through `spatial_context`, but the world still
feels thin. A cat does not understand a harbor only by listing nearby objects.
It feels fish oil, damp rope, hot metal, salt air, hollow boat creaks, soft
fabric, unsafe heat, familiar shelter, and sudden movement.

`FeelingEmitter` is the design for turning authored object and zone qualities
into compact LLM-readable sensory strings. Each meaningful object can expose
the sensory aspects it naturally has. The cat only receives aspects that are
active, detectable, and relevant from its current position.

The goal is not to simulate chemistry or acoustics. The goal is a maintainable
production layer that gives the LLM enough grounded sensory language to reason
like an embodied animal.

## Design Principles

- Objects own sensory meaning. The cat should not infer that a fish smells from
  its GameObject name every tick; the fish or its semantic proxy should carry a
  reusable sensory profile.
- Detection stays centralized. Objects expose data, while `CreaturePerception`
  performs scans and writes detected events to `CreatureBlackboard`.
- Output stays compact. The LLM receives short ranked strings, not raw physics
  state or every possible property.
- The system is aspect based. Smell and sound are first-class v1 senses, while
  texture, temperature, moisture, vibration, taste, comfort, and danger use the
  same model.
- Triggers are simple. V1 supports authored triggers and timed bursts without a
  full item state machine.
- Authoring can be partial. Important props get rich profiles; background props
  can rely on presets or have no feelings at all.

## Core Concept

A `FeelingEmitter` is a passive component attached to a prop, creature, player,
or zone. It stores a list of `FeelingAspect` entries. Each aspect describes one
detectable quality:

- `sense`: smell, sound, texture, temperature, moisture, vibration, taste,
  comfort, or danger.
- `description`: LLM-facing phrase, such as `sharp fish oil`, `warm smoke`,
  `hollow wood creak`, or `rough wet rope`.
- `radius`: how far the cat can detect distance-based aspects.
- `strength`: base intensity from 0 to 1.
- `trigger`: when this aspect is active.
- `duration`: how long event-triggered aspects remain active.

The cat perceives active aspects as `FeelingEvent`s. A snapshot channel reduces
those events into the `feelings` payload:

```json
{
  "feelings": {
    "summary": "Salt air, old fish, and damp wood make the dock feel busy and edible.",
    "smells": [
      "strong front_left near: old fish oil from FishCrate; edible and interesting",
      "faint all_around ambient: salt water and wet rope from Harbor; familiar dock air"
    ],
    "sounds": [
      "soft right near: rope creaks against the boat; something is moving gently"
    ],
    "signals": [
      "cool below contact: damp wood under paws; footing may be slippery"
    ]
  }
}
```

## Senses

### Smell

Smell ignores field of view. It should be detectable behind the cat and through
loose spatial layouts, limited mainly by radius and strength. Smell is useful
for food, creatures, player traces, water, smoke, rot, freshness, home, danger,
and comfort.

Good smell strings answer: what is it, how strong is it, where is it, and why
does it matter to the cat?

Examples:

- `strong back near: fresh fish from FishBasket; edible and urgent`
- `faint all_around ambient: salt water from Harbor; open outdoor air`
- `sharp front far: smoke from Brazier; warm but risky`

### Sound

Sound covers continuous ambience and short-lived events. It should include
direction, rough distance, source, and behavioral meaning. Sound is useful for
attention, startle, danger, social cues, movement, weather, water, and hidden
activity.

Examples:

- `sudden left near: barrel thud; object was kicked or fell`
- `soft all_around ambient: water laps under dock; calm background motion`
- `quick back far: footsteps on wood; someone is moving behind`

### Texture

Texture is usually contact-only. It tells the LLM what the cat's body is
touching: rough rope, slick dock, soft cloth, hard stone, splintery wood. This
should come from surface zones or nearby contact volumes, not distant scans.

Examples:

- `rough below contact: rope under paws; climbable but uneven`
- `slick below contact: wet wood; footing may slip`

### Temperature

Temperature can be distance-based for heat/cold sources or contact-only for
surfaces. It should support comfort and danger.

Examples:

- `warm front near: brazier heat; comfortable at edge, dangerous close`
- `cool below contact: damp stone; resting here may lower comfort`

### Moisture

Moisture captures wet air, puddles, damp wood, spray, soaked fabric, or rain.
It can modify texture and smell.

Examples:

- `damp all_around ambient: sea spray; fur may feel wet`
- `wet below contact: dock boards; wood smell is stronger`

### Vibration

Vibration is useful for impacts, heavy footsteps, moving boats, machinery, and
objects falling nearby. It can share triggers with sound.

Examples:

- `brief below near: hollow vibration through deck; something heavy shifted`

### Taste

Taste should almost always be contact-only or action-gated by licking/eating.
It should not activate just because food is nearby.

Examples:

- `salty contact: fish skin; edible`
- `bitter contact: dirty water; avoid drinking`

### Comfort And Danger

Comfort and danger are interpretive signals. They are not raw senses, but they
are useful when authored carefully. They should explain environmental meaning,
not command behavior.

Examples:

- `safe all_around ambient: covered basket nook; enclosed and soft`
- `danger front near: open flame heat; keep distance`

## Trigger Model

V1 uses simple authored triggers.

- `AlwaysOn`: active whenever the emitter exists and is within range.
- `StateBased`: active when the emitter has an authored state such as `wet`,
  `burning`, `fresh`, `rotten`, `moving`, or `broken`.
- `TimedEvent`: active for a duration after `EmitTrigger(name)`.
- `Collision`: emitted by a relay when the object receives a strong collision.
- `Kick`: emitted when the player, cat, or another object kicks or bumps it.
- `Fall`: emitted when a falling object lands.
- `EatenOrUsed`: emitted when gameplay systems consume, use, drink, scratch, or
  interact with the object.
- `EnvironmentModified`: active or boosted when zone conditions affect it, such
  as wet dock wood, hot metal near fire, or fresh fish becoming rotten later.
- `ContactOnly`: active only when the cat is touching or standing inside the
  associated contact area.

Objects should be able to call:

```csharp
feelingEmitter.EmitTrigger("kicked");
feelingEmitter.EmitTrigger("fell");
feelingEmitter.EmitTrigger("eaten");
feelingEmitter.EmitTrigger("used");
```

Optional relay components can translate Unity events into those trigger calls.

## Ranking

Each perception tick should rank events before writing the snapshot.

Use these priorities:

- Stronger intensity first.
- Short-lived event triggers before ambient background.
- Danger, food, and social cues before neutral ambience.
- Contact signals before distant signals.
- Cap repeated categories so five fish baskets do not erase fire, water, or
  footsteps.

Recommended v1 caps:

- `smells`: 4 strings.
- `sounds`: 4 strings.
- `signals`: 6 strings for texture, temperature, moisture, vibration, taste,
  comfort, and danger.
- `summary`: one sentence, generated by the channel from the top events with a
  stable template.

## Relationship To Existing Systems

- `SmartObject` remains the semantic identity of visible props and targets.
- `ZoneVolume` remains the place context system.
- `CreaturePerception` remains the only runtime scanner.
- `CreatureBlackboard` stores detected runtime events.
- `SnapshotManager` owns LLM snapshot channels.
- `entities` and `spatial_context` remain unchanged.
- `feelings` is a new channel, not a replacement for visible entities.

## Authoring Examples

### Fish Basket

- Smell, always-on: `fresh fish oil`, radius 8, strength 0.9.
- Taste, contact-only: `salty fish skin`, strength 0.8.
- Comfort, state-based `full`: `food is reachable`, strength 0.5.
- Smell, state-based `rotten`: `sour old fish`, radius 10, strength 1.0.

### Rope Coil

- Smell, always-on: `dry hemp rope`, radius 3, strength 0.25.
- Texture, contact-only: `rough rope fibers`, strength 0.7.
- Sound, trigger `kicked`: `rope scrape`, radius 6, strength 0.5, duration 2.

### Boat Hull

- Sound, always-on when `moving`: `slow hollow wood creak`, radius 10,
  strength 0.4.
- Vibration, always-on when `moving`: `gentle deck sway`, radius 5,
  strength 0.35.
- Sound, trigger `impact`: `hollow hull knock`, radius 12, strength 0.8,
  duration 3.

### Brazier Or Fire

- Temperature, always-on: `radiating heat`, radius 5, strength 0.8.
- Smell, always-on: `smoke and ash`, radius 9, strength 0.7.
- Danger, always-on: `open flame heat`, radius 3, strength 1.0.
- Texture or taste should not activate unless there is contact, and contact
  should be represented as danger/pain rather than a normal taste.

### Harbor Zone

- Smell, always-on: `salt water and damp wood`, radius from zone, strength 0.5.
- Sound, always-on: `water lapping under docks`, radius from zone, strength 0.4.
- Moisture, always-on: `humid sea air`, radius from zone, strength 0.5.
- Comfort, state-based `familiar`: `known outdoor territory`, strength 0.4.

## Success Criteria

The system is successful when the LLM can read one snapshot and understand not
only what is nearby, but what the place feels like to the cat. It should know
that fish behind the cat is interesting, fire nearby is hot and risky, wet wood
is slippery, a sudden thud came from the left, and the covered basket is a
comfortable place to hide.
