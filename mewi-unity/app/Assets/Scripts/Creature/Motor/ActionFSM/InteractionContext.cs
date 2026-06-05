using UnityEngine;

/// <summary>
/// Context passed to world-authored interaction providers.
/// Providers read this and append IntentMessage micro-actions; they never
/// execute body commands directly.
/// </summary>
public struct InteractionContext
{
    public CreatureBlackboard Board { get; private set; }
    public CreatureBlackboard.MindDirective Directive { get; private set; }
    public Transform Target { get; private set; }
    public string TargetId { get; private set; }

    public string Intent => Directive.Intent ?? "";
    public string Mood => Directive.Mood ?? "";
    public string Style => Directive.Style ?? "";
    public string Reason => Directive.Reason ?? "";
    public string RequestId => Directive.RequestId ?? "";
    public string CorrelationId => Directive.CorrelationId ?? "";
    public SocialAct SocialAct => Directive.SocialAct;

    public InteractionContext(
        CreatureBlackboard board,
        CreatureBlackboard.MindDirective directive,
        Transform target)
    {
        Board = board;
        Directive = directive;
        Target = target;
        TargetId = directive.FocusTarget ?? "";
    }
}
