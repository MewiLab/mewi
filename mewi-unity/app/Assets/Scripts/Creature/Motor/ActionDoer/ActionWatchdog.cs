/// <summary>
/// What the action watchdog wants the adapter to do this frame.
/// </summary>
public enum ActionWatchdogDecision
{
    Continue,
    ForceCleanup,
    FinishCooldown,
}

/// <summary>
/// Why an action command finished. The adapter exposes this for plan reports.
/// </summary>
public enum ActionCompletionReason
{
    None,
    Completed,
    TimedOutBeforeStart,
    TimedOut,
    Cancelled,
}

/// <summary>
/// Pure timing state for Malbers action modes. It does not call Malbers; the
/// adapter performs cleanup when this watchdog asks for it.
/// </summary>
public class ActionWatchdog
{
    ActionExecutionConfig _config = new ActionExecutionConfig();

    bool _active;
    bool _started;
    bool _coolingDown;
    string _intent = "";
    int _abilityIndex;
    float _requestedAt;
    float _modeStartedAt;
    float _cooldownEndsAt;
    ActionCompletionReason _completionReason = ActionCompletionReason.None;

    public bool IsBusy => _active || _coolingDown;
    public bool IsActive => _active;
    public bool IsCoolingDown => _coolingDown;
    public string Intent => _intent;
    public int AbilityIndex => _abilityIndex;
    public ActionCompletionReason CompletionReason => _completionReason;

    public void Configure(ActionExecutionConfig config)
    {
        if (config != null) _config = config;
    }

    public void Begin(string intent, int abilityIndex, float now)
    {
        _active = true;
        _started = false;
        _coolingDown = false;
        _intent = string.IsNullOrWhiteSpace(intent) ? "action" : intent.Trim();
        _abilityIndex = abilityIndex;
        _requestedAt = now;
        _modeStartedAt = 0f;
        _cooldownEndsAt = 0f;
        _completionReason = ActionCompletionReason.None;
    }

    public bool NotifyModeStarted(int abilityIndex, float now)
    {
        if (!_active || abilityIndex != _abilityIndex) return false;
        _started = true;
        _modeStartedAt = now;
        return true;
    }

    public bool NotifyModeEnded(int abilityIndex, float now)
    {
        if (!_active || abilityIndex != _abilityIndex) return false;
        Complete(ActionCompletionReason.Completed, now);
        return true;
    }

    public ActionWatchdogDecision Tick(float now)
    {
        if (_coolingDown)
            return now >= _cooldownEndsAt ? ActionWatchdogDecision.FinishCooldown : ActionWatchdogDecision.Continue;

        if (!_active)
            return ActionWatchdogDecision.Continue;

        float activationTimeout = _config.ActivationTimeoutFor(_intent);
        if (!_started && activationTimeout > 0f && now - _requestedAt >= activationTimeout)
            return ActionWatchdogDecision.ForceCleanup;

        float maxActionSeconds = _config.MaxActionSecondsFor(_intent);
        if (_started && maxActionSeconds > 0f && now - _modeStartedAt >= maxActionSeconds)
            return ActionWatchdogDecision.ForceCleanup;

        return ActionWatchdogDecision.Continue;
    }

    public void NotifyTimedOut(float now)
    {
        Complete(_started ? ActionCompletionReason.TimedOut : ActionCompletionReason.TimedOutBeforeStart, now);
    }

    public void FinishCooldown()
    {
        _coolingDown = false;
    }

    public void Cancel()
    {
        if (_active || _coolingDown)
            _completionReason = ActionCompletionReason.Cancelled;

        _active = false;
        _started = false;
        _coolingDown = false;
    }

    void Complete(ActionCompletionReason reason, float now)
    {
        _active = false;
        _started = false;
        _completionReason = reason;

        float cooldown = _config.CooldownSecondsFor(_intent);
        _coolingDown = cooldown > 0f;
        _cooldownEndsAt = now + cooldown;
    }
}
