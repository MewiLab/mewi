using System;
using UnityEngine;

public enum PlayerCatSocialGesture
{
    NodYes,
    ShakeNo,
    Meow,
    SitNear,
    PlayInvite,
}

[DisallowMultipleComponent]
public sealed class PlayerCatSocialFsm : MonoBehaviour
{
    [Header("Player")]
    [SerializeField] Transform playerRoot;
    [SerializeField] CreatureBlackboard playerBlackboard;

    [Header("Systems")]
    [SerializeField] KeyboardProximityCatTargetSource targetSource;
    [SerializeField] PlayerCatActionEmitter emitter;
    [SerializeField] PlayerCatMalbersActionDriver actionDriver;

    [Header("Motor")]
    [SerializeField] bool playMalbersActionDirectly = true;
    [SerializeField] bool emitCompletedImmediately = true;

    int _eventSeq;

    void Awake()
    {
        ResolveReferences();
    }

    public bool TryPerform(PlayerCatSocialGesture gesture)
        => TryPerformSpec(ResolveGesture(gesture));

    public bool TryPerformAction(
        string socialKind,
        string motorAction,
        bool requiresApproach)
    {
        string normalizedMotor = Normalize(motorAction);
        string normalizedKind = NormalizeSocialKind(socialKind, normalizedMotor);
        if (string.IsNullOrWhiteSpace(normalizedKind) || string.IsNullOrWhiteSpace(normalizedMotor))
            return false;

        return TryPerformSpec(new GestureSpec(normalizedKind, normalizedMotor, requiresApproach));
    }

    bool TryPerformSpec(GestureSpec spec)
    {
        ResolveReferences();
        if (targetSource == null || emitter == null)
            return false;

        if (!targetSource.TryGetCurrent(out PlayerCatTargetLock target) &&
            !targetSource.TryAcquireNearest(out target))
        {
            return false;
        }

        string correlationId = $"pcat-{Guid.NewGuid():N}";
        RememberTarget(target);
        Emit(target, spec, correlationId, "started");

        if (playMalbersActionDirectly)
            actionDriver?.TryPlay(spec.MotorAction);

        Emit(target, spec, correlationId, "committed");
        if (emitCompletedImmediately)
            Emit(target, spec, correlationId, "completed");

        return true;
    }

    public bool TryPerformKind(string kind)
    {
        switch (Normalize(kind))
        {
            case "player_nod_yes":
            case "nod_yes":
            case "yes":
                return TryPerform(PlayerCatSocialGesture.NodYes);
            case "player_shake_no":
            case "shake_no":
            case "no":
                return TryPerform(PlayerCatSocialGesture.ShakeNo);
            case "player_meow":
            case "meow":
            case "vocalize":
                return TryPerform(PlayerCatSocialGesture.Meow);
            case "player_sit_near":
            case "sit_near":
            case "sit":
                return TryPerform(PlayerCatSocialGesture.SitNear);
            case "player_play_invite":
            case "play_invite":
            case "play":
                return TryPerform(PlayerCatSocialGesture.PlayInvite);
            default:
            {
                string normalized = Normalize(kind);
                string motor = StripPlayerPrefix(normalized);
                return TryPerformAction(normalized, motor, false);
            }
        }
    }

    public void CancelActiveEpisode(string reason)
    {
        // V1 emits immediately and queues finite motor actions. The future
        // monitored FSM can use this hook to cancel in-flight approach/signals.
        targetSource?.Clear();
    }

    void Emit(
        PlayerCatTargetLock target,
        GestureSpec spec,
        string correlationId,
        string phase)
    {
        if (emitter == null || !target.IsValid)
            return;

        Vector3 actorPosition = playerRoot != null ? playerRoot.position : transform.position;
        Vector3 targetPosition = target.TargetTransform != null ? target.TargetTransform.position : actorPosition;
        string eventId = $"pcat-evt-{++_eventSeq:000000}";
        string actorId = ResolveActorId();

        emitter.Emit(new PlayerCatActionEvent(
            eventId,
            correlationId,
            actorId,
            target.TargetId,
            spec.Kind,
            phase,
            actorPosition,
            targetPosition,
            target.DistanceMeters,
            target.FacingDot,
            target.Confidence,
            Time.timeAsDouble,
            spec.Kind,
            spec.MotorAction));
    }

    void RememberTarget(PlayerCatTargetLock target)
    {
        if (playerBlackboard == null || !target.IsValid)
            return;

        playerBlackboard.RememberPerceivedTarget(
            target.TargetId,
            target.TargetCat.transform,
            target.TargetCat.transform.position);
    }

    string ResolveActorId()
    {
        if (playerBlackboard != null && !string.IsNullOrWhiteSpace(playerBlackboard.CreatureId))
            return playerBlackboard.CreatureId.Trim();
        if (playerRoot != null && !string.IsNullOrWhiteSpace(playerRoot.name))
            return playerRoot.name.Trim();
        return "player";
    }

    void ResolveReferences()
    {
        if (playerRoot == null)
            playerRoot = transform;
        if (playerBlackboard == null && playerRoot != null)
            playerBlackboard = playerRoot.GetComponent<CreatureBlackboard>()
                ?? playerRoot.GetComponentInChildren<CreatureBlackboard>()
                ?? playerRoot.GetComponentInParent<CreatureBlackboard>();
        if (targetSource == null)
            targetSource = GetComponent<KeyboardProximityCatTargetSource>()
                ?? GetComponentInChildren<KeyboardProximityCatTargetSource>()
                ?? GetComponentInParent<KeyboardProximityCatTargetSource>();
        if (emitter == null)
            emitter = GetComponent<PlayerCatActionEmitter>()
                ?? GetComponentInChildren<PlayerCatActionEmitter>()
                ?? GetComponentInParent<PlayerCatActionEmitter>();
        if (emitter == null)
            emitter = gameObject.AddComponent<PlayerCatActionEmitter>();
        if (actionDriver == null)
            actionDriver = GetComponent<PlayerCatMalbersActionDriver>()
                ?? GetComponentInChildren<PlayerCatMalbersActionDriver>()
                ?? GetComponentInParent<PlayerCatMalbersActionDriver>();
        if (actionDriver == null && playMalbersActionDirectly)
            actionDriver = gameObject.AddComponent<PlayerCatMalbersActionDriver>();
    }

    static GestureSpec ResolveGesture(PlayerCatSocialGesture gesture)
    {
        switch (gesture)
        {
            case PlayerCatSocialGesture.NodYes:
                return new GestureSpec("player_nod_yes", "nod_head", false);
            case PlayerCatSocialGesture.ShakeNo:
                return new GestureSpec("player_shake_no", "no", false);
            case PlayerCatSocialGesture.Meow:
                return new GestureSpec("player_meow", "vocalize", false);
            case PlayerCatSocialGesture.SitNear:
                return new GestureSpec("player_sit_near", "sit", true);
            case PlayerCatSocialGesture.PlayInvite:
                return new GestureSpec("player_play_invite", "scratch", true);
            default:
                return new GestureSpec("player_meow", "vocalize", false);
        }
    }

    static string Normalize(string value)
        => string.IsNullOrWhiteSpace(value)
            ? ""
            : value.Trim().ToLowerInvariant().Replace('-', '_').Replace(' ', '_');

    static string NormalizeSocialKind(string socialKind, string motorAction)
    {
        string normalized = Normalize(socialKind);
        if (string.IsNullOrWhiteSpace(normalized))
            normalized = Normalize(motorAction);
        if (string.IsNullOrWhiteSpace(normalized))
            return "";
        return normalized.StartsWith("player_", StringComparison.Ordinal)
            ? normalized
            : $"player_{normalized}";
    }

    static string StripPlayerPrefix(string value)
    {
        string normalized = Normalize(value);
        return normalized.StartsWith("player_", StringComparison.Ordinal)
            ? normalized.Substring("player_".Length)
            : normalized;
    }

    readonly struct GestureSpec
    {
        public readonly string Kind;
        public readonly string MotorAction;
        public readonly bool RequiresApproach;

        public GestureSpec(string kind, string motorAction, bool requiresApproach)
        {
            Kind = kind;
            MotorAction = motorAction;
            RequiresApproach = requiresApproach;
        }
    }
}
