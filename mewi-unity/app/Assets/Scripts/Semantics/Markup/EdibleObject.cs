using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Serialization;

/// <summary>
/// Sits on a food prop next to its <see cref="SmartObject"/> and acts as the
/// world-side confirmer for the cat's "eat" intent (see ADR-008).
///
/// Behavior:
///   - Has its own trigger collider, sized like a mouth-contact volume.
///   - While a cat's collider is inside the trigger AND CreatureMotorWorker has
///     declared an eat intent for this exact food id AND the cat is inside the
///     bite radius AND the per-cat cooldown has elapsed AND portions remain,
///     the EdibleObject:
///       1. Decrements <see cref="portions"/>.
///       2. Calls <see cref="CreatureBlackboard.RecordBite"/> to update the
///          cat's body drive.
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
    [Tooltip("How much of the cat's fullness one bite restores (0..1). 1.0 = one bite fully satiates her. Lower for snack items like an apple.")]
    [FormerlySerializedAs("hungerReliefPerBite")]
    [SerializeField, Range(0f, 1f)] float fullnessGainPerBite = 1.0f;

    [Header("Sensory Decay")]
    [Tooltip("Scale FeelingEmitter aspect strengths by portionsLeft/maxPortions after each bite, so smell/taste fade as the food is consumed.")]
    [SerializeField] bool decayFeelingsWithPortions = true;

    [Tooltip("Optional explicit FeelingEmitter. Empty uses the SmartObject's emitter (parent or child).")]
    [SerializeField] FeelingEmitter feelingEmitter;

    [Header("Validation")]
    [Tooltip("Only bite when CreatureMotorWorker has declared an active eat intent for this exact food id.")]
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
    [Tooltip("Log when OnTriggerStay rejects a bite attempt, with the gate that failed. Helps diagnose 'eat plays but portions don't drop' issues.")]
    [SerializeField] bool logBiteRejections = true;
    [Tooltip("Throttle for rejection logs — same (cat, reason) is logged at most once every N seconds.")]
    [SerializeField, Min(0.1f)] float rejectionLogIntervalSeconds = 1.5f;

    readonly Dictionary<string, float> _lastBiteAt = new Dictionary<string, float>();
    readonly Dictionary<string, float> _lastRejectionLogAt = new Dictionary<string, float>();
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
        string foodId = FoodId;

        if (portions <= 0)
        {
            LogRejection(other, foodId, "portions_depleted",
                () => $"food '{foodId}' has no portions left (collider may be re-enabled in scene).");
            return;
        }

        var blackboard = ResolveCat(other);
        if (blackboard == null)
        {
            // Don't log — most trigger contacts aren't cats and would spam.
            return;
        }

        string catId = blackboard.CreatureId;
        if (string.IsNullOrWhiteSpace(catId))
        {
            LogRejection(other, foodId, "empty_cat_id",
                () => "CreatureBlackboard found but CreatureId is empty.");
            return;
        }

        if (requireDeclaredEatIntent && !GoalEventBus.HasDeclaration(catId, "eat", foodId))
        {
            if (TryBuildDeclarationMismatchMessage(other, blackboard, foodId, out string message))
            {
                LogRejection(other, foodId, $"no_declaration:{catId}", () => message);
            }
            return;
        }

        if (!IsWithinBiteRadius(blackboard))
        {
            float dist = Vector3.Distance(blackboard.transform.position, BiteCenterPosition());
            LogRejection(other, foodId, $"out_of_bite_radius:{catId}",
                () => $"{catId} is inside trigger but {dist:F2}m from biteCenter (max={biteRadiusMeters:F2}m). " +
                      "Either widen biteRadiusMeters or shrink the trigger collider.");
            return;
        }

        float now = Time.time;
        if (_lastBiteAt.TryGetValue(catId, out float last) && now - last < biteIntervalSeconds)
        {
            // Cooldown is expected between consecutive bites — no log needed.
            return;
        }

        _lastBiteAt[catId] = now;
        portions = Mathf.Max(0, portions - 1);

        blackboard.RecordBite(fullnessGainPerBite);
        GoalEventBus.Confirm(catId, "eat", foodId, now, "consumed_bite");

        ApplyFeelingDecay();

        if (logBites)
            Debug.Log($"[EdibleObject] {catId} ate '{foodId}'. portions left = {portions}. fullness now = {blackboard.health.fullness:F2}.");

        if (portions == 0 && disableColliderWhenDepleted && _trigger != null)
            _trigger.enabled = false;
    }

    void LogRejection(Collider other, string foodId, string reasonKey, System.Func<string> messageBuilder)
    {
        if (!logBiteRejections) return;

        string key = $"{foodId}|{reasonKey}";
        float now = Time.time;
        if (_lastRejectionLogAt.TryGetValue(key, out float last) && now - last < rejectionLogIntervalSeconds)
            return;
        _lastRejectionLogAt[key] = now;

        string ownerInfo = other != null ? other.gameObject.name : "(unknown collider)";
        Debug.LogWarning($"[EdibleObject:{foodId}] bite skipped ({reasonKey}) — collider='{ownerInfo}'. {messageBuilder()}");
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

    static bool TryBuildDeclarationMismatchMessage(
        Collider other,
        CreatureBlackboard blackboard,
        string foodId,
        out string message)
    {
        message = "";
        if (blackboard == null)
            return false;

        CreatureMotorWorker worker = null;
        if (other != null)
            worker = other.GetComponentInParent<CreatureMotorWorker>();
        if (worker == null)
            worker = blackboard.GetComponent<CreatureMotorWorker>()
                ?? blackboard.GetComponentInParent<CreatureMotorWorker>()
                ?? blackboard.GetComponentInChildren<CreatureMotorWorker>();

        if (worker == null || !worker.TryGetActiveIntent(out IntentMessage active))
            return false;

        string activeIntent = Clean(active.Intent).ToLowerInvariant();
        if (activeIntent != "eat")
            return false;

        string activeTarget = Clean(active.TargetKey);
        if (string.IsNullOrEmpty(activeTarget))
        {
            message = $"{blackboard.CreatureId} is actively eating but the eat micro-action has no target. " +
                      $"Expected target_id='{foodId}'.";
            return true;
        }

        if (!string.Equals(activeTarget, foodId, System.StringComparison.OrdinalIgnoreCase))
        {
            message = $"{blackboard.CreatureId} is actively eating target_id='{activeTarget}', " +
                      $"but this EdibleObject uses foodId='{foodId}'. " +
                      "Make the backend target, SmartObject.Label, and foodIdOverride use the same stable id.";
            return true;
        }

        message = $"{blackboard.CreatureId} is actively eating '{foodId}' but GoalEventBus has no matching declaration. " +
                  "Check CreatureMotorWorker declaration timing.";
        return true;
    }

    static string Clean(string value)
        => string.IsNullOrWhiteSpace(value) ? "" : value.Trim();

    void ResolveReferences()
    {
        if (smartObject == null)
            smartObject = ResolveBestSmartObject();

        if (_trigger == null)
        {
            _trigger = GetComponent<Collider>();
            if (_trigger == null)
            {
                Debug.LogError(
                    $"[EdibleObject] '{gameObject.name}' has no Collider on the same GameObject. " +
                    "OnTriggerStay will never fire and the cat can never bite this food. " +
                    "Add a Collider (e.g. SphereCollider sized to the bite zone) and set isTrigger = true."
                );
            }
            else if (!_trigger.isTrigger)
            {
                Debug.LogWarning(
                    $"[EdibleObject] Collider on '{gameObject.name}' is not a trigger. " +
                    "EdibleObject relies on OnTriggerStay; set isTrigger = true."
                );
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
