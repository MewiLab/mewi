using System;

/// <summary>
/// Optional backend-authored social render hint. Unity may render this as
/// bubble/audio/body language, but backend social state remains authoritative.
/// </summary>
[Serializable]
public struct SocialAct
{
    public string kind;
    public string say;
    public string tone;
    public bool expects_reply;

    public bool IsValid =>
        !string.IsNullOrWhiteSpace(kind) ||
        !string.IsNullOrWhiteSpace(say) ||
        !string.IsNullOrWhiteSpace(tone);

    public static SocialAct Empty => new SocialAct
    {
        kind = "",
        say = "",
        tone = "",
        expects_reply = false,
    };
}
