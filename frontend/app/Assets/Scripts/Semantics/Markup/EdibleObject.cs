using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// Sits on a food prop next to its <see cref="SmartObject"/> and acts as the
/// world-side confirmer for the cat's "eat" intent (see ADR-008).
///
/// Behavior:
///   - Has its own trigger collider, sized like a mouth-contact volume.
///   - While a cat's collider is inside the trigger AND CreatureWorker has
///     declared an eat intent for this exact food id AND the cat is inside the
///     bite radius AND the per-cat cooldown has elapsed AND portions remain,
///     the EdibleObject:
///       1. Decrements <see cref="portions"/>.
///       2. Calls <see cref="CreatureBlackboard.RecordBite"/> to update the
///          cat's inventory.
///       3. Fires <see cref="GoalEventBus.Confirm"/> so the worker's eat
///          step reports honestly on its next completion check.
///   - When portions reach 0, the trigger collider is disabled (per design:
///     the prop stays visually present, only the eating affordance is gone).
/// </summary>
[DisallowMultipleComponent]
public class EdibleObject : MonoBehaviour
{
    [Header("Identity")]
    [SerializeField] SmartObject smartObject;
    [SerializeField, Tooltip("Optional exact id expected from LLM targets, e.g. SM_Fish_1. Empty uses the nearest food SmartObject or parent object name.")]
    string foodIdOverride = "";

    [Header("Resource")]
    [Tooltip("How many bites this food can supply before it's depleted.")]
    [SerializeField, Min(0)] int portions = 1;

    [Header("Nutrition")]
    [Tooltip("How much hunger this food relieves per bite (0..1). Higher = more filling.")]
    [SerializeField, Range(0f, 1f)] float hungerReliefPerBite = 0.35f;

    [Header("Sensory Decay")]
    [Tooltip("Scale FeelingEmitter aspect strengths by portionsLeft/maxPortions after each bite, so smell/taste fade as the food is consumed.")]
    [SerializeField] bool decayFeelingsWithPortions = true;

    [Tooltip("Optional explicit FeelingEmitter. Empty uses the SmartObject's emitter (parent or child).")]
    [SerializeField] FeelingEmitter feelingEmitter;

    [Header("Validation")]
    [Tooltip("Only bite when CreatureWorker has declared an active eat intent for this exact food id.")]
    [SerializeField] bool requireDeclaredEatIntent = true;

    [Tooltip("Cat must be within this radius of the bite center. This prevents huge trigger volumes from eating at a distance.")]
    [SerializeField, Min(0f)] float biteRadiusMeters = 1.2f;

    [Tooltip("Optional explicit bite center. Empty uses SmartObject.Position, then this transform.")]
    [SerializeField] Transform biteCenter;

    [Tooltip("Ignore vertical offset when checking bite distance. Useful when food sits on a table/prop above the NavMesh.")]
    [SerializeField] bool useHorizontalBiteDistance = true;

    [Tooltip("Per-cat cooldown between bites of this same food, in seconds.")]
    [SerializeField, Min(0f)] float biteIntervalSeconds = 1.5f;

    [Tooltip("Disable the trigger collider once portions reach 0. Prop stays visible.")]
    [SerializeField] bool disableColliderWhenDepleted = true;

    [Header("Debug")]
    [SerializeField] bool logBites = true;

    readonly Dictionary<string, float> _lastBiteAt = new Dictionary<string, float>();
    Collider _trigger;
    int _maxPortions;
    float[] _baselineAspectStrengths;

    public int Portions => portions;
    public string FoodId => ResolveFoodId();

    void Awake()
    {
        ResolveReferences();
        _maxPortions = Mathf.Max(1, portions);
        CacheBaselineFeelingStrengths();
    }

    void OnValidate()
    {
        ResolveReferences();
    }

    void OnTriggerStay(Collider other)
    {
        if (portions <= 0) return;

        var blackboard = ResolveCat(other);
        if (blackboard == null) return;

        string catId = blackboard.CreatureId;
        if (string.IsNullOrWhiteSpace(catId)) return;

        string foodId = FoodId;
        if (requireDeclaredEatIntent && !GoalEventBus.HasDeclaration(catId, "eat", foodId))
            return;

        if (!IsWithinBiteRadius(blackboard))
            return;

        float now = Time.time;
        if (_lastBiteAt.TryGetValue(catId, out float last) && now - last < biteIntervalSeconds)
            return;

        _lastBiteAt[catId] = now;
        portions = Mathf.Max(0, portions - 1);

        blackboard.RecordBite(foodId, now, hungerReliefPerBite);
        GoalEventBus.Confirm(catId, "eat", foodId, now, "consumed_bite");

        ApplyFeelingDecay();

        if (logBites)
            Debug.Log($"[EdibleObject] {catId} ate '{foodId}'. portions left = {portions}.");

        if (portions == 0 && disableColliderWhenDepleted && _trigger != null)
            _trigger.enabled = false;
    }

    void CacheBaselineFeelingStrengths()
    {
        if (feelingEmitter == null)
            feelingEmitter = GetComponentInParent<FeelingEmitter>() ?? GetComponentInChildren<FeelingEmitter>();

        if (feelingEmitter == null || feelingEmitter.aspects == null)
        {
            _baselineAspectStrengths = null;
            return;
        }

        var aspects = feelingEmitter.aspects;
        _baselineAspectStrengths = new float[aspects.Count];
        for (int i = 0; i < aspects.Count; i++)
            _baselineAspectStrengths[i] = aspects[i] != null ? aspects[i].strength : 0f;
    }

    void ApplyFeelingDecay()
    {
        if (!decayFeelingsWithPortions) return;
        if (feelingEmitter == null || _baselineAspectStrengths == null) return;

        float scale = _maxPortions > 0 ? (float)portions / _maxPortions : 0f;
        var aspects = feelingEmitter.aspects;
        int count = Mathf.Min(aspects != null ? aspects.Count : 0, _baselineAspectStrengths.Length);
        for (int i = 0; i < count; i++)
        {
            if (aspects[i] == null) continue;
            aspects[i].strength = Mathf.Clamp01(_baselineAspectStrengths[i] * scale);
        }
    }

    static CreatureBlackboard ResolveCat(Collider other)
    {
        if (other == null) return null;
        return other.GetComponentInParent<CreatureBlackboard>();
    }

    void ResolveReferences()
    {
        if (smartObject == null)
            smartObject = ResolveBestSmartObject();

        if (_trigger == null)
        {
            _trigger = GetComponent<Collider>();
            if (_trigger != null && !_trigger.isTrigger)
            {
                Debug.LogWarning($"[EdibleObject] Collider on '{gameObject.name}' is not a trigger. EdibleObject relies on OnTriggerStay; set isTrigger = true.");
            }
        }
    }

    SmartObject ResolveBestSmartObject()
    {
        SmartObject self = GetComponent<SmartObject>();
        SmartObject parent = GetComponentInParent<SmartObject>();
        SmartObject child = GetComponentInChildren<SmartObject>();

        if (IsFoodSmartObject(self)) return self;
        if (IsFoodSmartObject(parent)) return parent;
        if (IsFoodSmartObject(child)) return child;

        return self ?? parent ?? child;
    }

    string ResolveFoodId()
    {
        if (!string.IsNullOrWhiteSpace(foodIdOverride))
            return foodIdOverride.Trim();

        if (smartObject != null)
        {
            if (IsFoodSmartObject(smartObject) && !string.IsNullOrWhiteSpace(smartObject.Label))
                return smartObject.Label;
        }

        if (transform.parent != null)
            return transform.parent.name;

        return gameObject.name;
    }

    bool IsWithinBiteRadius(CreatureBlackboard blackboard)
    {
        if (blackboard == null) return false;
        if (biteRadiusMeters <= 0f) return true;

        Vector3 catPosition = blackboard.transform.position;
        Vector3 foodPosition = BiteCenterPosition();
        if (useHorizontalBiteDistance)
        {
            catPosition.y = 0f;
            foodPosition.y = 0f;
        }

        return Vector3.Distance(catPosition, foodPosition) <= biteRadiusMeters;
    }

    Vector3 BiteCenterPosition()
    {
        if (biteCenter != null)
            return biteCenter.position;

        if (smartObject != null)
            return smartObject.Position;

        return transform.position;
    }

    static bool IsFoodSmartObject(SmartObject candidate)
    {
        return candidate != null &&
            (candidate.HasTag("prop.food") || candidate.HasTag("food"));
    }
}
