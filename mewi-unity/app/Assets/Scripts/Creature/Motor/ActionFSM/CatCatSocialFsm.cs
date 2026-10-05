using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Cat-cat social FSM recipes selected by a stable string contract.
/// The backend can request one by setting social_act.kind to a motion key.
/// </summary>
[DisallowMultipleComponent]
public sealed class CatCatSocialFsm : MonoBehaviour, IInteractionProvider
{
    public const string CatGreet = "cat_greet";
    public const string NoseTouch = "nose_touch";
    public const string MutualSniff = "mutual_sniff";
    public const string CircleGreeting = "circle_greeting";
    public const string TailGreet = "tail_greet";
    public const string ParallelSit = "parallel_sit";
    public const string ParallelLie = "parallel_lie";
    public const string GroomInvite = "groom_invite";
    public const string ShareSpace = "share_space";
    public const string PlayBow = "play_bow";
    public const string PlayPaw = "play_paw";
    public const string ChaseInvite = "chase_invite";
    public const string SoftChirp = "soft_chirp";
    public const string AnswerChirp = "answer_chirp";
    public const string CautiousPause = "cautious_pause";
    public const string BoundaryHiss = "boundary_hiss";
    public const string StartledBreak = "startled_break";
    public const string DominanceStare = "dominance_stare";
    public const string ReconcileBlink = "reconcile_blink";
    public const string SettlePair = "settle_pair";

    public static readonly string[] MotionKeys =
    {
        CatGreet,
        NoseTouch,
        MutualSniff,
        CircleGreeting,
        TailGreet,
        ParallelSit,
        ParallelLie,
        GroomInvite,
        ShareSpace,
        PlayBow,
        PlayPaw,
        ChaseInvite,
        SoftChirp,
        AnswerChirp,
        CautiousPause,
        BoundaryHiss,
        StartledBreak,
        DominanceStare,
        ReconcileBlink,
        SettlePair,
    };

    const string CommandPrefix = "cat_cat_social";
    static readonly List<CatSocialMotionRecipe> DefaultRecipes = BuildDefaultRecipes();

    [Tooltip("Designer-authored cat-cat social recipes. social_act.kind/style selects by motion or alias.")]
    [SerializeField] List<CatSocialMotionRecipe> recipes = BuildDefaultRecipes();

    public bool TryBuildInteraction(InteractionContext context, List<IntentMessage> actions)
    {
        if (!LooksLikeCatTarget(context))
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
            return CatSocialMotionUtil.FindRecipe(AnswerChirp, recipeList, false);

        string socialText = $"{context.SocialAct.kind} {context.SocialAct.tone} {context.Style} {context.Mood} {context.Reason}";
        if (CatSocialMotionUtil.Contains(socialText, "play")) return CatSocialMotionUtil.FindRecipe(PlayBow, recipeList, false);
        if (CatSocialMotionUtil.Contains(socialText, "chase")) return CatSocialMotionUtil.FindRecipe(ChaseInvite, recipeList, false);
        if (CatSocialMotionUtil.Contains(socialText, "happy") || CatSocialMotionUtil.Contains(socialText, "friendly")) return CatSocialMotionUtil.FindRecipe(NoseTouch, recipeList, false);
        if (CatSocialMotionUtil.Contains(socialText, "shy") || CatSocialMotionUtil.Contains(socialText, "careful")) return CatSocialMotionUtil.FindRecipe(CautiousPause, recipeList, false);
        if (CatSocialMotionUtil.Contains(socialText, "no") || CatSocialMotionUtil.Contains(socialText, "refuse") || CatSocialMotionUtil.Contains(socialText, "boundary")) return CatSocialMotionUtil.FindRecipe(BoundaryHiss, recipeList, false);
        if (CatSocialMotionUtil.Contains(socialText, "calm") || CatSocialMotionUtil.Contains(socialText, "rest")) return CatSocialMotionUtil.FindRecipe(SettlePair, recipeList, false);

        MoodModel mood = context.Board != null ? context.Board.mood : null;
        if (mood != null)
        {
            if (mood.fear > 0.65f) return CatSocialMotionUtil.FindRecipe(CautiousPause, recipeList, false);
            if (mood.energy < 0.25f) return CatSocialMotionUtil.FindRecipe(ParallelLie, recipeList, false);
            if (mood.social > 0.75f && mood.trust > 0.65f) return CatSocialMotionUtil.FindRecipe(GroomInvite, recipeList, false);
            if (mood.social > 0.6f && mood.energy > 0.45f) return CatSocialMotionUtil.FindRecipe(PlayBow, recipeList, false);
            if (mood.trust > 0.45f) return CatSocialMotionUtil.FindRecipe(MutualSniff, recipeList, false);
        }

        return CatSocialMotionUtil.FindRecipe(CatGreet, recipeList, false);
    }

    static bool LooksLikeCatTarget(InteractionContext context)
    {
        CreatureBlackboard targetBoard = CatSocialMotionUtil.FindOnTarget<CreatureBlackboard>(context.Target);
        if (targetBoard != null && targetBoard != context.Board)
            return true;

        SmartObject smart = CatSocialMotionUtil.FindOnTarget<SmartObject>(context.Target);
        return smart != null && smart.HasTag("entity.cat");
    }

    static List<CatSocialMotionRecipe> BuildDefaultRecipes()
    {
        return new List<CatSocialMotionRecipe>
        {
            Recipe(CatGreet, "greet,greet_meow,hello,cat_hello", T("go_to"), T("look_at"), T("vocalize")),
            Recipe(NoseTouch, "nose,nose_greet,nose_bump,boop", T("go_to"), T("smell"), T("look_at")),
            Recipe(MutualSniff, "sniff,sniff_greeting,smell_hello", T("go_to"), T("smell"), T("smell")),
            Recipe(CircleGreeting, "circle,circle_sniff,inspect", T("go_to"), T("look_around", false), T("smell")),
            Recipe(TailGreet, "tail,tail_up,tail_greeting", T("go_to"), T("look_at"), T("nod_head", false)),
            Recipe(ParallelSit, "sit,sit_near,parallel_wait", T("go_to"), T("sit", false), T("look_at")),
            Recipe(ParallelLie, "lie,lie_near,rest_near", T("go_to"), T("lie", false)),
            Recipe(GroomInvite, "groom,groom_near,groom_pair,allogroom", T("go_to"), T("sit", false), T("groom", false)),
            Recipe(ShareSpace, "share,share_place,nearby", T("go_to"), T("sit", false), T("idle", false)),
            Recipe(PlayBow, "play,play_invite,bow,pounce_invite", T("go_to"), T("look_at"), T("scratch", false)),
            Recipe(PlayPaw, "paw,playful_paw,paw_tap,bat", T("go_to"), T("scratch", false), T("vocalize")),
            Recipe(ChaseInvite, "chase,run_play,zoom_invite", T("go_to"), T("shake", false), T("vocalize")),
            Recipe(SoftChirp, "chirp,soft,soft_meow,trill", T("go_to"), T("sit", false), T("vocalize")),
            Recipe(AnswerChirp, "answer,answer_meow,reply,respond,response", T("look_at"), T("vocalize")),
            Recipe(CautiousPause, "cautious,watch,shy,careful,pause", T("look_at"), T("alert", false)),
            Recipe(BoundaryHiss, "hiss,boundary,no,refuse,back_off", T("look_at"), T("no", false), T("vocalize")),
            Recipe(StartledBreak, "startled,startle,freeze,flinch,break", T("flinch", false), T("look_around", false)),
            Recipe(DominanceStare, "stare,dominance,assertive,hold_ground", T("look_at"), T("alert", false)),
            Recipe(ReconcileBlink, "reconcile,blink,slow_blink,trust_blink", T("look_at"), T("sit", false), T("idle", false)),
            Recipe(SettlePair, "settle,calm,loaf,stay_pair", T("go_to"), T("sit", false), T("lie", false)),
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
