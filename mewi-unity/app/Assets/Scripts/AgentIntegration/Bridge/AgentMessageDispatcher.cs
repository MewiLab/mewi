using UnityEngine;

/// <summary>
/// Thin per-cat delivery step for backend directives. Transport stays in
/// AgentNetworkHub, websocket message parsing stays in AgentWebSocketDispatcher,
/// and this component writes only this cat's CreatureBlackboard.
/// </summary>
[DisallowMultipleComponent]
public sealed class AgentMessageDispatcher : MonoBehaviour
{
    [SerializeField] AgentNetworkHub _hub;
    [SerializeField] CreatureBlackboard  _board;

    [Header("Debug")]
    [SerializeField] bool logDispatch;

    public void Init(CreatureBlackboard board)
    {
        _board = board;
        if (_hub == null) _hub = AgentNetworkHub.Resolve();
        _hub?.RegisterCreature(_board != null ? _board.CreatureId : "");
    }

    void Awake()
    {
        if (_hub == null) _hub = AgentNetworkHub.Resolve();
        if (_board == null) _board = GetComponent<CreatureBlackboard>();
    }

    void Update()
    {
        DispatchPending();
    }

    void DispatchPending()
    {
        if (_hub == null) _hub = AgentNetworkHub.Resolve();
        if (_hub == null || _board == null)
            return;

        if (_hub.TryConsumeDirective(_board.CreatureId, out CreatureBlackboard.MindDirective directive))
        {
            _board.EnqueueMindDirective(directive);
            if (logDispatch)
            {
                string target = string.IsNullOrEmpty(directive.FocusTarget) ? "" : $"->{directive.FocusTarget}";
                string mood = string.IsNullOrEmpty(directive.Mood) ? "" : $" mood={directive.Mood}";
                Debug.Log($"[AgentMessageDispatcher] directive creature={_board.CreatureId} {directive.Intent}{target}{mood}");
            }
        }
    }
}
