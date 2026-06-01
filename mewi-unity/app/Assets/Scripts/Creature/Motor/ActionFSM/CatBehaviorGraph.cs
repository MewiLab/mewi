using System;
using System.Collections.Generic;
using UnityEngine;

public enum CatBehaviorNode
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
/// The graph weights: one tunable weight per behavior node, used to score nodes
/// when the backend has not chosen a directive yet (the bootstrap/fallback case).
/// Designer-tuned via <see cref="CreatureBlackboard.SetMindWeights"/>; the graph
/// scores each node as weight × current need and picks one.
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
/// Local cat behavior graph. The intent worker asks for one action via
/// <see cref="TryNextAction"/>; the graph maps the active directive to a
/// behavior node, then emits the next micro-action in that bounded goal.
///
/// State selection has two paths:
///   • directive  — the backend chose a high-level intent (SOCIALIZE, EXPLORE, …),
///                  stored on the blackboard. It maps straight to a node.
///   • fallback   — unknown directive: score the 8 nodes from weights × live needs.
///
/// <see cref="CreatureBlackboard.MindFocusTarget"/> aims the chosen node's
/// actions at the backend's target. A goal completes when this graph returns no
/// next action and the motor is idle.
/// </summary>
[DisallowMultipleComponent]
public sealed class CatBehaviorGraph : MonoBehaviour
{
    [Header("Scoring tuning (designer, not LLM)")]
    [SerializeField] CatBehaviorWeights defaultWeights = new CatBehaviorWeights();
    [SerializeField, Min(0f)] float stateInertia = 0.25f;
    [SerializeField, Range(0f, 1f)] float randomDecisionNoise = 0.12f;

    [Header("Debug")]
    [SerializeField] CatBehaviorNode currentNode = CatBehaviorNode.Idle;
    [SerializeField] bool logDecisions;

    readonly List<ScoredNode> _scores = new List<ScoredNode>(8);
    int _phase;
    int _commandSeq;
    string _goalKey = "";

    public CatBehaviorNode CurrentNode => currentNode;

    public void ResetGoal(CreatureBlackboard board)
    {
        currentNode = ResolveNode(board);
        _phase = 0;
        _goalKey = BuildGoalKey(board, currentNode);
    }

    /// <summary>
    /// The intent worker's single entry point. A backend directive is treated as
    /// one bounded Unity goal: node + target -> finite micro-action sequence.
    /// Output uses the vocabulary CreatureMotorWorker.TryBuildCommand handles.
    /// </summary>
    public bool TryNextAction(CreatureBlackboard board, out IntentMessage action)
    {
        CatBehaviorNode next = ResolveNode(board);
        string goalKey = BuildGoalKey(board, next);
        if (next != currentNode || !string.Equals(goalKey, _goalKey, StringComparison.Ordinal))
        {
            currentNode = next;
            _phase = 0;
            _goalKey = goalKey;
        }

        action = ActionFor(currentNode, board, _phase);
        if (string.IsNullOrWhiteSpace(action.Intent))
            return false;

        _phase++;

        if (logDecisions)
        {
            string target = string.IsNullOrWhiteSpace(action.TargetKey) ? "" : $"->{action.TargetKey}";
            Debug.Log($"[CatBehaviorGraph] {currentNode}#{_phase} -> {action.Intent}{target}");
        }
        return true;
    }

    static string BuildGoalKey(CreatureBlackboard board, CatBehaviorNode node)
    {
        string directive = board != null ? board.MindDirectiveIntent : "";
        string focus = board != null ? board.MindFocusTarget : "";
        return $"{node}|{directive}|{focus}";
    }

    // ── node selection: directive first, weighted scoring as fallback ──

    CatBehaviorNode ResolveNode(CreatureBlackboard board)
    {
        string directive = board != null ? board.MindDirectiveIntent : "";
        if (TryMapDirective(directive, out CatBehaviorNode mapped))
            return mapped;
        return Pick(board);
    }

    /// <summary>
    /// Map a backend high-level intent to a behavior node. Returns false for an
    /// empty/unknown intent so the caller falls back to weighted scoring.
    /// </summary>
    static bool TryMapDirective(string intent, out CatBehaviorNode node)
    {
        node = CatBehaviorNode.Idle;
        if (string.IsNullOrWhiteSpace(intent))
            return false;

        switch (intent.Trim().ToUpperInvariant())
        {
            case "SOCIALIZE":
            case "SEEK_PLAYER": node = CatBehaviorNode.Socialize;   return true;
            case "INVESTIGATE": node = CatBehaviorNode.Investigate; return true;
            case "EXPLORE":     node = CatBehaviorNode.Explore;     return true;
            case "SEEK_FOOD":   node = CatBehaviorNode.SeekFood;    return true;
            case "REST":        node = CatBehaviorNode.Rest;        return true;
            case "SAFETY":      node = CatBehaviorNode.Safety;      return true;
            case "IDLE":        node = CatBehaviorNode.Idle;        return true;
            default:            return false;
        }
    }

    CatBehaviorNode Pick(CreatureBlackboard board)
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
        AddScore(CatBehaviorNode.Idle,        w.idle        * 0.15f);
        AddScore(CatBehaviorNode.Safety,      w.safety      * Mathf.Max(0f, fear * 2f));
        AddScore(CatBehaviorNode.SeekFood,    w.seekFood    * Mathf.Max(0f, 1f - fullness));
        AddScore(CatBehaviorNode.Rest,        w.rest        * Mathf.Max(0f, 1f - energy));
        AddScore(CatBehaviorNode.Socialize,   w.socialize   * (sawPlayer ? Mathf.Max(0f, social + trust * 0.5f) : 0f));
        AddScore(CatBehaviorNode.Investigate, w.investigate * Mathf.Max(0f, curiosity * (sawPlayer ? 1.2f : 0.65f)));
        AddScore(CatBehaviorNode.Explore,     w.explore     * Mathf.Max(0f, curiosity * (1f - fear * 0.7f)));
        AddScore(CatBehaviorNode.Groom,       w.groom       * Mathf.Max(0f, energy * (1f - fear)));

        return PickWeighted();
    }

    void AddScore(CatBehaviorNode node, float score)
    {
        if (node == currentNode)
            score += Mathf.Max(0f, stateInertia);
        if (randomDecisionNoise > 0f)
            score *= UnityEngine.Random.Range(1f - randomDecisionNoise, 1f + randomDecisionNoise);
        if (score > 0f)
            _scores.Add(new ScoredNode { node = node, score = score });
    }

    CatBehaviorNode PickWeighted()
    {
        float total = 0f;
        for (int i = 0; i < _scores.Count; i++)
            total += _scores[i].score;
        if (total <= 0f)
            return CatBehaviorNode.Idle;

        float pick = UnityEngine.Random.value * total;
        for (int i = 0; i < _scores.Count; i++)
        {
            pick -= _scores[i].score;
            if (pick <= 0f)
                return _scores[i].node;
        }
        return _scores[_scores.Count - 1].node;
    }

    // ── node → one action for this phase ──

    IntentMessage ActionFor(CatBehaviorNode node, CreatureBlackboard board, int phase)
    {
        bool sawPlayer = board != null && board.playerInSight;
        // Optional "go here" hint the parser may buffer alongside the weights.
        string focus = board != null ? board.MindFocusTarget : "";
        bool hasFocus = !string.IsNullOrWhiteSpace(focus);

        switch (node)
        {
            case CatBehaviorNode.Explore:
                if (hasFocus)
                {
                    if (phase == 0) return Make("go_to", focus);
                    if (phase == 1) return Make("look_around");
                    if (phase == 2) return Make("smell", focus);
                    return default;
                }
                if (phase == 0) return Make("wander");
                if (phase == 1) return Make("look_around");
                return default;

            case CatBehaviorNode.Investigate:
                if (phase == 0)
                    return hasFocus ? Make("go_to", focus)
                         : sawPlayer ? Make("investigate")
                         : Make("look_around");
                if (phase == 1) return Make("smell", hasFocus ? focus : "");
                if (phase == 2) return hasFocus ? Make("look_at", focus) : Make("look_around");
                return default;

            case CatBehaviorNode.SeekFood:
                if (hasFocus)
                {
                    if (phase == 0) return Make("go_to", focus);
                    if (phase == 1) return Make("eat", focus);
                    return default;
                }
                if (phase == 0) return Make("smell");
                if (phase == 1) return Make("wander");
                return default;

            case CatBehaviorNode.Socialize:
                if (phase == 0)
                    return hasFocus ? Make("go_to", focus)
                         : sawPlayer ? Make("investigate")
                         : Make("look_around");
                if (phase == 1) return Make("vocalize", hasFocus ? focus : "");
                if (phase == 2) return Make("sit");
                return default;

            case CatBehaviorNode.Rest:
            {
                float energy = board != null && board.mood != null ? board.mood.energy : 0.6f;
                if (phase == 0)
                    return energy < 0.25f ? Make("sleep")
                         : energy < 0.5f  ? Make("lie")
                         : Make("sit");
                if (phase == 1) return Make(UnityEngine.Random.value < 0.4f ? "groom" : "idle");
                return default;
            }

            case CatBehaviorNode.Safety:
            {
                Vector3 threat = board != null && board.closestPlayer != null
                    ? board.closestPlayer.position
                    : Vector3.zero;
                if (phase == 0 && threat != Vector3.zero)
                    return Make("flee", "", threat);
                if (phase == 0) return Make("alert");
                if (phase == 1) return Make("look_around");
                return default;
            }

            case CatBehaviorNode.Groom:
                if (phase == 0) return Make("sit");
                if (phase == 1) return Make("groom");
                return default;

            default: // Idle
                if (phase == 0) return Make("idle");
                return default;
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
            $"graph:{_commandSeq++:X6}",
            "",
            targetKey ?? "");
    }

    struct ScoredNode
    {
        public CatBehaviorNode node;
        public float score;
    }
}
