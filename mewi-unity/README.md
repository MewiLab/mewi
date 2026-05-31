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
separately from the live LLM `SnapshotPayload`.

For local testing, add `ReportSessionFileOutbox` beside the logger. Saved files
are organized under
`Application.persistentDataPath/mewi_report_sessions/{userId}/{pending|sent|failed}/`.
Use the `ReportSessionFileOutbox` inspector buttons in Play Mode to send the
latest pending file or all pending files manually.

Add `ReportSessionSender` and assign the same `BackendConfig` used by the LLM
bridge. Manual outbox sends call:

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
