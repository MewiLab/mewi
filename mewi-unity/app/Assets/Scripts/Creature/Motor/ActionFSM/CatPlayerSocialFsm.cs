using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Cat-player social FSM recipes selected by a stable string contract.
/// The backend can request one by setting social_act.kind to a motion key.
/// </summary>
[DisallowMultipleComponent]
public sealed class CatPlayerSocialFsm : MonoBehaviour, IInteractionProvider
{
    public const string GreetMeow = "greet_meow";
    public const string SoftMeow = "soft_meow";
    public const string AnswerMeow = "answer_meow";
    public const string SlowBlink = "slow_blink";
    public const string SniffGreeting = "sniff_greeting";
    public const string SitNear = "sit_near";
    public const string LieNear = "lie_near";
    public const string GroomNear = "groom_near";
    public const string RubRequest = "rub_request";
    public const string HeadBump = "head_bump";
    public const string TailUp = "tail_up";
    public const string PlayInvite = "play_invite";
    public const string PlayfulPaw = "playful_paw";
    public const string HappyYes = "happy_yes";
    public const string RefuseNo = "refuse_no";
    public const string StartledFreeze = "startled_freeze";
    public const string CautiousWatch = "cautious_watch";
    public const string AlertWatch = "alert_watch";
    public const string ExcitedShake = "excited_shake";
    public const string SettleClose = "settle_close";

    public static readonly string[] MotionKeys =
    {
        GreetMeow,
        SoftMeow,
        AnswerMeow,
        SlowBlink,
        SniffGreeting,
        SitNear,
        LieNear,
        GroomNear,
        RubRequest,
        HeadBump,
        TailUp,
        PlayInvite,
        PlayfulPaw,
        HappyYes,
        RefuseNo,
        StartledFreeze,
        CautiousWatch,
        AlertWatch,
        ExcitedShake,
        SettleClose,
    };

    const string CommandPrefix = "cat_player_social";
    static readonly List<CatSocialMotionRecipe> DefaultRecipes = BuildDefaultRecipes();

    [Tooltip("Designer-authored cat-player social recipes. social_act.kind/style selects by motion or alias.")]
    [SerializeField] List<CatSocialMotionRecipe> recipes = BuildDefaultRecipes();

    public bool TryBuildInteraction(InteractionContext context, List<IntentMessage> actions)
    {
        if (LooksLikeOtherCatTarget(context) && !LooksLikePlayerTarget(context))
            return false;

        return TryAppendSequence(context, actions, recipes);
    }

    public static bool TryAppendDefaultSequence(InteractionContext context, List<IntentMessage> actions)
        => TryAppendSequence(context, actions, DefaultRecipes);

    void Reset()
    {
        recipes = BuildDefaultRecipes();
    }

    static bool TryAppendSequence(
        InteractionContext context,
        List<IntentMessage> actions,
        List<CatSocialMotionRecipe> recipeList)
    {
        if (actions == null || recipeList == null || !CatSocialMotionUtil.IsSocialIntent(context))
            return false;

        CatSocialMotionRecipe recipe = ResolveRecipe(context, recipeList);
        if (recipe == null)
            return false;

        int before = actions.Count;
        recipe.Append(context, actions, CommandPrefix);
        return actions.Count > before;
    }

    static CatSocialMotionRecipe ResolveRecipe(
        InteractionContext context,
        List<CatSocialMotionRecipe> recipeList)
    {
        CatSocialMotionRecipe recipe = CatSocialMotionUtil.FindRecipe(context.SocialAct.kind, recipeList, false);
        if (recipe != null) return recipe;

        recipe = CatSocialMotionUtil.FindRecipe(context.Style, recipeList, true);
        if (recipe != null) return recipe;

        recipe = CatSocialMotionUtil.FindRecipe(context.SocialAct.tone, recipeList, true);
        if (recipe != null) return recipe;

        recipe = CatSocialMotionUtil.FindRecipe(context.Mood, recipeList, true);
        if (recipe != null) return recipe;

        return PickContextualFallback(context, recipeList);
    }

    static CatSocialMotionRecipe PickContextualFallback(
        InteractionContext context,
        List<CatSocialMotionRecipe> recipeList)
    {
        if (context.SocialAct.expects_reply)
            return CatSocialMotionUtil.FindRecipe(AnswerMeow, recipeList, false);

        string socialText = $"{context.SocialAct.kind} {context.SocialAct.tone} {context.Style} {context.Mood} {context.Reason}";
        if (CatSocialMotionUtil.Contains(socialText, "play")) return CatSocialMotionUtil.FindRecipe(PlayInvite, recipeList, false);
        if (CatSocialMotionUtil.Contains(socialText, "happy") || CatSocialMotionUtil.Contains(socialText, "pleased")) return CatSocialMotionUtil.FindRecipe(HappyYes, recipeList, false);
        if (CatSocialMotionUtil.Contains(socialText, "shy") || CatSocialMotionUtil.Contains(socialText, "careful")) return CatSocialMotionUtil.FindRecipe(CautiousWatch, recipeList, false);
        if (CatSocialMotionUtil.Contains(socialText, "excited")) return CatSocialMotionUtil.FindRecipe(ExcitedShake, recipeList, false);
        if (CatSocialMotionUtil.Contains(socialText, "rest") || CatSocialMotionUtil.Contains(socialText, "calm")) return CatSocialMotionUtil.FindRecipe(SettleClose, recipeList, false);

        MoodModel mood = context.Board != null ? context.Board.mood : null;
        if (mood != null)
        {
            if (mood.fear > 0.65f) return CatSocialMotionUtil.FindRecipe(CautiousWatch, recipeList, false);
            if (mood.energy < 0.25f) return CatSocialMotionUtil.FindRecipe(LieNear, recipeList, false);
            if (mood.social > 0.7f && mood.trust > 0.6f) return CatSocialMotionUtil.FindRecipe(HeadBump, recipeList, false);
            if (mood.trust > 0.45f) return CatSocialMotionUtil.FindRecipe(SniffGreeting, recipeList, false);
        }

        return CatSocialMotionUtil.FindRecipe(GreetMeow, recipeList, false);
    }

    static bool LooksLikeOtherCatTarget(InteractionContext context)
    {
        CreatureBlackboard targetBoard = CatSocialMotionUtil.FindOnTarget<CreatureBlackboard>(context.Target);
        return targetBoard != null && targetBoard != context.Board;
    }

    static bool LooksLikePlayerTarget(InteractionContext context)
    {
        SmartObject smart = CatSocialMotionUtil.FindOnTarget<SmartObject>(context.Target);
        if (smart != null && (smart.HasTag("entity.player") || smart.HasTag("player")))
            return true;

        string name = context.Target != null ? context.Target.root.name : "";
        return CatSocialMotionUtil.Contains(name, "player");
    }

    static List<CatSocialMotionRecipe> BuildDefaultRecipes()
    {
        return new List<CatSocialMotionRecipe>
        {
            Recipe(GreetMeow, "greet,meow,hello,hello_meow", T("go_to"), T("look_at"), T("vocalize")),
            Recipe(SoftMeow, "soft,purr,purr_meow,quiet_meow", T("go_to"), T("sit", false), T("vocalize")),
            Recipe(AnswerMeow, "answer,reply,respond,response", T("look_at"), T("vocalize")),
            Recipe(SlowBlink, "blink,trust_blink,affection", T("look_at"), T("sit", false), T("idle", false)),
            Recipe(SniffGreeting, "sniff,sniff_greet,smell_hello", T("go_to"), T("smell"), T("look_at")),
            Recipe(SitNear, "sit,sit_close,wait_near", T("go_to"), T("sit", false), T("look_at")),
            Recipe(LieNear, "lie,lie_close,rest_near", T("go_to"), T("lie", false)),
            Recipe(GroomNear, "groom,groom_self,comfort_groom", T("go_to"), T("sit", false), T("groom", false)),
            Recipe(RubRequest, "rub,nuzzle,lean,ask_pet", T("go_to"), T("look_at"), T("push", false)),
            Recipe(HeadBump, "headbutt,head_butt,bump,boop", T("go_to"), T("look_at"), T("push", false)),
            Recipe(TailUp, "tail,tail_raise,tail_greet", T("go_to"), T("look_at"), T("nod_head", false)),
            Recipe(PlayInvite, "play,invite_play,pounce_invite", T("go_to"), T("look_at"), T("scratch", false)),
            Recipe(PlayfulPaw, "paw,paw_tap,bat,playful_tap", T("go_to"), T("scratch", false), T("vocalize")),
            Recipe(HappyYes, "yes,nod,happy,agree", T("look_at"), T("nod_head", false), T("vocalize")),
            Recipe(RefuseNo, "no,refuse,decline,back_off", T("look_at"), T("no", false)),
            Recipe(StartledFreeze, "startled,startle,freeze,flinch", T("flinch", false), T("look_at")),
            Recipe(CautiousWatch, "cautious,watch,shy,careful", T("look_at"), T("alert", false)),
            Recipe(AlertWatch, "alert,scan,look_around", T("alert", false), T("look_around", false)),
            Recipe(ExcitedShake, "excited,shake,wriggle", T("go_to"), T("shake", false), T("vocalize")),
            Recipe(SettleClose, "settle,calm,stay,loaf", T("go_to"), T("sit", false), T("lie", false)),
        };
    }

    static CatSocialMotionRecipe Recipe(
        string motion,
        string aliases,
        params CatSocialMotionStep[] steps)
    {
        return new CatSocialMotionRecipe
        {
            motion = motion,
            aliases = aliases,
            steps = new List<CatSocialMotionStep>(steps),
        };
    }

    static CatSocialMotionStep T(string action, bool useTarget = true)
    {
        return new CatSocialMotionStep
        {
            action = action,
            useDirectiveTarget = useTarget,
        };
    }
}
