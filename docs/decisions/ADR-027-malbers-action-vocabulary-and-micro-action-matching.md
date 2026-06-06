# ADR-027: Malbers Action Vocabulary & Micro-Action String Matching

- **Status:** Proposed
- **Date:** 2026-06-03
- **Scope:** Unity body-action vocabulary in
  `mewi-unity/app/Assets/Scripts/Creature/Motor/ActionDoer/`
  (`CreatureMotorWorker`, `MalbersAnimalAdapter`, `MotorCommand`), the cat
  prefabs under `mewi-unity/app/Assets/Cats/`, and the Malbers cat animation
  assets under
  `mewi-unity/app/Assets/Malbers Animations/Animals Packs/04 Pets/Cat/`.
- **Builds on:** [ADR-005](ADR-005-movement-reliability-watchdog.md)
  (action watchdog), [ADR-022](ADR-022-dispatcher-intent-motor-workers.md)
  (micro-action worker split), [ADR-025](ADR-025-world-authored-interaction-fsm.md)
  (world-authored recipes), and
  [ADR-026](ADR-026-fishing-village-prop-catalog.md) (prop recipes).

## Context

`CreatureMotorWorker` consumes `IntentMessage.Intent` strings from
`MicroActionQueue`, translates each string into a `MotorCommand`, and hands the
body command to `MalbersAnimalAdapter`. That adapter currently exposes a small
hardcoded switch in `TryGetAbilityIndex`.

The problem is not that Malbers is short on cat behavior. The local cat package
contains many actions and variants. The problem is that only a narrow subset is
currently named, mapped, and safe for the micro-action queue.

There are three different vocabularies that must not be mixed:

1. **Micro-action strings**: stable body words such as `eat`, `smell`, `sit`,
   and `vocalize`.
2. **Malbers Action mode ability indices**: prefab-authored integers passed to
   `animal.Mode_TryActivate(ActionModeId, abilityIndex)`.
3. **Animation clip / Animator names**: asset names such as `Cat_Eat 1`,
   `Cat_Sit_Lick_Paw_L`, or `Cat_Shake_Water`.

The queue should speak stable micro-action strings. It should never depend on
raw clip names or Unity display names.

## Current Runtime Coverage

### Worker primitives, not Malbers Action mode

These strings are handled by `CreatureMotorWorker` as body primitives:

| Micro-action string | Runtime behavior | Notes |
| --- | --- | --- |
| `idle` | `MotorCommand.Idle` | Stops and returns to default stance. |
| `stop`, `stop_moving` | `MotorCommand.Stop` | Cancels navigation/action/climb/facing. |
| `wander` | Random local NavMesh movement | Uses adapter wander primitive. |
| `flee` | Run away from `DirectionHint` | Uses adapter flee primitive. |
| `die` | Death state | Requires `deathState`. |
| `go_to` | Navigate to target or `DirectionHint` | Self-confirms only on natural arrival. |
| `follow`, `investigate` | Follow a resolved target | `investigate` falls back to closest player. |
| `face`, `face_target`, `look_at` | Turn toward target | Not an animation; it rotates the body. |
| `face_sun`, `look_at_sun` | Turn toward directional light / sun target | Target key defaults to `sun`. |
| `climb`, `climb_ladder`, `use_ladder` | Activate Malbers Climb state | Uses `CatAutoClimbPoint` when present. |

### Adapter action strings today

`CreatureMotorWorker` currently recognizes these Action-mode strings and asks
`MalbersAnimalAdapter.TryGetAbilityIndex` for an ability index:

| Queue string | Adapter field | Current prefab value | Current result |
| --- | --- | ---: | --- |
| `flinch` | `startleAbilityIndex` | `1` | Works; maps to Malbers `Stun`. |
| `scratch` | `scratchAbilityIndex` | `0` | Rejected as `unmapped_action:scratch`. |
| `look_around` | `lookAroundAbilityIndex` | `0` | Rejected as `unmapped_action:look_around`. |
| `nod_head` | `nodHeadAbilityIndex` | `0` | Rejected as `unmapped_action:nod_head`. |
| `eat` | `eatAbilityIndex` | `2` | Works; requires a target and world confirmation. |
| `drink` | `drinkAbilityIndex` | `7` | Works; no world confirmation yet. |
| `sit` | `sitAbilityIndex` | `8` | Works. |
| `lie` | `lieAbilityIndex` | `11` | Works. |
| `sleep` | `sleepAbilityIndex` | `6` | Works. |
| `groom` | `groomAbilityIndex` | `0` | Rejected, although Malbers has `Groom` at index `29`. |
| `smell` | `smellAbilityIndex` | `16` | Works. |
| `alert` | `alertAbilityIndex` | `0` | Rejected, although Malbers has `Alert` at index `19`. |
| `vocalize` | `vocalizeAbilityIndex` | `20` | Works; maps to Malbers `Meow`. |

The important bug-shaped fact: the worker switch contains more words than the
prefab mapping actually supports. A string can be "recognized" by the worker and
still fail because its adapter index is `0`.

## Malbers Action Mode Inventory

On `mewi_cat.prefab`, the assigned `Action` ModeID is Malbers ID `4`
(`Common/Scriptable Assets/IDs/ModeID/Action.asset`). The Action mode contains
these prefab-authored abilities:

| Malbers ability name | Ability index | Suggested queue string | Current adapter coverage |
| --- | ---: | --- | --- |
| `Stun` | `1` | `flinch` | Covered as `flinch`. |
| `Eat` | `2` | `eat` | Covered. |
| `Sleep` | `6` | `sleep` | Covered. |
| `Drink` | `7` | `drink` | Covered. |
| `Sit` | `8` | `sit` | Covered. |
| `Crawl` | `9` | `crawl` | Missing. |
| `Dig` | `10` | `dig` | Missing. |
| `Lie` | `11` | `lie` | Covered. |
| `Push` | `13` | `push` | Missing. |
| `Smell` | `16` | `smell` | Covered. |
| `Open Chest` | `18` | `open_chest` | Missing; use only for authored props. |
| `Alert` | `19` | `alert` | Field exists but prefab value is `0`. |
| `Meow` | `20` | `vocalize` | Covered. |
| `Poop` | `24` | `poop` | Missing; ambient/self-care only. |
| `Pee` | `25` | `pee` | Missing; ambient/self-care only. |
| `Shake` | `26` | `shake_water` | Missing. |
| `Groom` | `29` | `groom` | Field exists but prefab value is `0`. |
| `Yes` | `107` | `nod_yes` | Missing. |
| `No` | `108` | `shake_no` | Missing. |

The adapter should stop growing one serialized integer per action. Replace the
hardcoded switch with a data-driven binding list:

```csharp
[Serializable]
public struct MalbersActionBinding
{
    public string canonicalIntent;
    public int abilityIndex;
    public string[] aliases;
    public string[] tags;
}
```

Existing serialized fields may stay for one migration release, but new actions
should enter through the binding list.

## Raw Cat Action Clips Present In The Package

These clips exist under the Malbers cat `Animations/Actions/` folder. They are
the full art vocabulary we can draw from, but not all are currently wired as
direct queue strings:

| Group | Clips |
| --- | --- |
| Food / drink | `Cat_Eat 1`, `Cat_Eat 2`, `Cat_Drink1`, `Cat_Drink2` |
| Smell / alert / startle | `Cat_Smell`, `Cat_Alert`, `Cat_Stun`, `Cat_ScareJump` |
| Sit / lie / sleep transitions | `Cat_Sit_From_Idle`, `Cat_Sit_to_Idle`, `Cat_Sit_to_Lie`, `Cat_Lie_to_Sit`, `Cat_Lie_to_Sleep`, `Cat_Sleep_to_Lie` |
| Sit / lie / sleep poses | `Cat_Sit_01`, `Cat_Sit_02`, `Cat_Lie_01`, `Cat_Lie_02`, `Cat_Sleep_Loop`, `Cat_Sleep_Pose2`, `Cat_Sleep_Pose3` |
| Grooming | `Cat_Sit_Lick_Paw_L`, `Cat_Sit_Lick_Paw_R`, `Cat_Sit_Lick_Chest`, `Cat_Lie_Licking` |
| Play / body motion | `Cat_Rolling`, `Cat_Wiggle`, `Cat_Shake_Water` |
| Voice / social signs | `Cat_Meow`, `Cat_Meow_Sit`, `Cat_Meow_Lie`, `Cat_Yes`, `Cat_No` |
| Object / ground interaction | `Cat_PickUp`, `Cat_Drop`, `Cat_Dig`, `Cat_Crawl` |
| Push variants | `Cat_Push_Object_L_Low`, `Cat_Push_Object_R_Low`, `Cat_Push_Object_Sit_L_Low`, `Cat_Push_Object_Sit_R_Low`, `Cat_Push_Object_L_Middle`, `Cat_Push_Object_R_Middle`, `Cat_Push_Object_L_Top`, `Cat_Push_Object_R_Top` |
| Ambient body functions | `Cat_Poop`, `Cat_Pee` |

Separate non-Action folders also contain useful clips:

| Group | Clips to consider later |
| --- | --- |
| Idle variants | `Cat_Idle_Look_Around`, `Cat_Idle Look Left`, `Cat_Idle Look Right`, `Cat_Idle_Scratch_Ear_L`, `Cat_Idle_Scratch_Ear_R`, `Cat_Idle_Yawn` |
| Attacks / toy contact | `Cat_Attack_Paw_Left`, `Cat_Attack_Paw_Right`, `Cat_Attack_Scratch`, `Cat_Attack_Bite_Left`, `Cat_Attack_Bite_Right`, `Cat_Attack_Bite_Forward` |
| Sneak stance | `Cat_Sneak_Idle`, `Cat_Sneak_Idle_Look Around`, `Cat_Sneak_Walk_Forward`, `Cat_Sneak_Trot_Forward`, sneak turns and side steps |
| Locomotion | walk, trot, canter, run, sprint, backward, turn left, turn right |
| Traversal states | jump, climb, fall, slide, ledge grab, swim, death |

These should not become one queue string per clip. The queue gets semantic
strings; the adapter or a later variant field chooses the clip.

## String Matching For `MicroActionQueue`

### Canonical matching rule

The queue should normalize incoming action text before matching:

1. Trim whitespace.
2. Lowercase invariant.
3. Replace spaces and hyphens with underscores.
4. Remove a leading `cat_` prefix when the sender accidentally uses a clip name.
5. Collapse repeated underscores.
6. Match exact canonical strings or explicit aliases only.

Do not fuzzy-match arbitrary substrings. Unknown words should still fail loudly
as `unknown_intent:<value>` or `unmapped_action:<value>`.

### Canonical action alias table

| Canonical queue string | Accepted aliases / clip-name aliases | Target required? | Backing |
| --- | --- | --- | --- |
| `flinch` | `stun`, `startle`, `scare_jump`, `scarejump`, `cat_stun`, `cat_scarejump` | No | Action index `1`; `scare_jump` clip needs future variant support. |
| `eat` | `bite`, `consume`, `cat_eat`, `cat_eat1`, `cat_eat_1`, `cat_eat2`, `cat_eat_2` | Yes | Action index `2`; world-confirmed by `EdibleObject`. |
| `sleep` | `nap`, `lie_to_sleep`, `cat_sleep_loop`, `cat_sleep_pose2`, `cat_sleep_pose3` | No | Action index `6`. |
| `drink` | `sip`, `lap_water`, `cat_drink`, `cat_drink1`, `cat_drink2` | Prefer target | Action index `7`; add water confirmation later. |
| `sit` | `sit_down`, `cat_sit`, `cat_sit_01`, `cat_sit_02`, `cat_sit_from_idle` | No | Action index `8`. |
| `crawl` | `sneak_crawl`, `cat_crawl` | No | Action index `9`; not wired today. |
| `dig` | `paw_ground`, `cat_dig` | Prefer target | Action index `10`; not wired today. |
| `lie` | `lay`, `lay_down`, `lie_down`, `cat_lie`, `cat_lie_01`, `cat_lie_02` | No | Action index `11`. |
| `push` | `nudge`, `bat`, `paw_push`, `cat_push_object_l_low`, `cat_push_object_r_low`, `cat_push_object_l_middle`, `cat_push_object_r_middle`, `cat_push_object_l_top`, `cat_push_object_r_top` | Prefer target | Action index `13`; not wired today. |
| `smell` | `sniff`, `scent`, `cat_smell` | Prefer target | Action index `16`. |
| `open_chest` | `open`, `cat_open_chest` | Yes | Action index `18`; only for authored prop recipes. |
| `alert` | `watch`, `perk_up`, `cat_alert` | No | Action index `19`; field exists but prefab is `0` today. |
| `vocalize` | `meow`, `mew`, `voice`, `vocalise`, `cat_meow`, `cat_meow_sit`, `cat_meow_lie` | Optional | Action index `20`. |
| `poop` | `cat_poop` | No | Action index `24`; ambient/self-care only. |
| `pee` | `urinate`, `cat_pee` | No | Action index `25`; ambient/self-care only. |
| `shake_water` | `shake`, `shake_off`, `cat_shake_water` | No | Action index `26`; not wired today. |
| `groom` | `lick`, `lick_paw`, `lick_chest`, `cat_sit_lick_paw_l`, `cat_sit_lick_paw_r`, `cat_sit_lick_chest`, `cat_lie_licking` | No | Action index `29`; field exists but prefab is `0` today. |
| `nod_yes` | `yes`, `nod`, `cat_yes` | No | Action index `107`; not wired today. |
| `shake_no` | `no`, `head_no`, `cat_no` | No | Action index `108`; not wired today. |

### Keep these as non-Action primitives

| Canonical queue string | Aliases | Reason |
| --- | --- | --- |
| `go_to` | `goto`, `move_to`, `walk_to`, `approach` | Navigation is owned by NavMesh/Malbers AI control, not Action mode. |
| `look_at` | `face`, `face_target`, `watch_target` | Current implementation rotates the body; no Action ability needed. |
| `look_around` | `scan`, `lookaround`, `cat_idle_look_around` | Should be an idle/variant behavior, not Action index `0`. |
| `scratch` | `scratch_ear`, `cat_idle_scratch_ear_l`, `cat_idle_scratch_ear_r`, `cat_attack_scratch` | Needs a future idle/attack binding; current Action index is `0`. |
| `climb` | `climb_ladder`, `use_ladder` | Already implemented through the Climb state. |
| `pick_up` | `pickup`, `grab`, `cat_pickup` | Malbers has a PickUp mode/clip, but the adapter does not expose it yet. |
| `drop` | `cat_drop` | Same as `pick_up`; do not route through Action mode until implemented. |

## Decision

1. The canonical micro-action vocabulary is semantic snake_case, not Malbers
   clip names.
2. The queue matcher normalizes strings and applies only explicit aliases.
3. `MalbersAnimalAdapter` should move from one serialized int per action to a
   data-driven `MalbersActionBinding` list.
4. The first binding migration should add these missing Action-mode abilities:
   `crawl`, `dig`, `push`, `alert`, `shake_water`, `groom`, `nod_yes`,
   `shake_no`, `poop`, and `pee`.
5. `scratch`, `look_around`, `pick_up`, and `drop` remain known-but-unwired
   until the adapter gains idle/attack/PickUp-mode support.
6. World recipes may use `poop`/`pee` only for ambient self-care. Backend goals
   should not request them as primary social/exploration directives.

## Consequences

**Positive**

- The backend, authored recipes, and Unity worker get one shared action spelling
  table.
- Existing queue strings keep working.
- Malbers clip churn stays inside Unity; the backend does not learn raw asset
  names.
- Missing actions are visible as map entries instead of hidden as `0` fields.

**Negative**

- Some attractive clips are still not callable until the adapter grows non-Action
  mode support.
- Adding aliases without tests can accidentally make a backend typo look valid.
  The matcher needs unit coverage for both accepted aliases and rejected unknowns.

**Follow-up implementation checklist**

1. Add `MalbersActionBinding` and normalized alias lookup to
   `MalbersAnimalAdapter`.
2. Move current working mappings into bindings:
   `flinch=1`, `eat=2`, `sleep=6`, `drink=7`, `sit=8`, `lie=11`, `smell=16`,
   `vocalize=20`.
3. Add missing Action-mode bindings:
   `crawl=9`, `dig=10`, `push=13`, `alert=19`, `shake_water=26`, `groom=29`,
   `nod_yes=107`, `shake_no=108`, `poop=24`, `pee=25`.
4. Add worker tests for alias normalization and current rejection behavior.
5. Add a later adapter path for `scratch`, `look_around`, `pick_up`, and `drop`.
