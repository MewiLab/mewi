# Cat Motor FSM

This documents the current one-cat behavior FSM in `ActionFSM/CatBehaviorFSM.cs`
and how it is driven through the Motor stack.

## Runtime Flow

```mermaid
flowchart TD
    Backend[FastAPI / LLM tick reply] --> Bridge[AgentNetworkManager]
    Bridge -->|plan_steps legacy path| PeriodicMind[PeriodicMind]
    Bridge -->|intent + future weights directive path| Blackboard[CreatureBlackboard]

    PeriodicMind -->|useDirectiveFSM on StartThinking| DirectiveMode[Blackboard.DirectiveModeEnabled]
    PeriodicMind -->|heartbeat| Flush[CreatureWorker.FlushReport]
    Flush --> ReportQueue[Blackboard completed plan reports]
    ReportQueue --> PeriodicMind
    PeriodicMind -->|snapshot + last report| Backend

    DirectiveMode --> Worker[CreatureWorker.Tick]
    Worker -->|mind queue empty| ServiceDirective[CreatureWorker.ServiceDirective]
    ServiceDirective -->|TryNextAction board| FSM[CatBehaviorFSM]
    FSM -->|IntentMessage micro action| Queue[Blackboard.EnqueueMindMicroAction]
    Queue --> Worker

    Worker -->|TryBuildCommand| Command[MotorCommand]
    Command --> Adapter[MalbersAnimalAdapter.Apply]
    Adapter --> Body[Malbers / NavMesh / animation]
    Body --> Worker
    Worker -->|RecordStep| Flush
```

## Weighted State Pick

Each call to `CatBehaviorFSM.TryNextAction` does one fresh decision:

1. Read `CreatureBlackboard.MindWeights`, or `defaultWeights` if no LLM weights exist.
2. Read live needs from mood, health, and perception.
3. Score every behavior node.
4. Add `stateInertia` to the current node.
5. Apply small random noise.
6. Weighted-pick one state.
7. Reset `_phase` only if the selected state changed.
8. Emit one low-level `IntentMessage`.

```mermaid
flowchart LR
    Weights[MindWeights or defaultWeights] --> Score[Score behavior nodes]
    Mood[Mood: fear curiosity social trust energy] --> Score
    Health[Health: fullness] --> Score
    Perception[playerInSight closestPlayer] --> Score
    Focus[MindFocusTarget] --> ActionOnly[Action selection only]

    Score --> Inertia[Add stateInertia to current state]
    Inertia --> Noise[Apply randomDecisionNoise]
    Noise --> Pick[Weighted random pick]
    Pick --> Same{Same state?}
    Same -->|yes| KeepPhase[Keep phase]
    Same -->|no| ResetPhase[Set currentState and phase = 0]
    KeepPhase --> Action[ActionFor state, phase]
    ResetPhase --> Action
    ActionOnly --> Action
    Action --> Micro[One IntentMessage]
```

## State Utility Formula

```mermaid
flowchart TD
    Idle["Idle score = w.idle * 0.15"]
    Safety["Safety score = w.safety * max(0, fear * 2)"]
    SeekFood["SeekFood score = w.seekFood * max(0, 1 - fullness)"]
    Rest["Rest score = w.rest * max(0, 1 - energy)"]
    Socialize["Socialize score = w.socialize * playerSeen ? max(0, social + trust * 0.5) : 0"]
    Investigate["Investigate score = w.investigate * max(0, curiosity * playerFactor)"]
    Explore["Explore score = w.explore * max(0, curiosity * (1 - fear * 0.7))"]
    Groom["Groom score = w.groom * max(0, energy * (1 - fear))"]

    Idle --> Pick[Weighted pick]
    Safety --> Pick
    SeekFood --> Pick
    Rest --> Pick
    Socialize --> Pick
    Investigate --> Pick
    Explore --> Pick
    Groom --> Pick
```

`playerFactor` is `1.2` when the player is visible and `0.65` otherwise.

## State To Action Phases

The FSM does not build a long plan. It emits one action per worker opportunity.
If the same state wins again, `_phase` advances. If another state wins, `_phase`
resets to `0`.

```mermaid
stateDiagram-v2
    [*] --> PickWeightedState

    PickWeightedState --> Idle
    PickWeightedState --> Explore
    PickWeightedState --> Investigate
    PickWeightedState --> SeekFood
    PickWeightedState --> Socialize
    PickWeightedState --> Rest
    PickWeightedState --> Safety
    PickWeightedState --> Groom

    Idle --> PickWeightedState: phase 0 idle\nphase 1+ look_around or smell
    Explore --> PickWeightedState: phase 0 wander\nphase 1 smell\nphase 2+ wander or look_around
    Investigate --> PickWeightedState: phase 0 go_to focus / investigate / look_around\nphase 1 smell\nphase 2+ look_at focus / look_around
    SeekFood --> PickWeightedState: with focus: go_to, eat, smell\nno focus: smell, wander alternating
    Socialize --> PickWeightedState: phase 0 go_to focus / investigate / look_around\nphase 1 vocalize\nphase 2+ sit
    Rest --> PickWeightedState: phase 0 sleep / lie / sit by energy\nphase 1+ groom or idle
    Safety --> PickWeightedState: phase 0 flee if threat exists\nelse alert / look_around alternating
    Groom --> PickWeightedState: phase 0 sit\nphase 1+ groom
```

## Action Mapping

```mermaid
flowchart TD
    FSM[CatBehaviorFSM ActionFor] --> Intent[IntentMessage]
    Intent --> Worker[CreatureWorker.TryBuildCommand]

    Worker --> Idle[MotorCommand.Idle]
    Worker --> Stop[MotorCommand.Stop]
    Worker --> Wander[MotorCommand.Wander]
    Worker --> Flee[MotorCommand.Flee]
    Worker --> GoTo[MotorCommand.GoTo]
    Worker --> Follow[MotorCommand.Follow]
    Worker --> Face[MotorCommand.FaceTarget]
    Worker --> Action[MotorCommand.Action]
    Worker --> Climb[MotorCommand.Climb]
    Worker --> Death[MotorCommand.Death]

    Idle --> Adapter[MalbersAnimalAdapter]
    Stop --> Adapter
    Wander --> Adapter
    Flee --> Adapter
    GoTo --> Adapter
    Follow --> Adapter
    Face --> Adapter
    Action --> Adapter
    Climb --> Adapter
    Death --> Adapter
```

Current FSM-emitted intent names:

- `idle`
- `wander`
- `smell`
- `look_around`
- `go_to`
- `investigate`
- `look_at`
- `eat`
- `vocalize`
- `sit`
- `sleep`
- `lie`
- `groom`
- `flee`
- `alert`

## Notes For Iteration

- The LLM should primarily edit `CatBehaviorWeights` and optional
  `MindFocusTarget`.
- The FSM owns moment-to-moment action choice.
- `CreatureWorker` remains the only translator from intent strings to
  `MotorCommand`.
- `MalbersAnimalAdapter` remains the only body executor.
- In directive mode, reports are not flushed whenever the queue empties; they
  are flushed by `PeriodicMind` heartbeat through `CreatureWorker.FlushReport`.
