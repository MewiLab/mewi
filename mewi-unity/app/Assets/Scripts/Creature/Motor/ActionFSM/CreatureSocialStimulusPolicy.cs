using System;
using System.Collections.Generic;
using UnityEngine;

[DisallowMultipleComponent]
public sealed class CreatureSocialStimulusPolicy : MonoBehaviour
{
    public static event Action<CreatureBlackboard, SocialStimulus, CreatureBlackboard.MindDirective> GlobalReactionDirectiveChosen;

    [SerializeField, Min(0.1f)] float ttlSeconds = 4f;
    [SerializeField, Min(0f)] float cooldownSeconds = 1.0f;
    [SerializeField, Range(0f, 1f)] float minimumConfidence = 0.5f;
    [SerializeField, Range(-1f, 1f)] float hardPreemptFacingDot = 0.35f;
    [SerializeField] bool hardPreemptFastApproachAndContact = true;

    readonly Dictionary<string, double> _lastAcceptedAt = new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase);

    public bool TryBuildReactionDirective(
        CreatureBlackboard board,
        out CreatureBlackboard.MindDirective directive,
        out SocialStimulusPreemption preemption)
    {
        directive = default;
        preemption = SocialStimulusPreemption.None;

        if (board == null)
            return false;

        double now = Time.timeAsDouble;
        while (board.TryPopSocialStimulus(out SocialStimulus stimulus))
        {
            if (!stimulus.IsValid || stimulus.IsExpired(now, ttlSeconds))
                continue;
            if (stimulus.Confidence < minimumConfidence)
                continue;
            if (IsCoolingDown(stimulus, now))
                continue;

            string socialKind = MapSocialKind(stimulus.Kind);
            if (string.IsNullOrWhiteSpace(socialKind))
                continue;

            preemption = ResolvePreemption(stimulus);
            if (preemption == SocialStimulusPreemption.None)
                continue;

            directive = CreatureBlackboard.MindDirective.Create(
                "SOCIALIZE",
                stimulus.ActorId,
                $"player_cat_action:{stimulus.Kind}",
                socialAct: new SocialAct
                {
                    kind = socialKind,
                    say = "",
                    tone = "",
                    expects_reply = false,
                },
                requestId: $"stim:{stimulus.CorrelationId}",
                correlationId: stimulus.CorrelationId);

            MarkCooldown(stimulus, now);
            GlobalReactionDirectiveChosen?.Invoke(board, stimulus, directive);
            return true;
        }

        return false;
    }

    bool IsCoolingDown(SocialStimulus stimulus, double now)
    {
        if (cooldownSeconds <= 0f)
            return false;

        string key = CoalescingKey(stimulus);
        return _lastAcceptedAt.TryGetValue(key, out double lastAt) &&
               now - lastAt < cooldownSeconds;
    }

    void MarkCooldown(SocialStimulus stimulus, double now)
    {
        _lastAcceptedAt[CoalescingKey(stimulus)] = now;
    }

    SocialStimulusPreemption ResolvePreemption(SocialStimulus stimulus)
    {
        string kind = Normalize(stimulus.Kind);
        if (hardPreemptFastApproachAndContact &&
            (kind == "player_approach_fast" ||
             kind == "player_contact" ||
             kind == "player_attack"))
        {
            return SocialStimulusPreemption.Hard;
        }

        return stimulus.FacingDot >= hardPreemptFacingDot
            ? SocialStimulusPreemption.Soft
            : SocialStimulusPreemption.None;
    }

    static string MapSocialKind(string stimulusKind)
    {
        switch (Normalize(stimulusKind))
        {
            case "player_nod_yes":
            case "player_nod_head":
            case "player_yes":
                return CatPlayerSocialFsm.HappyYes;
            case "player_shake_no":
            case "player_no":
                return CatPlayerSocialFsm.CautiousWatch;
            case "player_meow":
            case "player_vocalize":
                return CatPlayerSocialFsm.AnswerMeow;
            case "player_sit_near":
                return CatPlayerSocialFsm.SettleClose;
            case "player_play_invite":
                return CatPlayerSocialFsm.PlayInvite;
            case "player_attack":
                return CatPlayerSocialFsm.StartledFreeze;
            case "player_groom":
            case "player_sit":
            case "player_lie":
            case "player_sleep":
                return CatPlayerSocialFsm.SettleClose;
            case "player_smell":
                return CatPlayerSocialFsm.SniffGreeting;
            case "player_scratch":
            case "player_dig":
            case "player_push":
                return CatPlayerSocialFsm.PlayfulPaw;
            case "player_poop":
            case "player_pee":
            case "player_drink":
            case "player_eat":
            case "player_crawl":
            case "player_flinch":
            case "player_startle":
            case "player_stun":
            case "player_open_chest":
                return CatPlayerSocialFsm.CautiousWatch;
            case "player_look_around":
            case "player_alert":
                return CatPlayerSocialFsm.AlertWatch;
            case "player_shake":
                return CatPlayerSocialFsm.ExcitedShake;
            case "player_approach_fast":
            case "player_contact":
                return CatPlayerSocialFsm.CautiousWatch;
            default:
                return "";
        }
    }

    static string CoalescingKey(SocialStimulus stimulus)
        => $"{stimulus.ActorId}|{stimulus.TargetCatId}|{stimulus.Kind}";

    static string Normalize(string value)
        => string.IsNullOrWhiteSpace(value)
            ? ""
            : value.Trim().ToLowerInvariant().Replace('-', '_').Replace(' ', '_');
}
