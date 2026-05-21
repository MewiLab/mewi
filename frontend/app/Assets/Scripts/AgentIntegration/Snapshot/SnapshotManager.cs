// Owns the channel registry and produces the per-tick JSON payload.
//
// Responsibilities:
//   - Hold an ordered list of ISnapshotChannel implementations.
//   - On BuildJson(), iterate channels and let each populate its slot on
//     a fresh SnapshotPayload, then JsonUtility-serialise the whole thing.
//
// Adding a new perception channel = create a class implementing
// ISnapshotChannel + register it here. AgentNetworkManager does NOT change.
// PeriodicMind does NOT change.
//
// Channels can read the blackboard but must not mutate it.

using System.Collections.Generic;
using UnityEngine;

public class SnapshotManager : MonoBehaviour
{
    [Header("Entity Filter (Eye perception)")]
    [Tooltip("Max entities sent per tick. The closest N are kept.")]
    public int maxEntities = 8;
    [Tooltip("Max entities of any single category. Prevents 12 lanterns crowding out the boat.")]
    public int maxPerCategory = 2;

    [Header("Feelings Filter")]
    [Tooltip("Max smell strings sent per tick.")]
    public int maxSmellStrings = 4;
    [Tooltip("Max sound strings sent per tick.")]
    public int maxSoundStrings = 4;
    [Tooltip("Max non-smell/non-sound feeling strings sent per tick.")]
    public int maxSignalStrings = 6;

    [Header("Debug")]
    public bool logPayload = false;

    readonly List<ISnapshotChannel> _channels = new List<ISnapshotChannel>();

    // Set by CreatureController.Init.
    CreatureBlackboard _board;

    public void Init(CreatureBlackboard board)
    {
        _board = board;
        RegisterDefaultChannels();
    }

    void RegisterDefaultChannels()
    {
        _channels.Clear();
        // Order is purely for readability in serialised JSON.
        Register(new SelfChannel());
        Register(new MoodChannel());
        Register(new HealthChannel());
        Register(new EntitiesChannel(maxEntities, maxPerCategory));
        Register(new SpatialChannel());
        Register(new FeelingsChannel(maxSmellStrings, maxSoundStrings, maxSignalStrings));
    }

    /// <summary>
    /// Public registration hook so future channels (Ambient, Affordance, Social)
    /// can be added from other call sites without editing this class.
    /// </summary>
    public void Register(ISnapshotChannel channel)
    {
        if (channel == null) return;
        _channels.Add(channel);
    }

    /// <summary>
    /// Build the current blackboard state as a wire-format payload object.
    /// </summary>
    public SnapshotPayload BuildPayload(string requestId)
    {
        if (_board == null)
        {
            Debug.LogError("[SnapshotManager] Init not called — blackboard is null.");
            return new SnapshotPayload { requestId = requestId };
        }

        var payload = new SnapshotPayload
        {
            agent_id  = _board.CreatureId,
            requestId = requestId,
            commandId = _board.MindIntent.HasValue ? _board.MindIntent.Value.CommandId : "",
            time      = Time.time,
        };

        for (int i = 0; i < _channels.Count; i++)
            _channels[i].Write(payload, _board, transform);

        return payload;
    }

    /// <summary>
    /// Serialise the current blackboard state to the legacy raw snapshot JSON.
    /// </summary>
    public string BuildJson(string requestId)
    {
        SnapshotPayload payload = BuildPayload(requestId);
        string json = JsonUtility.ToJson(payload);
        if (logPayload) Debug.Log($"[SnapshotManager] {json}");
        return json;
    }
}
