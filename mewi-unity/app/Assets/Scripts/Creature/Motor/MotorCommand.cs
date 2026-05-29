using UnityEngine;

/// <summary>
/// The verbs the worker can issue to <see cref="MalbersAnimalAdapter.Apply"/>.
/// Kept Malbers-free so the worker never imports MalbersAnimations.
/// </summary>
public enum MotorCommandKind
{
    None,
    Idle,
    Stop,
    Wander,
    Flee,
    GoTo,
    Follow,
    Action,
    Death,
}

/// <summary>
/// One generic command for the body adapter. Only relevant fields are read for
/// each <see cref="MotorCommandKind"/>; the rest are ignored.
/// </summary>
public struct MotorCommand
{
    public MotorCommandKind Kind;

    public Vector3   Destination;   // GoTo, Flee (threat position)
    public Transform Target;        // Follow

    public int AbilityIndex;        // Action
    public string ActionIntent;      // Action

    public static MotorCommand Idle()                       => new MotorCommand { Kind = MotorCommandKind.Idle };
    public static MotorCommand Stop()                       => new MotorCommand { Kind = MotorCommandKind.Stop };
    public static MotorCommand Wander()                     => new MotorCommand { Kind = MotorCommandKind.Wander };
    public static MotorCommand Flee(Vector3 threat)         => new MotorCommand { Kind = MotorCommandKind.Flee, Destination = threat };
    public static MotorCommand GoTo(Vector3 destination)    => new MotorCommand { Kind = MotorCommandKind.GoTo, Destination = destination };
    public static MotorCommand Follow(Transform target)     => new MotorCommand { Kind = MotorCommandKind.Follow, Target = target };
    public static MotorCommand Action(string intent, int abilityIndex) => new MotorCommand { Kind = MotorCommandKind.Action, ActionIntent = intent, AbilityIndex = abilityIndex };
    public static MotorCommand Death()                      => new MotorCommand { Kind = MotorCommandKind.Death };
}
