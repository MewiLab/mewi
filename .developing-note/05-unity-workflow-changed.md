now
```
stateDiagram-v2
    [*] --> Idle
    Idle --> DirectiveQueued: AgentMessageDispatcher enqueues MindDirective
    DirectiveQueued --> ResolveTarget: CreatureIntentWorker drains queue
    ResolveTarget --> BuildSequence: target found
    ResolveTarget --> Abort: unknown target

    BuildSequence --> ProviderSequence: target has InteractionProvider
    BuildSequence --> FallbackSequence: no provider
    ProviderSequence --> ExecuteMicroAction
    FallbackSequence --> ExecuteMicroAction

    ExecuteMicroAction --> WaitMotor: enqueue next IntentMessage
    WaitMotor --> ExecuteMicroAction: motor completed and sequence has more
    WaitMotor --> Complete: motor completed and sequence empty
    WaitMotor --> Abort: motor failed or rejected

    Complete --> Idle: clear active directive
    Abort --> Idle: clear active directive and report failure
```

before:

```flowchart TD
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