using UnityEngine;

/// <summary>
/// Optional creature component that leaves slow-decaying scent/history traces
/// in the current most-specific ZoneVolume.
/// </summary>
[DisallowMultipleComponent]
public sealed class PresenceTraceEmitter : MonoBehaviour
{
    [SerializeField] string ownerKind = "cat";
    [SerializeField] string description = "cat scent trail";
    [SerializeField, Range(0f, 1f)] float strengthPerVisit = 0.18f;
    [SerializeField, Min(30f)] float lifetimeSeconds = 600f;
    [SerializeField, Min(0.5f)] float emitIntervalSeconds = 8f;
    [SerializeField, Min(1)] int maxTracesPerZone = 6;

    CreatureBlackboard _board;
    float _nextEmitAt;

    public void Init(CreatureBlackboard board)
    {
        _board = board;
        _nextEmitAt = Time.time + Random.Range(0f, emitIntervalSeconds);
    }

    public void Tick()
    {
        if (_board == null || Time.time < _nextEmitAt)
            return;

        _nextEmitAt = Time.time + Mathf.Max(0.5f, emitIntervalSeconds);
        ZoneVolume zone = CurrentZone();
        if (zone == null)
            return;

        PresenceTraceRegistry.Record(
            zone,
            _board.CreatureId,
            ownerKind,
            description,
            strengthPerVisit,
            lifetimeSeconds,
            maxTracesPerZone);
    }

    ZoneVolume CurrentZone()
    {
        if (_board.activeZones == null || _board.activeZones.Count == 0)
            return null;
        return _board.activeZones[_board.activeZones.Count - 1];
    }
}
