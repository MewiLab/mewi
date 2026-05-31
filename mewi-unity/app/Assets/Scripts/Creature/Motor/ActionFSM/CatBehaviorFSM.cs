using System;
using System.Collections.Generic;
using UnityEngine;

public enum CatBehaviorState
{
    Idle,
    Explore,
    Investigate,
    SeekFood,
    Socialize,
    Rest,
    Safety,
    Groom,
}

[Serializable]
public class CatBehaviorEdgeWeights
{
    [Min(0f)] public float explore = 1.0f;
    [Min(0f)] public float investigate = 1.0f;
    [Min(0f)] public float seekFood = 1.0f;
    [Min(0f)] public float socialize = 1.0f;
    [Min(0f)] public float rest = 1.0f;
    [Min(0f)] public float safety = 1.0f;
    [Min(0f)] public float groom = 0.55f;
    [Min(0f)] public float stateInertia = 0.25f;
}

/// <summary>
/// First-pass local cat behavior layer. It translates slow, semantic mind
/// directives such as EXPLORE or REST into short executable episodes while the
/// existing CreatureWorker remains the only component that drives the body.
/// </summary>
[DisallowMultipleComponent]
public sealed class CatBehaviorFSM : MonoBehaviour
{
    [Header("Activation")]
    [SerializeField] bool enableMindIntentExpansion = true;
    [SerializeField] bool enableAutonomousOutput = true;
    [SerializeField] bool allowAutonomousWhenNoRequestInFlight;
    [SerializeField] bool logExpansions = true;

    [Header("Transition Utility")]
    [SerializeField] CatBehaviorEdgeWeights edgeWeights = new CatBehaviorEdgeWeights();
    [SerializeField, Range(0f, 1f)] float randomDecisionNoise = 0.12f;

    [Header("Autonomous Timing")]
    [SerializeField, Range(0f, 1f)] float autonomousOutputChance = 0.8f;
    [SerializeField, Min(0f)] float autonomousCooldownSeconds = 1.25f;
    [SerializeField] Vector2 autonomousCooldownJitterSeconds = new Vector2(0.25f, 1.25f);

    [Header("Episode Shape")]
    [SerializeField, Min(1)] int maxEpisodeSteps = 3;
    [SerializeField, Range(0f, 1f)] float extraIdleMotionChance = 0.45f;

    [Header("Debug")]
    [SerializeField] CatBehaviorState currentState = CatBehaviorState.Idle;
    [SerializeField] string currentDirective = "IDLE";
    [SerializeField] string lastExpansion = "";

    readonly List<ScoredState> _scores = new List<ScoredState>(8);
    readonly List<IntentMessage> _autonomousScratch = new List<IntentMessage>(4);
    float _nextAutonomousAllowedAt;
    int _autonomousSequence;

    // Worker-orchestrator path: tracks progress through the current directive so
    // TryNextAction can hand out one action at a time without pre-baking a chain.
    string _activeDirectiveKey = "";
    int _phase;

    public CatBehaviorState CurrentState => currentState;
    public string CurrentDirective => currentDirective;
    public string LastExpansion => lastExpansion;

    /// <summary>
    /// Worker-orchestrator policy. Given the currently active directive and a
    /// fresh view of the world, return the single next low-level action for the
    /// body. The worker calls this each time it goes free, so the cat re-decides
    /// on current state instead of committing to a pre-baked episode.
    ///
    /// Phase advances per call within one directive (same Intent+target+request);
    /// it resets when the directive changes. The returned action uses the same
    /// low-level vocabulary CreatureWorker.TryBuildCommand already handles.
    /// </summary>
    public bool TryNextAction(
        IntentMessage directive,
        CreatureBlackboard board,
        out IntentMessage action)
    {
        action = default;

        string key = $"{directive.RequestId}|{directive.Intent}|{directive.TargetKey}";
        if (key != _activeDirectiveKey)
        {
            _activeDirectiveKey = key;
            _phase = 0;
            currentDirective = NormalizeDirective(directive.Intent);
            currentState = IsHighLevelDirective(currentDirective)
                ? SelectState(currentDirective, board)
                : SelectUtilityState(board);
        }

        action = StepForState(currentState, directive, board, _phase);
        _phase++;

        if (string.IsNullOrWhiteSpace(action.Intent))
            return false;

        lastExpansion = $"{currentDirective}->{currentState}#{_phase}: {action.Intent}" +
            (string.IsNullOrWhiteSpace(action.TargetKey) ? "" : $"->{action.TargetKey}");
        if (logExpansions)
            Debug.Log($"[CatBehaviorFSM] next {lastExpansion}");

        return true;
    }

    /// <summary>Reset directive progress; call from the worker when a directive ends.</summary>
    public void ResetDirectiveProgress()
    {
        _activeDirectiveKey = "";
        _phase = 0;
    }

    /// <summary>
    /// One action for the given state at the given phase. Mirrors the episode
    /// vocabulary in BuildEpisode but yields a single step so the worker can
    /// re-evaluate between actions. Sequences hold on a gentle loop at the end
    /// rather than terminating, so the cat stays in motion until the directive's
    /// TTL flushes it.
    /// </summary>
    IntentMessage StepForState(
        CatBehaviorState state,
        IntentMessage source,
        CreatureBlackboard board,
        int phase)
    {
        bool hasTarget = !string.IsNullOrWhiteSpace(source.TargetKey);
        bool playerVisible = board != null && board.playerInSight;

        switch (state)
        {
            case CatBehaviorState.Explore:
                switch (phase)
                {
                    case 0:  return Make(source, "wander");
                    case 1:  return Make(source, "smell");
                    default: return Make(source, UnityEngine.Random.value < 0.5f ? "wander" : "look_around");
                }

            case CatBehaviorState.Investigate:
                if (phase == 0)
                    return hasTarget ? Make(source, "go_to", source.TargetKey)
                         : playerVisible ? Make(source, "investigate")
                         : Make(source, "look_around");
                if (phase == 1) return Make(source, "smell", source.TargetKey);
                return hasTarget ? Make(source, "look_at", source.TargetKey) : Make(source, "look_around");

            case CatBehaviorState.SeekFood:
                if (hasTarget)
                {
                    if (phase == 0) return Make(source, "go_to", source.TargetKey);
                    if (phase == 1) return Make(source, "eat", source.TargetKey);
                    return Make(source, "smell", source.TargetKey);
                }
                return Make(source, phase % 2 == 0 ? "smell" : "wander");

            case CatBehaviorState.Socialize:
                if (phase == 0)
                    return hasTarget ? Make(source, "go_to", source.TargetKey)
                         : playerVisible ? Make(source, "investigate")
                         : Make(source, "look_around");
                if (phase == 1) return Make(source, "vocalize", source.TargetKey);
                return Make(source, "sit");

            case CatBehaviorState.Rest:
            {
                float energy = board != null && board.mood != null ? board.mood.energy : 0.6f;
                if (phase == 0)
                    return energy < 0.25f ? Make(source, "sleep")
                         : energy < 0.5f  ? Make(source, "lie")
                         : Make(source, "sit");
                return Make(source, UnityEngine.Random.value < 0.4f ? "groom" : "idle");
            }

            case CatBehaviorState.Safety:
            {
                Vector3 threat = source.DirectionHint;
                if (threat == Vector3.zero && board != null && board.closestPlayer != null)
                    threat = board.closestPlayer.position;
                if (phase == 0 && threat != Vector3.zero)
                    return Make(source, "flee", "", threat);
                return Make(source, phase % 2 == 0 ? "alert" : "look_around");
            }

            case CatBehaviorState.Groom:
                return phase == 0 ? Make(source, "sit") : Make(source, "groom");

            default:
                if (phase == 0) return Make(source, "idle");
                return Make(source, UnityEngine.Random.value < extraIdleMotionChance
                    ? (UnityEngine.Random.value < 0.5f ? "look_around" : "smell")
                    : "idle");
        }
    }

    IntentMessage Make(
        IntentMessage source,
        string intent,
        string targetKey = "",
        Vector3 directionHint = default)
    {
        string commandId = string.IsNullOrWhiteSpace(source.CommandId)
            ? $"fsm:{_autonomousSequence++:0000}:{_phase:00}"
            : $"{source.CommandId}:fsm{_phase:00}";

        return IntentMessage.Create(
            intent,
            source.Source,
            source.Duration,
            directionHint == default ? source.DirectionHint : directionHint,
            commandId,
            source.RequestId,
            string.IsNullOrWhiteSpace(targetKey) ? source.TargetKey : targetKey);
    }

    public bool TryOutputToQueue(
        CreatureBlackboard board,
        CreatureWorker worker,
        AgentNetworkManager bridge)
    {
        if (!CanOutputAutonomous(board, worker, bridge))
            return false;

        if (UnityEngine.Random.value > autonomousOutputChance)
        {
            ScheduleAutonomousCooldown(0.5f);
            return false;
        }

        IntentMessage source = IntentMessage.Create(
            "IDLE",
            LayerSource.Neutral,
            -1f,
            Vector3.zero,
            $"fsm:{_autonomousSequence++:0000}",
            "",
            "");

        currentDirective = "AUTONOMOUS";
        currentState = SelectUtilityState(board);
        _autonomousScratch.Clear();
        BuildEpisode(currentState, source, board, _autonomousScratch);
        TrimEpisode(_autonomousScratch);

        if (_autonomousScratch.Count == 0)
            AddStep(_autonomousScratch, source, "idle");

        if (!board.TryEnqueueNeutralPlan(_autonomousScratch))
            return false;

        lastExpansion = $"AUTONOMOUS->{currentState}: {Describe(_autonomousScratch)}";
        if (logExpansions)
            Debug.Log($"[CatBehaviorFSM] queued {lastExpansion}");

        ScheduleAutonomousCooldown(autonomousCooldownSeconds);
        return true;
    }

    public bool TryExpandMindIntent(
        IntentMessage source,
        CreatureBlackboard board,
        CreatureWorker worker,
        List<IntentMessage> output,
        out string reason)
    {
        output?.Clear();
        reason = "";

        if (!enableMindIntentExpansion)
        {
            reason = "fsm_disabled";
            return false;
        }

        if (output == null)
        {
            reason = "missing_output_buffer";
            return false;
        }

        string directive = NormalizeDirective(source.Intent);
        if (!IsHighLevelDirective(directive))
        {
            reason = "not_high_level";
            return false;
        }

        currentDirective = directive;
        currentState = SelectState(directive, board);
        BuildEpisode(currentState, source, board, output);
        TrimEpisode(output);

        if (output.Count == 0)
            AddStep(output, source, "idle");

        lastExpansion = $"{directive}->{currentState}: {Describe(output)}";
        if (logExpansions)
            Debug.Log($"[CatBehaviorFSM] {lastExpansion}");

        return true;
    }

    bool CanOutputAutonomous(
        CreatureBlackboard board,
        CreatureWorker worker,
        AgentNetworkManager bridge)
    {
        if (!enableAutonomousOutput) return false;
        if (board == null || worker == null) return false;
        if (Time.time < _nextAutonomousAllowedAt) return false;
        if (worker.IsBusy) return false;
        if (board.HasMindPlan) return false;

        bool requestInFlight = bridge != null && bridge.RequestInFlight;
        if (!requestInFlight && !allowAutonomousWhenNoRequestInFlight)
            return false;

        return true;
    }

    static string NormalizeDirective(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "";
        return value.Trim().ToUpperInvariant().Replace("-", "_").Replace(" ", "_");
    }

    static bool IsHighLevelDirective(string directive)
    {
        switch (directive)
        {
            case "EXPLORE":
            case "SEEK_FOOD":
            case "SEEK_PLAYER":
            case "SOCIALIZE":
            case "INVESTIGATE":
            case "REST":
            case "SAFETY":
            case "IDLE":
            case "LEGACY_PLAN":
                return true;
            default:
                return false;
        }
    }

    CatBehaviorState SelectState(string directive, CreatureBlackboard board)
    {
        switch (directive)
        {
            case "EXPLORE": return CatBehaviorState.Explore;
            case "SEEK_FOOD": return CatBehaviorState.SeekFood;
            case "SEEK_PLAYER": return CatBehaviorState.Socialize;
            case "SOCIALIZE": return CatBehaviorState.Socialize;
            case "INVESTIGATE": return CatBehaviorState.Investigate;
            case "REST": return CatBehaviorState.Rest;
            case "SAFETY": return CatBehaviorState.Safety;
            case "LEGACY_PLAN": return CatBehaviorState.Idle;
            default: return SelectUtilityState(board);
        }
    }

    CatBehaviorState SelectUtilityState(CreatureBlackboard board)
    {
        MoodModel mood = board != null ? board.mood : null;
        HealthModel health = board != null ? board.health : null;

        float fear = mood != null ? mood.fear : 0.2f;
        float curiosity = mood != null ? mood.curiosity : 0.5f;
        float social = mood != null ? mood.social : 0.0f;
        float trust = mood != null ? mood.trust : 0.3f;
        float energy = mood != null ? mood.energy : 0.6f;
        float fullness = health != null ? health.fullness : 1.0f;
        bool playerVisible = board != null && board.playerInSight;

        _scores.Clear();
        AddScore(CatBehaviorState.Safety, edgeWeights.safety * Mathf.Max(0f, fear * 2.0f));
        AddScore(CatBehaviorState.SeekFood, edgeWeights.seekFood * Mathf.Max(0f, 1.0f - fullness));
        AddScore(CatBehaviorState.Rest, edgeWeights.rest * Mathf.Max(0f, 1.0f - energy));
        AddScore(CatBehaviorState.Socialize, edgeWeights.socialize * (playerVisible ? Mathf.Max(0f, social + trust * 0.5f) : 0f));
        AddScore(CatBehaviorState.Investigate, edgeWeights.investigate * Mathf.Max(0f, curiosity * (playerVisible ? 1.2f : 0.65f)));
        AddScore(CatBehaviorState.Explore, edgeWeights.explore * Mathf.Max(0f, curiosity * (1.0f - fear * 0.7f)));
        AddScore(CatBehaviorState.Groom, edgeWeights.groom * Mathf.Max(0f, energy * (1.0f - fear)));

        return PickWeightedState();
    }

    void AddScore(CatBehaviorState state, float score)
    {
        if (state == currentState)
            score += Mathf.Max(0f, edgeWeights.stateInertia);

        if (randomDecisionNoise > 0f)
            score *= UnityEngine.Random.Range(1f - randomDecisionNoise, 1f + randomDecisionNoise);

        if (score > 0f)
            _scores.Add(new ScoredState { state = state, score = score });
    }

    CatBehaviorState PickWeightedState()
    {
        float total = 0f;
        for (int i = 0; i < _scores.Count; i++)
            total += Mathf.Max(0f, _scores[i].score);

        if (total <= 0f)
            return CatBehaviorState.Idle;

        float pick = UnityEngine.Random.value * total;
        for (int i = 0; i < _scores.Count; i++)
        {
            pick -= Mathf.Max(0f, _scores[i].score);
            if (pick <= 0f)
                return _scores[i].state;
        }

        return _scores[_scores.Count - 1].state;
    }

    void BuildEpisode(
        CatBehaviorState state,
        IntentMessage source,
        CreatureBlackboard board,
        List<IntentMessage> output)
    {
        switch (state)
        {
            case CatBehaviorState.Explore:
                AddStep(output, source, "wander");
                AddStep(output, source, "smell");
                AddStep(output, source, UnityEngine.Random.value < 0.5f ? "look_around" : "idle");
                break;

            case CatBehaviorState.Investigate:
                if (!string.IsNullOrWhiteSpace(source.TargetKey))
                    AddStep(output, source, "go_to", source.TargetKey);
                else if (board != null && board.playerInSight)
                    AddStep(output, source, "investigate");
                AddStep(output, source, "smell", source.TargetKey);
                AddStep(output, source, string.IsNullOrWhiteSpace(source.TargetKey) ? "look_around" : "look_at", source.TargetKey);
                break;

            case CatBehaviorState.SeekFood:
                if (!string.IsNullOrWhiteSpace(source.TargetKey))
                {
                    AddStep(output, source, "go_to", source.TargetKey);
                    AddStep(output, source, "eat", source.TargetKey);
                }
                else
                {
                    AddStep(output, source, "smell");
                    AddStep(output, source, "wander");
                }
                break;

            case CatBehaviorState.Socialize:
                if (!string.IsNullOrWhiteSpace(source.TargetKey))
                    AddStep(output, source, "go_to", source.TargetKey);
                else if (board != null && board.playerInSight)
                    AddStep(output, source, "investigate");
                AddStep(output, source, "vocalize", source.TargetKey);
                AddStep(output, source, "sit");
                break;

            case CatBehaviorState.Rest:
                BuildRestEpisode(source, board, output);
                break;

            case CatBehaviorState.Safety:
                BuildSafetyEpisode(source, board, output);
                break;

            case CatBehaviorState.Groom:
                AddStep(output, source, "sit");
                AddStep(output, source, "groom");
                break;

            default:
                AddStep(output, source, "idle");
                if (UnityEngine.Random.value < extraIdleMotionChance)
                    AddStep(output, source, UnityEngine.Random.value < 0.5f ? "look_around" : "smell");
                break;
        }
    }

    void BuildRestEpisode(IntentMessage source, CreatureBlackboard board, List<IntentMessage> output)
    {
        float energy = board != null && board.mood != null ? board.mood.energy : 0.6f;

        if (energy < 0.25f)
            AddStep(output, source, "sleep");
        else if (energy < 0.5f)
            AddStep(output, source, "lie");
        else
            AddStep(output, source, "sit");

        if (UnityEngine.Random.value < 0.35f)
            AddStep(output, source, "groom");
    }

    void BuildSafetyEpisode(IntentMessage source, CreatureBlackboard board, List<IntentMessage> output)
    {
        Vector3 threat = source.DirectionHint;
        if (threat == Vector3.zero && board != null && board.closestPlayer != null)
            threat = board.closestPlayer.position;

        if (threat != Vector3.zero)
        {
            AddStep(output, source, "flee", "", threat);
            AddStep(output, source, "alert");
            return;
        }

        AddStep(output, source, "alert");
        AddStep(output, source, "look_around");
    }

    void AddStep(
        List<IntentMessage> output,
        IntentMessage source,
        string intent,
        string targetKey = "",
        Vector3 directionHint = default)
    {
        if (output == null || string.IsNullOrWhiteSpace(intent))
            return;

        string commandId = string.IsNullOrWhiteSpace(source.CommandId)
            ? ""
            : $"{source.CommandId}:fsm{output.Count:00}";

        output.Add(IntentMessage.Create(
            intent,
            source.Source,
            source.Duration,
            directionHint == default ? source.DirectionHint : directionHint,
            commandId,
            source.RequestId,
            string.IsNullOrWhiteSpace(targetKey) ? source.TargetKey : targetKey));
    }

    void TrimEpisode(List<IntentMessage> output)
    {
        if (output == null)
            return;

        int maxSteps = Mathf.Max(1, maxEpisodeSteps);
        if (output.Count > maxSteps)
            output.RemoveRange(maxSteps, output.Count - maxSteps);
    }

    static string Describe(List<IntentMessage> output)
    {
        if (output == null || output.Count == 0)
            return "(empty)";

        var parts = new List<string>(output.Count);
        for (int i = 0; i < output.Count; i++)
        {
            IntentMessage message = output[i];
            string target = string.IsNullOrWhiteSpace(message.TargetKey) ? "" : $"->{message.TargetKey}";
            parts.Add($"{message.Intent}{target}");
        }
        return string.Join(", ", parts);
    }

    void ScheduleAutonomousCooldown(float baseSeconds)
    {
        float jitter = UnityEngine.Random.Range(
            Mathf.Min(autonomousCooldownJitterSeconds.x, autonomousCooldownJitterSeconds.y),
            Mathf.Max(autonomousCooldownJitterSeconds.x, autonomousCooldownJitterSeconds.y));
        _nextAutonomousAllowedAt = Time.time + Mathf.Max(0f, baseSeconds) + Mathf.Max(0f, jitter);
    }

    struct ScoredState
    {
        public CatBehaviorState state;
        public float score;
    }
}
