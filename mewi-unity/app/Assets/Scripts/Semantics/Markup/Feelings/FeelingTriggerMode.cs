/// <summary>
/// Designer-facing activation mode for a FeelingAspect.
/// Event-style modes are implemented through FeelingEmitter.EmitTrigger().
/// </summary>
public enum FeelingTriggerMode
{
    AlwaysOn,
    StateBased,
    TimedEvent,
    Collision,
    Kick,
    Fall,
    EatenOrUsed,
    EnvironmentModified,
    ContactOnly
}
