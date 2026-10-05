# Current Need To Fix / Verify

This file tracks the movement/action reliability issues and the current fix
status. Items marked "verify" need Unity play-mode confirmation because this
workspace cannot run the Unity editor.

## Fixed In This Pass

- Navigation progress now means "closer to the destination", not just "moved
  somewhere". File: `NavigationWatchdog.cs`.
- `go_to` target positions now prefer the perceived snapshot position and then
  `SmartObject.perceptionCenter`. Files: `CreatureBlackboard.cs`,
  `EntitiesChannel.cs`, `CreatureWorker.cs`.
- Off-NavMesh destinations no longer reject immediately; they raw-warp as the
  final reliability fallback. File: `MalbersAnimalAdapter.cs`.
- `wander`, `flee`, `follow`, and `go_to` are all covered by the recovery path.
- Action execution has its own watchdog/config files so `eat`, `sit`, `lie`,
  and `sleep` can finish naturally or be cleaned up by timeout.
- `IsBusy` now stays true during action cooldown, so `PeriodicMind` waits before
  sending the next snapshot.

## Verify In Unity

- `go_to -> SM_Fish_1, eat -> SM_Fish_1`: the cat reaches the perceived fish
  point, then the eat animation runs.
- Blocked route: logs show watchdog repath attempts, then warp, and the next
  queued action runs.
- Off-NavMesh target: command completes through raw warp instead of
  `adapter_refused`.
- `sleep`, `sit`, `lie`, and `eat`: if Malbers emits `OnModeEnd`, the animation
  finishes naturally; if it loops, timeout cleanup releases the queue.
- Queue empty while action is still active: `PeriodicMind` logs `bodyBusy=True`
  and sends no snapshot until action cooldown ends.

## Remaining Risks

- Unity Inspector defaults may need tuning per creature. Start with
  `maxActionSeconds`, `postActionCooldownSeconds`, `repathDelaySeconds`, and
  `hardTimeoutSeconds`.
- Raw warp is intentionally blunt for prototype reliability. Later, add a fade
  or short "scramble" animation if visual popping becomes distracting.
- If a target's `SmartObject.perceptionCenter` is authored far from the
  interactable surface, the cat will correctly move to that point, but the point
  itself should be adjusted in the scene.
