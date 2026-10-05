using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Bridges Unity's system-wide social events into the live PlanExecutionReport.
/// Gameplay systems emit domain events; this class alone translates them for the backend.
/// </summary>
public static class LiveMicroActionReportEmitter
{
    const int MaxCachedPlayerActions = 128;

    static readonly Dictionary<string, PlayerCatActionEvent> _playerActionsById =
        new Dictionary<string, PlayerCatActionEvent>(StringComparer.OrdinalIgnoreCase);
    static readonly Queue<string> _playerActionOrder = new Queue<string>();
    static readonly Dictionary<string, Queue<PlanMicroActionEvent>> _pendingEventsByCreature =
        new Dictionary<string, Queue<PlanMicroActionEvent>>(StringComparer.OrdinalIgnoreCase);

    static bool _subscribed;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
    static void ResetForPlayMode()
    {
        PlayerCatActionEmitter.GlobalActionEmitted -= OnPlayerCatAction;
        CreatureSocialStimulusBus.GlobalStimulusDelivered -= OnSocialStimulusDelivered;
        CreatureSocialStimulusPolicy.GlobalReactionDirectiveChosen -= OnReactionDirectiveChosen;
        _subscribed = false;
        _playerActionsById.Clear();
        _playerActionOrder.Clear();
        _pendingEventsByCreature.Clear();
    }

    public static PlanMicroActionEvent[] DrainEvents(string creatureId)
    {
        string id = NormalizeId(creatureId);
        if (string.IsNullOrWhiteSpace(id) ||
            !_pendingEventsByCreature.TryGetValue(id, out Queue<PlanMicroActionEvent> queue) ||
            queue.Count == 0)
        {
            return Array.Empty<PlanMicroActionEvent>();
        }

        PlanMicroActionEvent[] events = queue.ToArray();
        queue.Clear();
        return events;
    }

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Subscribe()
    {
        if (_subscribed)
            return;

        PlayerCatActionEmitter.GlobalActionEmitted += OnPlayerCatAction;
        CreatureSocialStimulusBus.GlobalStimulusDelivered += OnSocialStimulusDelivered;
        CreatureSocialStimulusPolicy.GlobalReactionDirectiveChosen += OnReactionDirectiveChosen;
        _subscribed = true;
    }

    static void OnPlayerCatAction(PlayerCatActionEvent actionEvent)
    {
        if (string.IsNullOrWhiteSpace(actionEvent.EventId))
            return;

        _playerActionsById[actionEvent.EventId] = actionEvent;
        _playerActionOrder.Enqueue(actionEvent.EventId);
        TrimPlayerActionCache();
    }

    static void OnSocialStimulusDelivered(SocialStimulus stimulus)
    {
        if (!stimulus.IsValid)
            return;

        CreatureBlackboard targetBoard = FindBoard(stimulus.TargetCatId);
        if (targetBoard == null)
            return;

        if (_playerActionsById.TryGetValue(stimulus.SourceEventId ?? "", out PlayerCatActionEvent actionEvent))
            Enqueue(targetBoard, FromPlayerCatAction(actionEvent));

        Enqueue(targetBoard, FromSocialStimulus(stimulus));
    }

    static void OnReactionDirectiveChosen(
        CreatureBlackboard board,
        SocialStimulus stimulus,
        CreatureBlackboard.MindDirective directive)
    {
        if (board == null || !stimulus.IsValid || !directive.IsValid)
            return;

        string reactionEventId = $"react-{stimulus.EventId}";
        Enqueue(
            board,
            FromReactionDirective(
                board,
                stimulus,
                directive,
                reactionEventId));
    }

    static void TrimPlayerActionCache()
    {
        while (_playerActionOrder.Count > MaxCachedPlayerActions)
        {
            string oldest = _playerActionOrder.Dequeue();
            if (!_playerActionOrder.Contains(oldest))
                _playerActionsById.Remove(oldest);
        }
    }

    static void Enqueue(CreatureBlackboard board, PlanMicroActionEvent liveEvent)
    {
        if (board == null || liveEvent == null || string.IsNullOrWhiteSpace(liveEvent.event_id))
            return;

        string creatureId = NormalizeId(board.CreatureId);
        if (string.IsNullOrWhiteSpace(creatureId))
            return;

        if (!_pendingEventsByCreature.TryGetValue(creatureId, out Queue<PlanMicroActionEvent> queue))
        {
            queue = new Queue<PlanMicroActionEvent>();
            _pendingEventsByCreature[creatureId] = queue;
        }

        queue.Enqueue(liveEvent);
    }

    static PlanMicroActionEvent FromPlayerCatAction(PlayerCatActionEvent actionEvent)
    {
        return new PlanMicroActionEvent
        {
            event_id = actionEvent.EventId ?? "",
            correlation_id = actionEvent.CorrelationId ?? "",
            request_id = "",
            actor_type = "player_cat",
            actor_id = string.IsNullOrWhiteSpace(actionEvent.ActorId) ? "player_cat" : actionEvent.ActorId,
            target_type = "cat",
            target_id = actionEvent.TargetCatId ?? "",
            direction = "player_cat_to_cat",
            action = actionEvent.Kind ?? "",
            behavior_key = actionEvent.BehaviorKey ?? "",
            motor_action = actionEvent.MotorAction ?? "",
            phase = string.IsNullOrWhiteSpace(actionEvent.Phase) ? "completed" : actionEvent.Phase,
            status = "",
            source_event_id = "",
            timestamp = (float)actionEvent.TimestampSeconds,
            distance_m = actionEvent.DistanceMeters,
            facing_dot = actionEvent.FacingDot,
            confidence = actionEvent.Confidence,
        };
    }

    static PlanMicroActionEvent FromSocialStimulus(SocialStimulus stimulus)
    {
        return new PlanMicroActionEvent
        {
            event_id = stimulus.EventId ?? "",
            correlation_id = stimulus.CorrelationId ?? "",
            request_id = "",
            actor_type = "player_cat",
            actor_id = stimulus.ActorId ?? "",
            target_type = "cat",
            target_id = stimulus.TargetCatId ?? "",
            direction = "player_cat_to_cat",
            action = "social_stimulus_delivered",
            behavior_key = "",
            motor_action = "",
            phase = "delivered",
            status = "",
            source_event_id = stimulus.SourceEventId ?? "",
            timestamp = (float)stimulus.TimestampSeconds,
            distance_m = stimulus.DistanceMeters,
            facing_dot = stimulus.FacingDot,
            confidence = stimulus.Confidence,
        };
    }

    static PlanMicroActionEvent FromReactionDirective(
        CreatureBlackboard board,
        SocialStimulus stimulus,
        CreatureBlackboard.MindDirective directive,
        string eventId)
    {
        string socialKind = directive.SocialAct.kind ?? "";
        return new PlanMicroActionEvent
        {
            event_id = eventId ?? "",
            correlation_id = stimulus.CorrelationId ?? "",
            request_id = directive.RequestId ?? "",
            actor_type = "cat",
            actor_id = board != null ? board.CreatureId ?? "" : "",
            target_type = "player_cat",
            target_id = stimulus.ActorId ?? "",
            direction = "cat_to_player_cat",
            action = string.IsNullOrWhiteSpace(socialKind) ? "reaction_directive_chosen" : socialKind,
            behavior_key = socialKind,
            motor_action = "",
            phase = "chosen",
            status = "",
            source_event_id = stimulus.EventId ?? "",
            timestamp = Time.time,
            distance_m = stimulus.DistanceMeters,
            facing_dot = stimulus.FacingDot,
            confidence = stimulus.Confidence,
        };
    }

    static CreatureBlackboard FindBoard(string id)
    {
        if (string.IsNullOrWhiteSpace(id))
            return null;

        string normalized = id.Trim();
        CreatureBlackboard[] boards = UnityEngine.Object.FindObjectsByType<CreatureBlackboard>(
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

    static string NormalizeId(string value)
        => string.IsNullOrWhiteSpace(value) ? "" : value.Trim();
}
