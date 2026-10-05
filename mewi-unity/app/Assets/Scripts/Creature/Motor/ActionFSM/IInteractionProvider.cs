using System.Collections.Generic;

/// <summary>
/// Optional object-local interaction recipe. Attach an implementation to a
/// SmartObject, ZoneVolume, cat/player target, or semantic child.
/// </summary>
public interface IInteractionProvider
{
    bool TryBuildInteraction(InteractionContext context, List<IntentMessage> actions);
}
