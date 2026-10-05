/// </summary>
// Owns the channel registry and produces the per-tick JSON payload.
// Channels can read the blackboard but must not mutate it.
/// </summary>
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

    [Header("Exploration Candidates")]
    [Tooltip("Max zone ids sent as nearby exploration candidates.")]
    public int maxReachableZones = 12;
    [Tooltip("Only zones within this distance are considered for exploration candidates.")]
    public float reachableZoneRadius = 60f;
    [Tooltip("Prefer zones with a complete NavMesh path, but still send nearby candidates so the backend can explore and Unity can validate execution.")]
    public bool requireNavMeshPathForReachableZones = true;

    [Header("Route Safety")]
    [Tooltip("Fallback safety checks used when describing nearby routes to the LLM. If a MalbersAnimalAdapter is found, its Navigation Safety config is used instead.")]
    public NavigationSafetyConfig navigationSafety = new NavigationSafetyConfig();

    [Header("Affordance Contract")]
    [Tooltip("Max clean intent targets sent to the backend.")]
    public int maxAffordanceTargets = 16;

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
        Register(new SpatialChannel(
            maxReachableZones,
            reachableZoneRadius,
            requireNavMeshPathForReachableZones,
            navigationSafety
        ));
        Register(new FeelingsChannel(maxSmellStrings, maxSoundStrings, maxSignalStrings));
        Register(new AffordancesChannel(maxAffordanceTargets));
    }

    /// <summary>
    /// Public registration hook for adding channels
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
            commandId = _board.MicroAction.HasValue ? _board.MicroAction.Value.CommandId : "",
            time      = Time.time,
        };

        for (int i = 0; i < _channels.Count; i++)
            _channels[i].Write(payload, _board, transform);

        if (logPayload) Debug.Log($"[SnapshotManager] {JsonUtility.ToJson(payload)}");
        return payload;
    }
}
