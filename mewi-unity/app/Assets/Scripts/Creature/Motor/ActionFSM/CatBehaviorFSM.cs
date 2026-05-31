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

/// <summary>
/// The graph weights: one tunable weight per behavior node. The LLM edits these
/// through <see cref="CreatureBlackboard.SetMindWeights"/> (a parser fills the
/// blackboard buffer from the websocket reply). The FSM scores each node as
/// weight × current need and picks one.
/// </summary>
[Serializable]
public class CatBehaviorWeights
{
    [Min(0f)] public float idle = 0.3f;
    [Min(0f)] public float explore = 1f;
    [Min(0f)] public float investigate = 1f;
    [Min(0f)] public float seekFood = 1f;
    [Min(0f)] public float socialize = 1f;
    [Min(0f)] public float rest = 1f;
    [Min(0f)] public float safety = 1f;
    [Min(0f)] public float groom = 0.55f;
}

/// <summary>
/// Local cat behavior policy as a weighted state graph. Two responsibilities,
/// one public method each side of the bus:
///   • the LLM edits the weights  → CreatureBlackboard.SetMindWeights (the buffer)
///   • the worker asks for action → CatBehaviorFSM.TryNextAction      (this class)
///
/// Each call: score the 8 nodes from the buffer weights × live needs, pick one,
/// and return a single low-level action. Re-decides on fresh world state every
/// time, so there is no pre-baked chain.
/// </summary>
[DisallowMultipleComponent]
public sealed class CatBehaviorFSM : MonoBehaviour
{
    [Header("Scoring tuning (designer, not LLM)")]
    [SerializeField] CatBehaviorWeights defaultWeights = new CatBehaviorWeights();
    [SerializeField, Min(0f)] float stateInertia = 0.25f;
    [SerializeField, Range(0f, 1f)] float randomDecisionNoise = 0.12f;

    [Header("Debug")]
    [SerializeField] CatBehaviorState currentState = CatBehaviorState.Idle;
    [SerializeField] bool logDecisions;

    readonly List<ScoredState> _scores = new List<ScoredState>(8);
    int _phase;
    int _commandSeq;

    public CatBehaviorState CurrentState => currentState;

    /// <summary>
    /// The worker's single entry point. Picks the state from the weighted graph
    /// and returns one body action; resets the per-state phase when the state
    /// changes. Output uses the vocabulary CreatureWorker.TryBuildCommand handles.
    /// </summary>
    public bool TryNextAction(CreatureBlackboard board, out IntentMessage action)
    {
        CatBehaviorState next = Pick(board);
        if (next != currentState)
        {
            currentState = next;
            _phase = 0;
        }

        action = ActionFor(currentState, board, _phase);
        _phase++;

        if (string.IsNullOrWhiteSpace(action.Intent))
            return false;

        if (logDecisions)
        {
            string target = string.IsNullOrWhiteSpace(action.TargetKey) ? "" : $"->{action.TargetKey}";
            Debug.Log($"[CatBehaviorFSM] {currentState}#{_phase} -> {action.Intent}{target}");
        }
        return true;
    }

    // ── state selection: weight × need, + inertia + noise, weighted pick ──

    CatBehaviorState Pick(CreatureBlackboard board)
    {
        CatBehaviorWeights w =
            board != null && board.MindWeights != null ? board.MindWeights : defaultWeights;

        MoodModel mood = board != null ? board.mood : null;
        HealthModel health = board != null ? board.health : null;
        float fear      = mood != null ? mood.fear : 0.2f;
        float curiosity = mood != null ? mood.curiosity : 0.5f;
        float social    = mood != null ? mood.social : 0f;
        float trust     = mood != null ? mood.trust : 0.3f;
        float energy    = mood != null ? mood.energy : 0.6f;
        float fullness  = health != null ? health.fullness : 1f;
        bool sawPlayer  = board != null && board.playerInSight;

        _scores.Clear();
        AddScore(CatBehaviorState.Idle,        w.idle        * 0.15f);
        AddScore(CatBehaviorState.Safety,      w.safety      * Mathf.Max(0f, fear * 2f));
        AddScore(CatBehaviorState.SeekFood,    w.seekFood    * Mathf.Max(0f, 1f - fullness));
        AddScore(CatBehaviorState.Rest,        w.rest        * Mathf.Max(0f, 1f - energy));
        AddScore(CatBehaviorState.Socialize,   w.socialize   * (sawPlayer ? Mathf.Max(0f, social + trust * 0.5f) : 0f));
        AddScore(CatBehaviorState.Investigate, w.investigate * Mathf.Max(0f, curiosity * (sawPlayer ? 1.2f : 0.65f)));
        AddScore(CatBehaviorState.Explore,     w.explore     * Mathf.Max(0f, curiosity * (1f - fear * 0.7f)));
        AddScore(CatBehaviorState.Groom,       w.groom       * Mathf.Max(0f, energy * (1f - fear)));

        return PickWeighted();
    }

    void AddScore(CatBehaviorState state, float score)
    {
        if (state == currentState)
            score += Mathf.Max(0f, stateInertia);
        if (randomDecisionNoise > 0f)
            score *= UnityEngine.Random.Range(1f - randomDecisionNoise, 1f + randomDecisionNoise);
        if (score > 0f)
            _scores.Add(new ScoredState { state = state, score = score });
    }

    CatBehaviorState PickWeighted()
    {
        float total = 0f;
        for (int i = 0; i < _scores.Count; i++)
            total += _scores[i].score;
        if (total <= 0f)
            return CatBehaviorState.Idle;

        float pick = UnityEngine.Random.value * total;
        for (int i = 0; i < _scores.Count; i++)
        {
            pick -= _scores[i].score;
            if (pick <= 0f)
                return _scores[i].state;
        }
        return _scores[_scores.Count - 1].state;
    }

    // ── state → one action for this phase ──

    IntentMessage ActionFor(CatBehaviorState state, CreatureBlackboard board, int phase)
    {
        bool sawPlayer = board != null && board.playerInSight;
        // Optional "go here" hint the parser may buffer alongside the weights.
        string focus = board != null ? board.MindFocusTarget : "";
        bool hasFocus = !string.IsNullOrWhiteSpace(focus);

        switch (state)
        {
            case CatBehaviorState.Explore:
                if (phase == 0) return Make("wander");
                if (phase == 1) return Make("smell");
                return Make(UnityEngine.Random.value < 0.5f ? "wander" : "look_around");

            case CatBehaviorState.Investigate:
                if (phase == 0)
                    return hasFocus ? Make("go_to", focus)
                         : sawPlayer ? Make("investigate")
                         : Make("look_around");
                if (phase == 1) return Make("smell", hasFocus ? focus : "");
                return hasFocus ? Make("look_at", focus) : Make("look_around");

            case CatBehaviorState.SeekFood:
                if (hasFocus)
                {
                    if (phase == 0) return Make("go_to", focus);
                    if (phase == 1) return Make("eat", focus);
                    return Make("smell", focus);
                }
                return Make(phase % 2 == 0 ? "smell" : "wander");

            case CatBehaviorState.Socialize:
                if (phase == 0)
                    return hasFocus ? Make("go_to", focus)
                         : sawPlayer ? Make("investigate")
                         : Make("look_around");
                if (phase == 1) return Make("vocalize", hasFocus ? focus : "");
                return Make("sit");

            case CatBehaviorState.Rest:
            {
                float energy = board != null && board.mood != null ? board.mood.energy : 0.6f;
                if (phase == 0)
                    return energy < 0.25f ? Make("sleep")
                         : energy < 0.5f  ? Make("lie")
                         : Make("sit");
                return Make(UnityEngine.Random.value < 0.4f ? "groom" : "idle");
            }

            case CatBehaviorState.Safety:
            {
                Vector3 threat = board != null && board.closestPlayer != null
                    ? board.closestPlayer.position
                    : Vector3.zero;
                if (phase == 0 && threat != Vector3.zero)
                    return Make("flee", "", threat);
                return Make(phase % 2 == 0 ? "alert" : "look_around");
            }

            case CatBehaviorState.Groom:
                return phase == 0 ? Make("sit") : Make("groom");

            default: // Idle
                if (phase == 0) return Make("idle");
                return Make(UnityEngine.Random.value < 0.5f ? "look_around" : "smell");
        }
    }

    IntentMessage Make(string intent, string targetKey = "", Vector3 directionHint = default)
    {
        // Indefinite duration: the worker owns a micro-action's lifecycle.
        return IntentMessage.Create(
            intent,
            LayerSource.Mind,
            -1f,
            directionHint,
            $"fsm:{_commandSeq++:X6}",
            "",
            targetKey ?? "");
    }

    struct ScoredState
    {
        public CatBehaviorState state;
        public float score;
    }
}
