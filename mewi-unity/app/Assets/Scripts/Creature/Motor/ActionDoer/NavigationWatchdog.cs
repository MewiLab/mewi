using UnityEngine;

/// <summary>
/// What the watchdog wants the adapter to do this tick.
/// The watchdog never touches Malbers or NavMesh; the adapter performs the action.
/// </summary>
public enum NavigationRecoveryAction
{
    Continue,
    Repath,
    Warp,
}

/// <summary>
/// Why a navigation command finished. Surfaced through the adapter so
/// <see cref="CreatureMotorWorker"/> can attach it to the plan step report.
/// </summary>
public enum NavigationCompletionReason
{
    None,
    Arrived,
    ArrivedAfterRepath,
    WarpedToNavMesh,
    WarpedRaw,
    Failed,
    Cancelled,
}

/// <summary>
/// Pure C# progress tracker for active navigation commands. The adapter calls
/// <see cref="Begin"/> when nav starts, <see cref="Tick"/> every frame, and one
/// of the Notify* methods when nav resolves. The watchdog itself contains no
/// Malbers, NavMesh, or Unity dependencies beyond <see cref="Vector3"/>.
/// </summary>
public class NavigationWatchdog
{
    NavigationRecoveryConfig _config = new NavigationRecoveryConfig();

    bool _active;
    Vector3 _destination;
    Vector3 _progressReferenceDestination;
    Vector3 _lastPosition;
    float _bestDistanceToDestination;
    float _startedAt;
    float _lastProgressAt;
    float _lastCheckAt;
    int _repathAttempts;
    NavigationCompletionReason _completionReason = NavigationCompletionReason.None;

    public bool IsActive => _active;
    public Vector3 Destination => _destination;
    public int RepathAttempts => _repathAttempts;
    public NavigationCompletionReason CompletionReason => _completionReason;

    public void Configure(NavigationRecoveryConfig config)
    {
        if (config != null) _config = config;
    }

    public void Begin(Vector3 destination, Vector3 currentPosition, float now)
    {
        _active = true;
        _destination = destination;
        _progressReferenceDestination = destination;
        _lastPosition = currentPosition;
        _bestDistanceToDestination = HorizontalDistance(currentPosition, destination);
        _startedAt = now;
        _lastProgressAt = now;
        _lastCheckAt = now;
        _repathAttempts = 0;
        _completionReason = NavigationCompletionReason.None;
    }

    public void UpdateDestination(Vector3 destination) => _destination = destination;

    public void UpdateDestination(Vector3 destination, Vector3 currentPosition, float now)
    {
        if (HorizontalDistance(destination, _progressReferenceDestination) >= _config.destinationMoveResetMeters)
        {
            _bestDistanceToDestination = HorizontalDistance(currentPosition, destination);
            _progressReferenceDestination = destination;
            _lastPosition = currentPosition;
            _lastProgressAt = now;
        }

        _destination = destination;
    }

    public NavigationRecoveryAction Tick(Vector3 currentPosition, float now)
    {
        if (!_active) return NavigationRecoveryAction.Continue;
        if (now - _lastCheckAt < _config.progressCheckInterval) return NavigationRecoveryAction.Continue;
        _lastCheckAt = now;

        float distanceToDestination = HorizontalDistance(currentPosition, _destination);
        if (_bestDistanceToDestination - distanceToDestination >= _config.minProgressMeters)
        {
            _lastProgressAt = now;
            _lastPosition = currentPosition;
            _bestDistanceToDestination = distanceToDestination;
        }

        float stuckFor = now - _lastProgressAt;
        float totalFor = now - _startedAt;

        if (totalFor >= _config.hardTimeoutSeconds)
            return NavigationRecoveryAction.Warp;

        if (stuckFor >= _config.repathDelaySeconds)
        {
            if (_repathAttempts < _config.maxRepathAttempts)
            {
                _repathAttempts++;
                _lastProgressAt = now;
                _lastPosition = currentPosition;
                return NavigationRecoveryAction.Repath;
            }
            return NavigationRecoveryAction.Warp;
        }

        return NavigationRecoveryAction.Continue;
    }

    public void NotifyArrivedNaturally()
    {
        if (!_active) return;
        _completionReason = _repathAttempts > 0
            ? NavigationCompletionReason.ArrivedAfterRepath
            : NavigationCompletionReason.Arrived;
        _active = false;
    }

    public void NotifyWarpedToNavMesh()
    {
        _completionReason = NavigationCompletionReason.WarpedToNavMesh;
        _active = false;
    }

    public void NotifyWarpedRaw()
    {
        _completionReason = NavigationCompletionReason.WarpedRaw;
        _active = false;
    }

    public void NotifyFailed()
    {
        _completionReason = NavigationCompletionReason.Failed;
        _active = false;
    }

    public void Cancel()
    {
        if (_active) _completionReason = NavigationCompletionReason.Cancelled;
        _active = false;
    }

    static float HorizontalDistance(Vector3 a, Vector3 b)
    {
        a.y = 0f;
        b.y = 0f;
        return Vector3.Distance(a, b);
    }
}
