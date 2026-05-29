# Mewi Unity

## Report Raw Data Logger

The offline behavioral report exporter lives under:

`app/Assets/Scripts/AgentIntegration/Report/`

Attach `ReportSessionLogger` to a scene object, usually the human-controlled
creature prefab or a session manager object. Assign:

- `Human Actor`: the player/human transform. This can be the same creature
  prefab type as NPC cats.
- `Human Blackboard`: optional, used only to read the current zone.
- `Report Cats`: map each report cat ID (`mewi`, `miso`, `yuzu`, `haru`) to
  that cat's `CreatureBlackboard`.

`ReportSessionLogger` writes one immutable `mewi.report.raw.v1` session JSON
separately from the live LLM `SnapshotPayload`. By default it saves local debug
files under `Application.persistentDataPath/mewi_report_sessions/{userId}/`.

For the production path, add `ReportSessionSender`, assign the same
`BackendConfig` used by the LLM bridge, and enable `Send To Backend On Session
End` on the logger. Unity then sends:

```http
POST /api/v1/report/session
```

The backend owns local file storage now and can move the same payload to S3
later without changing Unity.

### How `approach` Is Derived

Because the human actor can use the same motor intents as cats, `approach` is a
relationship event, not a unique prefab action.

The logger records human `"action": "approach"` when the human-controlled
actor's distance to a configured report cat decreases by the configured
`Approach Distance Delta Meters` while inside `Approach Max Distance Meters`.

Manual motor logging can also call:

```csharp
reportLogger.RecordHumanMotorIntent("go_to", targetCatTransform);
```

`go_to`, `move`, `follow`, and `investigate` become `approach` only when the
target transform belongs to one of the configured report cats.
