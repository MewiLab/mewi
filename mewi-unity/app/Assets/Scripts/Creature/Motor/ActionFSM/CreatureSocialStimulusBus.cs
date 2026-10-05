using System;
using UnityEngine;

[DisallowMultipleComponent]
public sealed class CreatureSocialStimulusBus : MonoBehaviour
{
    public static event Action<SocialStimulus> GlobalStimulusDelivered;

    [SerializeField] bool subscribeToPlayerCatActions = true;
    [SerializeField] bool deliverCommittedPhaseOnly = true;
    [SerializeField] bool logDelivery;

    void OnEnable()
    {
        if (subscribeToPlayerCatActions)
            PlayerCatActionEmitter.GlobalActionEmitted += OnPlayerCatAction;
    }

    void OnDisable()
    {
        PlayerCatActionEmitter.GlobalActionEmitted -= OnPlayerCatAction;
    }

    public bool TryDeliver(PlayerCatActionEvent actionEvent)
    {
        if (!actionEvent.IsReactionEligible)
            return false;
        if (deliverCommittedPhaseOnly &&
            !string.Equals(actionEvent.Phase, "committed", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        SocialStimulus stimulus = new SocialStimulus(actionEvent);
        if (!stimulus.IsValid)
            return false;

        CreatureBlackboard targetBoard = FindTargetBoard(stimulus.TargetCatId);
        if (targetBoard == null)
            return false;

        Transform actorTransform = FindActorTransform(stimulus.ActorId);
        if (actorTransform == null)
        {
            if (logDelivery)
                Debug.LogWarning($"[CreatureSocialStimulusBus] cannot resolve actor target '{stimulus.ActorId}' for {stimulus.Kind}");
            return false;
        }

        RememberActorTarget(targetBoard, stimulus, actorTransform);
        targetBoard.EnqueueSocialStimulus(stimulus);
        GlobalStimulusDelivered?.Invoke(stimulus);

        if (logDelivery)
            Debug.Log($"[CreatureSocialStimulusBus] delivered {stimulus.Kind} {stimulus.ActorId}->{stimulus.TargetCatId}");

        return true;
    }

    void OnPlayerCatAction(PlayerCatActionEvent actionEvent)
    {
        TryDeliver(actionEvent);
    }

    static CreatureBlackboard FindTargetBoard(string targetCatId)
        => FindBoard(targetCatId);

    static CreatureBlackboard FindBoard(string id)
    {
        if (string.IsNullOrWhiteSpace(id))
            return null;

        string normalized = id.Trim();
        CreatureBlackboard[] boards = FindObjectsByType<CreatureBlackboard>(
            FindObjectsInactive.Exclude,
            FindObjectsSortMode.None);

        for (int i = 0; i < boards.Length; i++)
        {
            CreatureBlackboard board = boards[i];
            if (board == null)
                continue;

            if (string.Equals(board.CreatureId, normalized, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(board.name, normalized, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(board.transform.root.name, normalized, StringComparison.OrdinalIgnoreCase))
            {
                return board;
            }
        }

        return null;
    }

    static Transform FindActorTransform(string actorId)
    {
        CreatureBlackboard actorBoard = FindBoard(actorId);
        if (actorBoard != null)
            return actorBoard.transform;

        SmartObject[] smartObjects = FindObjectsByType<SmartObject>(
            FindObjectsInactive.Exclude,
            FindObjectsSortMode.None);

        for (int i = 0; i < smartObjects.Length; i++)
        {
            SmartObject smart = smartObjects[i];
            if (smart == null)
                continue;

            bool isPlayer = smart.HasTag("entity.player") || smart.HasTag("player");
            bool idMatches =
                string.Equals(smart.Label, actorId, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(smart.name, actorId, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(smart.transform.root.name, actorId, StringComparison.OrdinalIgnoreCase);
            if (isPlayer || idMatches)
                return smart.transform;
        }

        return null;
    }

    static void RememberActorTarget(
        CreatureBlackboard targetBoard,
        SocialStimulus stimulus,
        Transform actorTransform)
    {
        if (targetBoard == null || actorTransform == null)
            return;

        RememberAlias(targetBoard, stimulus.ActorId, actorTransform, stimulus.ActorPosition);
        RememberAlias(targetBoard, actorTransform.name, actorTransform, stimulus.ActorPosition);
        RememberAlias(targetBoard, actorTransform.root.name, actorTransform, stimulus.ActorPosition);
        RememberAlias(targetBoard, "player", actorTransform, stimulus.ActorPosition);
        RememberAlias(targetBoard, "player_cat", actorTransform, stimulus.ActorPosition);
    }

    static void RememberAlias(
        CreatureBlackboard board,
        string key,
        Transform target,
        Vector3 perceivedPosition)
    {
        if (board == null || target == null || string.IsNullOrWhiteSpace(key))
            return;

        board.RememberPerceivedTarget(key.Trim().ToLowerInvariant(), target, perceivedPosition);
    }
}
