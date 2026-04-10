using UnityEngine;

/// <summary>
/// Sense layer — writes perception data to the blackboard at a configurable tick rate.
/// All other layers read from the blackboard, never do their own physics queries.
/// </summary>
public class CreaturePerception : MonoBehaviour
{
    CreatureBlackboard _board;
    CreatureConfig     _config;
    Transform          _self;

    [Header("Tick Rate")]
    [Tooltip("Perception refreshes per second. Lower = cheaper. 0 = every frame.")]
    public float ticksPerSecond = 10f;
    float _elapsed;

    // Computed from ticksPerSecond each tick so Inspector changes take effect live.
    float TickInterval => ticksPerSecond > 0f ? 1f / ticksPerSecond : 0f;

    [Header("Nearby Scan")]
    public LayerMask nearbyLayers;         // assign Animal + Enemy + Item in Inspector
    public float     nearbyRadius = 6f;
    readonly Collider[] _nearbyBuffer = new Collider[32];

    // state for approach speed estimation
    Vector3 _prevPlayerPos;
    float   _playerSpeedEstimate;

    public void Init(CreatureBlackboard board, CreatureConfig config)
    {
        _board  = board;
        _config = config;
        _self   = transform;
    }

    // Called every frame by CreatureController — throttled internally.
    public void Tick()
    {
        _elapsed += Time.deltaTime;
        float interval = TickInterval;
        if (interval > 0f && _elapsed < interval) return;
        _elapsed = 0f;

        ScanForPlayer();
        ScanNearby();
    }

    // ── Player ────────────────────────────────────────────────────────────────

    void ScanForPlayer()
    {
        var playerObj = GameObject.FindGameObjectWithTag("Player");
        if (playerObj == null) { ClearPlayer(); return; }

        var     playerT  = playerObj.transform;
        Vector3 toPlayer = playerT.position - _self.position;
        float   dist     = toPlayer.magnitude;

        _board.closestPlayer     = playerT;
        _board.closestPlayerDist = dist;
        _board.playerInSight     = IsInSight(toPlayer, dist);

        UpdateApproachSpeed(playerT.position, dist);

        if (dist <= _config.sightRange)
            EmitPlayer(SensoryEvent.SenseType.PlayerNearby, playerT,
                       1f - dist / _config.sightRange);

        if (_board.playerApproachingFast && dist < _config.personalSpaceRadius * 3f)
            EmitPlayer(SensoryEvent.SenseType.PlayerApproachFast, playerT,
                       Mathf.Clamp01(_playerSpeedEstimate / 6f));
    }

    void ClearPlayer()
    {
        _board.closestPlayer     = null;
        _board.closestPlayerDist = Mathf.Infinity;
        _board.playerInSight     = false;
    }

    bool IsInSight(Vector3 toPlayer, float dist)
        => dist <= _config.sightRange
        && Vector3.Angle(_self.forward, toPlayer.normalized) <= _config.fieldOfViewDeg * 0.5f;

    void UpdateApproachSpeed(Vector3 playerPos, float dist)
    {
        if (_prevPlayerPos != Vector3.zero)
        {
            float prevDist = (_prevPlayerPos - _self.position).magnitude;
            float closing  = (prevDist - dist) / Time.deltaTime;
            _playerSpeedEstimate = Mathf.Lerp(_playerSpeedEstimate, closing, 0.3f);
        }
        _prevPlayerPos               = playerPos;
        _board.playerApproachingFast = _playerSpeedEstimate > _config.fastApproachSpeed;
    }

    void EmitPlayer(SensoryEvent.SenseType type, Transform src, float intensity)
        => _board.sensorEvents.Add(SensoryEvent.Create(type, src.position, intensity, src));

    // ── Nearby ────────────────────────────────────────────────────────────────

    void ScanNearby()
    {
        // One OverlapSphere covers all nearby layers (cats, items, enemies, etc.).
        // Consumers tell objects apart via SensoryEvent.label (= GameObject.name).
        // No type-switch here — renaming prefabs requires zero changes to this code.
        int n = Physics.OverlapSphereNonAlloc(_self.position, nearbyRadius, _nearbyBuffer, nearbyLayers);
        for (int i = 0; i < n; i++)
        {
            Collider col = _nearbyBuffer[i];
            if (col.transform == _self) continue;

            float dist      = Vector3.Distance(_self.position, col.transform.position);
            float intensity = 1f - Mathf.Clamp01(dist / nearbyRadius);

            _board.sensorEvents.Add(SensoryEvent.Create(
                SensoryEvent.SenseType.NearbyObject,
                col.transform.position,
                intensity,
                col.transform,
                col.gameObject.name
            ));
        }
    }

    // ── External injection ────────────────────────────────────────────────────

    /// <summary>Call from sound emitters to inject a heard event.</summary>
    public void OnSoundHeard(Vector3 soundPos, float loudness)
    {
        float dist = Vector3.Distance(_self.position, soundPos);
        if (dist > _config.hearingRange) return;

        _board.lastHeardSoundDir  = (soundPos - _self.position).normalized;
        _board.lastHeardSoundTime = Time.time;

        _board.sensorEvents.Add(SensoryEvent.Create(
            SensoryEvent.SenseType.SoundHeard,
            soundPos,
            Mathf.Clamp01(loudness * (1f - dist / _config.hearingRange))
        ));
    }
}
