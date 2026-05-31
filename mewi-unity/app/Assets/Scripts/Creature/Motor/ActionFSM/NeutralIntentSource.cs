using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

/// <summary>
/// Produces small local intents while the LLM request is in flight.
/// It does not execute anything; CreatureWorker remains the only body executor.
/// </summary>
[DisallowMultipleComponent]
public sealed class NeutralIntentSource : MonoBehaviour
{
    enum NeutralActionNode
    {
        LocalWalk,
        Smell,
        Sit,
        Lie,
        Vocalize,
        Idle,
    }

    [Serializable]
    sealed class NeutralEpisode
    {
        public string id = "sniff_shift";
        [Min(0f)] public float weight = 1f;
        public NeutralActionNode[] nodes = { NeutralActionNode.Smell };
    }

    [Header("Activation")]
    [SerializeField] bool enableNeutralOutput = true;
    [SerializeField] bool allowWhenNoRequestInFlight;
    [SerializeField, Range(0f, 1f)] float outputChance = 0.8f;
    [SerializeField, Min(0f)] float cooldownSeconds = 1.25f;
    [SerializeField] Vector2 cooldownJitterSeconds = new Vector2(0.25f, 1.25f);
    [SerializeField, Range(0f, 1f)] float maxFear = 0.65f;

    [Header("Local Movement")]
    [SerializeField, Min(0f)] float localWalkMinRadius = 0.45f;
    [SerializeField, Min(0.1f)] float localWalkMaxRadius = 1.4f;
    [SerializeField, Min(0.1f)] float navMeshSampleRadius = 1.25f;
    [SerializeField, Min(1)] int destinationSampleAttempts = 10;
    [SerializeField] bool requireSamePlace = true;
    [SerializeField] bool fallbackToNonMovingAction = true;
    [SerializeField, Min(0)] int maxConsecutiveLocalWalkEpisodes = 1;
    [SerializeField, Range(0f, 1f)] float repeatedLocalWalkWeightScale;
    [SerializeField, Min(0f)] float postLocalWalkCooldownMultiplier = 1.5f;

    [Header("Episodes")]
    [SerializeField] List<NeutralEpisode> episodes = new List<NeutralEpisode>
    {
        new NeutralEpisode
        {
            id = "sniff_pause",
            weight = 35f,
            nodes = new[] { NeutralActionNode.Smell },
        },
        new NeutralEpisode
        {
            id = "small_walk",
            weight = 12f,
            nodes = new[] { NeutralActionNode.LocalWalk, NeutralActionNode.Smell },
        },
        new NeutralEpisode
        {
            id = "sit_pause",
            weight = 20f,
            nodes = new[] { NeutralActionNode.Sit, NeutralActionNode.Smell },
        },
        new NeutralEpisode
        {
            id = "rest_shift",
            weight = 10f,
            nodes = new[] { NeutralActionNode.Lie },
        },
        new NeutralEpisode
        {
            id = "soft_call",
            weight = 10f,
            nodes = new[] { NeutralActionNode.Vocalize },
        },
    };

    [Header("Debug")]
    [SerializeField] bool logNeutralOutput;

    readonly List<IntentMessage> _scratchIntents = new List<IntentMessage>(4);
    NavMeshPath _path;

    float _nextAllowedAt;
    int _sequence;
    int _consecutiveLocalWalkEpisodes;

    public bool TryOutputToQueue(
        CreatureBlackboard board,
        CreatureWorker worker,
        AgentNetworkManager bridge)
    {
        if (!CanOutputNeutral(board, worker, bridge))
            return false;

        if (UnityEngine.Random.value > outputChance)
        {
            ScheduleCooldown(0.5f);
            return false;
        }

        if (!TryChooseEpisode(out NeutralEpisode episode))
        {
            ScheduleCooldown(0.5f);
            return false;
        }

        if (!TryBuildIntentMessages(board, worker, episode, _scratchIntents))
        {
            ScheduleCooldown(0.5f);
            return false;
        }

        if (!board.TryEnqueueNeutralPlan(_scratchIntents))
            return false;

        if (logNeutralOutput)
            Debug.Log($"[NeutralIntentSource] queued {episode.id}: {Describe(_scratchIntents)}");

        bool queuedLocalWalk = ContainsIntent(_scratchIntents, "go_to");
        RecordQueuedNeutralPlan(queuedLocalWalk);
        ScheduleCooldown(queuedLocalWalk ? cooldownSeconds * postLocalWalkCooldownMultiplier : cooldownSeconds);
        return true;
    }

    bool CanOutputNeutral(CreatureBlackboard board, CreatureWorker worker, AgentNetworkManager bridge)
    {
        if (!enableNeutralOutput) return false;
        if (board == null || worker == null) return false;
        if (Time.time < _nextAllowedAt) return false;
        if (worker.IsBusy) return false;
        if (board.HasMindPlan) return false;
        if (board.mood != null && board.mood.fear > maxFear) return false;

        bool requestInFlight = bridge != null && bridge.RequestInFlight;
        if (!requestInFlight && !allowWhenNoRequestInFlight)
            return false;

        return true;
    }

    bool TryChooseEpisode(out NeutralEpisode episode)
    {
        episode = null;
        if (episodes == null || episodes.Count == 0)
            return false;

        float totalWeight = 0f;
        for (int i = 0; i < episodes.Count; i++)
        {
            NeutralEpisode candidate = episodes[i];
            if (candidate == null || candidate.nodes == null || candidate.nodes.Length == 0)
                continue;
            totalWeight += EffectiveEpisodeWeight(candidate);
        }

        if (totalWeight <= 0f)
            return false;

        float pick = UnityEngine.Random.value * totalWeight;
        for (int i = 0; i < episodes.Count; i++)
        {
            NeutralEpisode candidate = episodes[i];
            if (candidate == null || candidate.nodes == null || candidate.nodes.Length == 0)
                continue;

            pick -= EffectiveEpisodeWeight(candidate);
            if (pick > 0f)
                continue;

            episode = candidate;
            return true;
        }

        return false;
    }

    float EffectiveEpisodeWeight(NeutralEpisode episode)
    {
        if (episode == null)
            return 0f;

        float weight = Mathf.Max(0f, episode.weight);
        if (!ContainsNode(episode, NeutralActionNode.LocalWalk))
            return weight;

        if (_consecutiveLocalWalkEpisodes >= maxConsecutiveLocalWalkEpisodes)
            weight *= repeatedLocalWalkWeightScale;

        return weight;
    }

    bool TryBuildIntentMessages(
        CreatureBlackboard board,
        CreatureWorker worker,
        NeutralEpisode episode,
        List<IntentMessage> output)
    {
        output.Clear();
        if (episode == null || episode.nodes == null)
            return false;

        for (int i = 0; i < episode.nodes.Length; i++)
        {
            NeutralActionNode node = episode.nodes[i];
            if (!TryMapNodeToCreatureIntent(node, out string intentName))
                continue;

            Vector3 directionHint = Vector3.zero;
            if (intentName == "go_to")
            {
                if (!TrySampleSamePlaceDestination(board, worker, out directionHint))
                    continue;
            }

            output.Add(IntentMessage.Create(
                intentName,
                LayerSource.Neutral,
                -1f,
                directionHint,
                BuildCommandId(episode.id, i),
                "",
                ""));
        }

        if (output.Count > 0)
            return true;

        if (!fallbackToNonMovingAction)
            return false;

        output.Add(IntentMessage.Create(
            "idle",
            LayerSource.Neutral,
            -1f,
            Vector3.zero,
            BuildCommandId(episode.id, 0),
            "",
            ""));
        return true;
    }

    static bool TryMapNodeToCreatureIntent(NeutralActionNode node, out string creatureIntent)
    {
        switch (node)
        {
            case NeutralActionNode.LocalWalk:
                creatureIntent = "go_to";
                return true;
            case NeutralActionNode.Smell:
                creatureIntent = "smell";
                return true;
            case NeutralActionNode.Sit:
                creatureIntent = "sit";
                return true;
            case NeutralActionNode.Lie:
                creatureIntent = "lie";
                return true;
            case NeutralActionNode.Vocalize:
                creatureIntent = "vocalize";
                return true;
            case NeutralActionNode.Idle:
                creatureIntent = "idle";
                return true;
            default:
                creatureIntent = "";
                return false;
        }
    }

    void RecordQueuedNeutralPlan(bool queuedLocalWalk)
    {
        if (queuedLocalWalk)
        {
            _consecutiveLocalWalkEpisodes++;
            return;
        }

        _consecutiveLocalWalkEpisodes = 0;
    }

    static bool ContainsNode(NeutralEpisode episode, NeutralActionNode node)
    {
        if (episode == null || episode.nodes == null)
            return false;

        for (int i = 0; i < episode.nodes.Length; i++)
        {
            if (episode.nodes[i] == node)
                return true;
        }

        return false;
    }

    static bool ContainsIntent(List<IntentMessage> intents, string intentName)
    {
        if (intents == null || string.IsNullOrWhiteSpace(intentName))
            return false;

        for (int i = 0; i < intents.Count; i++)
        {
            if (string.Equals(intents[i].Intent, intentName, StringComparison.OrdinalIgnoreCase))
                return true;
        }

        return false;
    }

    // only forward <= 180
    bool TrySampleSamePlaceDestination(
        CreatureBlackboard board,
        CreatureWorker worker,
        out Vector3 destination)
    {
        destination = Vector3.zero;

        Transform originTransform = worker != null ? worker.transform : transform;
        Vector3 origin = originTransform != null ? originTransform.position : transform.position;
        // Get the forward direction of the cat to ensure it walks somewhat forward
        Vector3 forward = originTransform != null ? originTransform.forward : transform.forward;

        bool hasLeashBounds = TryGetCurrentPlaceBounds(board, out Bounds leashBounds);
        float minRadius = Mathf.Max(0f, Mathf.Min(localWalkMinRadius, localWalkMaxRadius));
        float maxRadius = Mathf.Max(minRadius, localWalkMaxRadius);
        float minRadiusSqr = minRadius * minRadius;

        for (int attempt = 0; attempt < destinationSampleAttempts; attempt++)
        {
            // Pick a random angle between -75 and +75 degrees (a cone in front of the cat)
            float randomAngle = UnityEngine.Random.Range(-75f, 75f);
            Quaternion rotation = Quaternion.Euler(0, randomAngle, 0);
            Vector3 randomDir = rotation * forward;
            
            // Pick a random distance
            float distance = UnityEngine.Random.Range(minRadius, maxRadius);
            
            // Calculate the candidate point
            Vector3 candidate = origin + (randomDir * distance);

            if (!NavMesh.SamplePosition(candidate, out NavMeshHit hit, navMeshSampleRadius, NavMesh.AllAreas))
                continue;

            Vector3 toDestination = hit.position - origin;
            toDestination.y = 0f;
            if (toDestination.sqrMagnitude < minRadiusSqr)
                continue;

            if (requireSamePlace && hasLeashBounds && !ContainsXZ(leashBounds, hit.position))
                continue;

            if (!HasCompleteNavMeshPath(origin, hit.position))
                continue;

            destination = hit.position;
            return true;
        }

        return false;
    }

    // bool TrySampleSamePlaceDestination(
    //     CreatureBlackboard board,
    //     CreatureWorker worker,
    //     out Vector3 destination)
    // {
    //     destination = Vector3.zero;

    //     Transform originTransform = worker != null ? worker.transform : transform;
    //     Vector3 origin = originTransform != null ? originTransform.position : transform.position;
        
    //     bool hasLeashBounds = TryGetCurrentPlaceBounds(board, out Bounds leashBounds);
    //     float minRadius = Mathf.Max(0f, Mathf.Min(localWalkMinRadius, localWalkMaxRadius));
    //     float maxRadius = Mathf.Max(minRadius, localWalkMaxRadius);
    //     float minRadiusSqr = minRadius * minRadius;

    //     for (int attempt = 0; attempt < destinationSampleAttempts; attempt++)
    //     {
    //         Vector2 offset2 = UnityEngine.Random.insideUnitCircle;
    //         if (offset2.sqrMagnitude <= 0.0001f)
    //             offset2 = Vector2.right;

    //         offset2.Normalize();
    //         offset2 *= UnityEngine.Random.Range(minRadius, maxRadius);

    //         Vector3 candidate = origin + new Vector3(offset2.x, 0f, offset2.y);
    //         if (!NavMesh.SamplePosition(candidate, out NavMeshHit hit, navMeshSampleRadius, NavMesh.AllAreas))
    //             continue;

    //         Vector3 toDestination = hit.position - origin;
    //         toDestination.y = 0f;
    //         if (toDestination.sqrMagnitude < minRadiusSqr)
    //             continue;

    //         if (requireSamePlace && hasLeashBounds && !ContainsXZ(leashBounds, hit.position))
    //             continue;

    //         if (!HasCompleteNavMeshPath(origin, hit.position))
    //             continue;

    //         destination = hit.position;
    //         return true;
    //     }

    //     return false;
    // }

    static bool TryGetCurrentPlaceBounds(CreatureBlackboard board, out Bounds bounds)
    {
        bounds = default;
        if (board == null || board.activeZones == null)
            return false;

        for (int i = board.activeZones.Count - 1; i >= 0; i--)
        {
            ZoneVolume zone = board.activeZones[i];
            if (zone == null)
                continue;

            if (ZoneVolumeUtility.TryGetBounds(zone, out bounds))
                return true;
        }

        return false;
    }

    bool HasCompleteNavMeshPath(Vector3 from, Vector3 to)
    {
        if (_path == null)
            _path = new NavMeshPath();

        if (!NavMesh.SamplePosition(from, out NavMeshHit start, navMeshSampleRadius, NavMesh.AllAreas))
            return false;
        if (!NavMesh.SamplePosition(to, out NavMeshHit end, navMeshSampleRadius, NavMesh.AllAreas))
            return false;

        if (!NavMesh.CalculatePath(start.position, end.position, NavMesh.AllAreas, _path))
            return false;

        return _path.status == NavMeshPathStatus.PathComplete;
    }

    static bool ContainsXZ(Bounds bounds, Vector3 position)
    {
        return position.x >= bounds.min.x &&
               position.x <= bounds.max.x &&
               position.z >= bounds.min.z &&
               position.z <= bounds.max.z;
    }

    void ScheduleCooldown(float baseSeconds)
    {
        float jitter = UnityEngine.Random.Range(
            Mathf.Min(cooldownJitterSeconds.x, cooldownJitterSeconds.y),
            Mathf.Max(cooldownJitterSeconds.x, cooldownJitterSeconds.y));
        _nextAllowedAt = Time.time + Mathf.Max(0f, baseSeconds) + Mathf.Max(0f, jitter);
    }

    string BuildCommandId(string episodeId, int stepIndex)
    {
        string safeEpisode = string.IsNullOrWhiteSpace(episodeId) ? "episode" : episodeId.Trim();
        return $"neutral:{safeEpisode}:{_sequence++:0000}:{stepIndex:00}";
    }

    static string Describe(List<IntentMessage> intents)
    {
        if (intents == null || intents.Count == 0)
            return "(none)";

        var parts = new List<string>(intents.Count);
        for (int i = 0; i < intents.Count; i++)
            parts.Add(intents[i].Intent);
        return string.Join(", ", parts);
    }
}
