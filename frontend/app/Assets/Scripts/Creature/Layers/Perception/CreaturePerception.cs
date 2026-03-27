using UnityEngine;

/// <summary>
/// Sense layer — runs every frame, writes perception data to the blackboard.
/// All other layers read from the blackboard, never do their own raycasts.
///
/// For MVP: simple distance + angle checks. No raycasts yet.
/// Upgrade path: add OverlapSphere, line-of-sight raycasts, sound propagation.
/// </summary>
public class CreaturePerception : MonoBehaviour
{
    CreatureBlackboard _board;
    CreatureConfig     _config;
    Transform          _self;

    // cache for player tracking
    Vector3 _prevPlayerPos;
    float   _playerSpeedEstimate;

    public void Init(CreatureBlackboard board, CreatureConfig config)
    {
        _board  = board;
        _config = config;
        _self   = transform;
    }

    public void Tick()
    {
        ScanForPlayers();
    }

    void ScanForPlayers()
    {
        // MVP: find closest GameObject tagged "Player"
        // Upgrade: use OverlapSphere + layer mask for efficiency
        GameObject playerObj = GameObject.FindGameObjectWithTag("Player");
        if (playerObj == null)
        {
            _board.closestPlayer     = null;
            _board.closestPlayerDist = Mathf.Infinity;
            _board.playerInSight     = false;
            return;
        }

        Transform playerT = playerObj.transform;
        Vector3 toPlayer   = playerT.position - _self.position;
        float dist         = toPlayer.magnitude;

        _board.closestPlayer     = playerT;
        _board.closestPlayerDist = dist;

        // Sight check: within range and field of view
        bool inRange = dist <= _config.sightRange;
        bool inFOV   = Vector3.Angle(_self.forward, toPlayer.normalized) 
                        <= _config.fieldOfViewDeg * 0.5f;
        _board.playerInSight = inRange && inFOV;

        // Estimate player approach speed
        if (_prevPlayerPos != Vector3.zero)
        {
            float prevDist = (_prevPlayerPos - _self.position).magnitude;
            float closing  = (prevDist - dist) / Time.deltaTime; // positive = getting closer
            _playerSpeedEstimate = Mathf.Lerp(_playerSpeedEstimate, closing, 0.3f);
        }
        _prevPlayerPos = playerT.position;

        _board.playerApproachingFast = _playerSpeedEstimate > _config.fastApproachSpeed;

        // Emit sensory events for this frame
        if (inRange)
        {
            _board.sensorEvents.Add(SensoryEvent.Create(
                SensoryEvent.SenseType.PlayerNearby,
                playerT.position,
                1f - (dist / _config.sightRange), // closer = higher intensity
                playerT
            ));
        }

        if (_board.playerApproachingFast && dist < _config.personalSpaceRadius * 3f)
        {
            _board.sensorEvents.Add(SensoryEvent.Create(
                SensoryEvent.SenseType.PlayerApproachFast,
                playerT.position,
                Mathf.Clamp01(_playerSpeedEstimate / 6f),
                playerT
            ));
        }
    }

    /// <summary>
    /// Call from external systems (e.g., a sound emitter) to inject a heard event.
    /// </summary>
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
