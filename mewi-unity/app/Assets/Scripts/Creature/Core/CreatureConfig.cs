using UnityEngine;
using UnityEngine.Serialization;

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

    [Header("Mind")]
    public float mindTickInterval     = 3f;     // seconds between periodic updates

    [Header("Self Status Drift")]
    public float trustDecayRate       = 0.01f;  // per tick, toward neutral
    public float fearDecayRate        = 0.02f;
    public float energyDecayRate      = 0.02f;
    [FormerlySerializedAs("hungerGrowthRate")]
    [Tooltip("Fullness lost per real-time second. 0.0000389 means a full fish meal reaches the backend 'low fullness' band after about 5 hours.")]
    public float fullnessDecayRate    = 0.0000389f;

    [Header("General")]
    public float personalSpaceRadius  = 2f;     // cat's comfort zone
}
