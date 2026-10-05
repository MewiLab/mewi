using UnityEngine;

/// <summary>
/// Consumes high-level intent directives and uses the cat behavior graph to
/// refill the micro-action queue that CreatureMotorWorker executes.
/// </summary>
[DisallowMultipleComponent]
public sealed class CreatureIntentWorker : MonoBehaviour
{
    [SerializeField] CatBehaviorGraph _behaviorGraph;
    [SerializeField] CreatureBlackboard _board;
    [SerializeField] CreatureMotorWorker _motorWorker;

    [Header("Debug")]
    [SerializeField] bool logIntentWorker;

    bool _running;

    public void Init(CreatureBlackboard board)
    {
        _board = board;
        ResolveGraph();
        ResolveMotorWorker();
        StartWorking();
    }

    public void StartWorking()
    {
        _running = true;
        _board?.EnableIntentWorker();
    }

    public void StopWorking()
    {
        _running = false;
    }

    public void Tick()
    {
        if (!_running || _board == null)
            return;

        ConsumeIntentQueue();

        if (_board.HasMicroActionPlan || IsMotorExecuting() || _behaviorGraph == null)
            return;

        if (!_board.HasActiveMindDirective)
            return;

        if (_board.LastMicroActionFailed)
        {
            if (logIntentWorker)
            {
                Debug.LogWarning(
                    $"[CreatureIntentWorker] abort {_board.MindDirectiveIntent}{(string.IsNullOrEmpty(_board.MindFocusTarget) ? "" : $"->{_board.MindFocusTarget}")} " +
                    $"after {_board.LastMicroActionIntent}{(string.IsNullOrEmpty(_board.LastMicroActionTarget) ? "" : $"->{_board.LastMicroActionTarget}")} " +
                    $"{_board.LastMicroActionStatus}:{_board.LastMicroActionReason}");
            }
            _board.ClearActiveMindDirective();
            return;
        }

        if (_behaviorGraph.TryNextAction(_board, out IntentMessage micro))
        {
            _board.EnqueueMicroAction(micro);
            return;
        }

        if (logIntentWorker)
            Debug.Log($"[CreatureIntentWorker] completed {_board.MindDirectiveIntent}{(string.IsNullOrEmpty(_board.MindFocusTarget) ? "" : $"->{_board.MindFocusTarget}")}");
        _board.ClearActiveMindDirective();
    }

    void ConsumeIntentQueue()
    {
        bool consumed = false;
        CreatureBlackboard.MindDirective latest = default;

        while (_board.TryPopMindDirective(out CreatureBlackboard.MindDirective directive))
        {
            latest = directive;
            consumed = true;
        }

        if (!consumed)
            return;

        _board.SetMindDirective(latest);
        _behaviorGraph?.ResetGoal(_board);
        if (logIntentWorker)
            Debug.Log($"[CreatureIntentWorker] active {latest.Intent}{(string.IsNullOrEmpty(latest.FocusTarget) ? "" : $"->{latest.FocusTarget}")}");
    }

    void ResolveGraph()
    {
        if (_behaviorGraph != null)
            return;

        _behaviorGraph = GetComponent<CatBehaviorGraph>();
        if (_behaviorGraph == null) _behaviorGraph = GetComponentInChildren<CatBehaviorGraph>();
        if (_behaviorGraph == null) _behaviorGraph = GetComponentInParent<CatBehaviorGraph>();
        if (_behaviorGraph == null) _behaviorGraph = gameObject.AddComponent<CatBehaviorGraph>();
    }

    void ResolveMotorWorker()
    {
        if (_motorWorker != null)
            return;

        _motorWorker = GetComponent<CreatureMotorWorker>();
        if (_motorWorker == null) _motorWorker = GetComponentInChildren<CreatureMotorWorker>();
        if (_motorWorker == null) _motorWorker = GetComponentInParent<CreatureMotorWorker>();
    }

    bool IsMotorExecuting()
    {
        if (_motorWorker == null)
            ResolveMotorWorker();
        return _motorWorker != null && _motorWorker.IsExecutingIntent;
    }
}
