using UnityEngine;

/// <summary>
/// All tunable values in one place. Create via Assets > Create > Creature > Config.
/// Referenced by CreatureController and passed to layers that need thresholds.
/// </summary>
[CreateAssetMenu(fileName = "CreatureConfig", menuName = "Creature/Config")]
public class CreatureConfig : ScriptableObject
{
    [Header("Perception")]
    public float sightRange        = 12f;
    public float hearingRange      = 8f;
    public float fieldOfViewDeg    = 160f;
    public float fastApproachSpeed = 3f;   // player speed above this = "approaching fast"

    [Header("Feelings")]
    public float feelingScanRadius = 12f;
    public int maxFeelingEvents    = 16;
    public int maxSmellStrings     = 4;
    public int maxSoundStrings     = 4;
    public int maxSignalStrings    = 6;

    [Header("Reflex")]
    public float flinchDistance       = 1.5f;   // how close before startle
    public float flinchCooldown       = 2f;     // seconds between flinches
    public float gazeReactionTime     = 0.1f;   // delay before head turns
    public float startleDuration      = 0.6f;   // how long startled state lasts

    [Header("Tactical")]
    public float wanderSpeed          = 0.2f;
    public float wanderRadius         = 5f;
    public float wanderRetargetTime = 5f;
    public float waypointReachDist    = 0.6f;
    public float fleeThreshold        = 0.6f;
    public float fleeSpeed            = 0.6f;
    public float investigateThreshold = 0.7f;
    public float fleeDistance          = 8f;    // how far to run
    // Add these to your CreatureConfig ScriptableObject:



    [Header("Mind")]
    public float mindTickInterval     = 3f;     // seconds between periodic updates
    public float trustDecayRate       = 0.01f;  // per tick, toward neutral
    public float fearDecayRate        = 0.02f;
    public float hungerGrowthRate     = 0.005f; // per second (≈200s to fill from 0→1)

    [Header("General")]
    public float personalSpaceRadius  = 2f;     // cat's comfort zone

    [Header("Health")]
    public float hungerThreshold = 0.4f;
}
