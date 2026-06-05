using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;
using UnityEngine.Serialization;

public enum CatDoorMotionMode
{
    Slide,
    Rotate,
}

/// <summary>
/// Scene-authored door behavior for cat navigation. Attach this to a door root,
/// assign the moving door transform if needed, then place CatNavigationPoint
/// children in front of the door. The door opens when a creature reaches one of
/// those points.
/// </summary>
[DisallowMultipleComponent]
public class CatDoorController : MonoBehaviour
{
    [Header("Door Motion")]
    [SerializeField] CatDoorMotionMode motionMode = CatDoorMotionMode.Slide;
    [SerializeField] Transform doorPivot;
    [FormerlySerializedAs("captureClosedRotationOnAwake")]
    [SerializeField] bool captureClosedPoseOnAwake = true;

    [Header("Slide")]
    [Tooltip("Local-space open offset. Positive X is the door's local right.")]
    [SerializeField] Vector3 openLocalPositionOffset = new Vector3(1.25f, 0f, 0f);
    [SerializeField] Vector3 closedLocalPosition;
    [SerializeField] float slideSpeed = 1.5f;

    [Header("Rotation")]
    [SerializeField] Vector3 closedLocalEulerAngles;
    [SerializeField] Vector3 openLocalEulerOffset = new Vector3(0f, 90f, 0f);
    [SerializeField] float rotationSpeedDegrees = 180f;

    [Header("State")]
    [SerializeField] bool openOnStart;
    [SerializeField] bool keepOpenOnceOpened;

    [Header("Auto Close")]
    [SerializeField] bool autoClose = true;
    [SerializeField] float closeDelaySeconds = 2f;

    [Header("Activation")]
    [SerializeField] List<Transform> activationPoints = new List<Transform>();
    [SerializeField] bool autoDiscoverChildNavigationPoints = true;
    [SerializeField] List<CatNavigationPointKind> activationPointKinds =
        new List<CatNavigationPointKind>
        {
            CatNavigationPointKind.Approach,
            CatNavigationPointKind.Entry,
        };
    [SerializeField] float openDistance = 1.1f;
    [SerializeField] float closeDistance = 1.8f;

    [Header("Creature Lookup")]
    [SerializeField] Transform explicitCreature;
    [SerializeField] bool findCreatureMotorWorkers = true;
    [SerializeField] float creatureScanIntervalSeconds = 0.25f;
    [SerializeField] string requiredCreatureTag = "";

    [Header("Optional Blockers")]
    [Tooltip("Optional dynamic NavMesh obstacles to disable while the door is open.")]
    [SerializeField] List<NavMeshObstacle> obstaclesToDisableWhileOpen = new List<NavMeshObstacle>();

    [Tooltip("Optional colliders to disable while the door is open. Leave empty when the moving door collider already behaves correctly.")]
    [SerializeField] List<Collider> collidersToDisableWhileOpen = new List<Collider>();

    [Header("Debug")]
    [SerializeField] bool logDoorEvents;
    [SerializeField] bool isOpenRequested;

    readonly List<Transform> _resolvedActivationPoints = new List<Transform>();
    readonly List<Transform> _creatures = new List<Transform>();

    Vector3 _closedLocalPosition;
    Vector3 _openLocalPosition;
    Quaternion _closedLocalRotation;
    Quaternion _openLocalRotation;
    float _lastCreatureNearAt;
    float _nextCreatureScanAt;
    bool _blockersDisabled;

    public bool IsOpenRequested => isOpenRequested;
    public Transform DoorPivot => doorPivot != null ? doorPivot : transform;

    void Reset()
    {
        doorPivot = transform;
        RefreshActivationPoints();
    }

    void Awake()
    {
        if (doorPivot == null)
            doorPivot = transform;

        CacheDoorPose();

        RefreshActivationPoints();

        if (openOnStart)
        {
            isOpenRequested = true;
            _lastCreatureNearAt = Time.time;
            ApplyOpenPoseImmediately();
            ApplyBlockersForOpenState(true);
        }
    }

    void OnValidate()
    {
        if (doorPivot == null)
            doorPivot = transform;

        slideSpeed = Mathf.Max(0.01f, slideSpeed);
        rotationSpeedDegrees = Mathf.Max(1f, rotationSpeedDegrees);
        openDistance = Mathf.Max(0.05f, openDistance);
        closeDistance = Mathf.Max(openDistance, closeDistance);
        closeDelaySeconds = Mathf.Max(0f, closeDelaySeconds);
        creatureScanIntervalSeconds = Mathf.Max(0.05f, creatureScanIntervalSeconds);
        RefreshActivationPoints();
    }

    void Update()
    {
        if (IsCreatureNearActivationPoint())
        {
            RequestOpen();
        }
        else if (CanAutoCloseNow())
        {
            RequestClose();
        }

        MoveDoor();

        ApplyBlockersForOpenState(isOpenRequested);
    }

    [ContextMenu("Open Door")]
    public void RequestOpen()
    {
        _lastCreatureNearAt = Time.time;
        if (isOpenRequested) return;

        isOpenRequested = true;
        if (logDoorEvents)
            Debug.Log($"[CatDoorController] Open {name}");
    }

    [ContextMenu("Close Door")]
    public void RequestClose()
    {
        if (!isOpenRequested || keepOpenOnceOpened) return;

        isOpenRequested = false;
        if (logDoorEvents)
            Debug.Log($"[CatDoorController] Close {name}");
    }

    [ContextMenu("Capture Closed Pose")]
    public void CaptureClosedPose()
    {
        Transform pivot = DoorPivot;
        closedLocalPosition = pivot.localPosition;
        closedLocalEulerAngles = pivot.localEulerAngles;
        CacheDoorPose();
    }

    [ContextMenu("Capture Closed Rotation")]
    public void CaptureClosedRotation()
    {
        CaptureClosedPose();
    }

    [ContextMenu("Refresh Activation Points")]
    public void RefreshAuthoredActivationPoints()
    {
        RefreshActivationPoints();
    }

    bool CanAutoCloseNow()
    {
        if (!isOpenRequested || !autoClose || keepOpenOnceOpened)
            return false;

        return Time.time - _lastCreatureNearAt >= closeDelaySeconds;
    }

    void CacheDoorPose()
    {
        Transform pivot = DoorPivot;

        _closedLocalPosition = captureClosedPoseOnAwake
            ? pivot.localPosition
            : closedLocalPosition;
        _openLocalPosition = _closedLocalPosition + openLocalPositionOffset;

        _closedLocalRotation = captureClosedPoseOnAwake
            ? pivot.localRotation
            : Quaternion.Euler(closedLocalEulerAngles);
        _openLocalRotation = _closedLocalRotation * Quaternion.Euler(openLocalEulerOffset);
    }

    void MoveDoor()
    {
        if (motionMode == CatDoorMotionMode.Slide)
        {
            Vector3 targetPosition = isOpenRequested ? _openLocalPosition : _closedLocalPosition;
            doorPivot.localPosition = Vector3.MoveTowards(
                doorPivot.localPosition,
                targetPosition,
                slideSpeed * Time.deltaTime);
            return;
        }

        Quaternion targetRotation = isOpenRequested ? _openLocalRotation : _closedLocalRotation;
        doorPivot.localRotation = Quaternion.RotateTowards(
            doorPivot.localRotation,
            targetRotation,
            rotationSpeedDegrees * Time.deltaTime);
    }

    void ApplyOpenPoseImmediately()
    {
        if (motionMode == CatDoorMotionMode.Slide)
            doorPivot.localPosition = _openLocalPosition;
        else
            doorPivot.localRotation = _openLocalRotation;
    }

    bool IsCreatureNearActivationPoint()
    {
        float threshold = isOpenRequested ? closeDistance : openDistance;
        float thresholdSqr = threshold * threshold;

        if (explicitCreature != null &&
            IsValidCreature(explicitCreature) &&
            IsNearAnyActivationPoint(explicitCreature.position, thresholdSqr))
        {
            return true;
        }

        if (!findCreatureMotorWorkers)
            return false;

        RefreshCreatureCache();
        for (int i = 0; i < _creatures.Count; i++)
        {
            Transform creature = _creatures[i];
            if (creature == null || !IsValidCreature(creature))
                continue;

            if (IsNearAnyActivationPoint(creature.position, thresholdSqr))
                return true;
        }

        return false;
    }

    void RefreshCreatureCache()
    {
        if (Time.time < _nextCreatureScanAt)
            return;

        _nextCreatureScanAt = Time.time + creatureScanIntervalSeconds;
        _creatures.Clear();

        CreatureMotorWorker[] workers = FindObjectsByType<CreatureMotorWorker>(FindObjectsSortMode.None);
        for (int i = 0; i < workers.Length; i++)
        {
            CreatureMotorWorker worker = workers[i];
            if (worker != null && worker.isActiveAndEnabled)
                _creatures.Add(worker.transform);
        }
    }

    bool IsValidCreature(Transform creature)
    {
        if (creature == null)
            return false;

        if (string.IsNullOrWhiteSpace(requiredCreatureTag))
            return true;

        return creature.gameObject.tag == requiredCreatureTag.Trim();
    }

    bool IsNearAnyActivationPoint(Vector3 creaturePosition, float thresholdSqr)
    {
        if (_resolvedActivationPoints.Count == 0)
        {
            Vector3 fallback = transform.position;
            return (creaturePosition - fallback).sqrMagnitude <= thresholdSqr;
        }

        for (int i = 0; i < _resolvedActivationPoints.Count; i++)
        {
            Transform point = _resolvedActivationPoints[i];
            if (point == null)
                continue;

            if ((creaturePosition - point.position).sqrMagnitude <= thresholdSqr)
                return true;
        }

        return false;
    }

    void RefreshActivationPoints()
    {
        _resolvedActivationPoints.Clear();

        if (activationPoints != null)
        {
            for (int i = 0; i < activationPoints.Count; i++)
                AddActivationPoint(activationPoints[i]);
        }

        if (!autoDiscoverChildNavigationPoints)
            return;

        CatNavigationPoint[] childPoints = GetComponentsInChildren<CatNavigationPoint>(true);
        for (int i = 0; i < childPoints.Length; i++)
        {
            CatNavigationPoint point = childPoints[i];
            if (point == null || !IsActivationKind(point.kind))
                continue;

            AddActivationPoint(point.transform);
        }
    }

    void AddActivationPoint(Transform point)
    {
        if (point != null && !_resolvedActivationPoints.Contains(point))
            _resolvedActivationPoints.Add(point);
    }

    bool IsActivationKind(CatNavigationPointKind kind)
    {
        if (activationPointKinds == null || activationPointKinds.Count == 0)
            return true;

        for (int i = 0; i < activationPointKinds.Count; i++)
        {
            if (activationPointKinds[i] == kind)
                return true;
        }

        return false;
    }

    void ApplyBlockersForOpenState(bool open)
    {
        if (_blockersDisabled == open)
            return;

        _blockersDisabled = open;

        if (obstaclesToDisableWhileOpen != null)
        {
            for (int i = 0; i < obstaclesToDisableWhileOpen.Count; i++)
            {
                NavMeshObstacle obstacle = obstaclesToDisableWhileOpen[i];
                if (obstacle != null)
                    obstacle.enabled = !open;
            }
        }

        if (collidersToDisableWhileOpen != null)
        {
            for (int i = 0; i < collidersToDisableWhileOpen.Count; i++)
            {
                Collider blocker = collidersToDisableWhileOpen[i];
                if (blocker != null)
                    blocker.enabled = !open;
            }
        }
    }

    void OnDrawGizmosSelected()
    {
        RefreshActivationPoints();
        Gizmos.color = new Color(0.2f, 0.8f, 1f, 0.85f);

        if (_resolvedActivationPoints.Count == 0)
        {
            Gizmos.DrawWireSphere(transform.position, openDistance);
            Gizmos.DrawWireSphere(transform.position, closeDistance);
            return;
        }

        for (int i = 0; i < _resolvedActivationPoints.Count; i++)
        {
            Transform point = _resolvedActivationPoints[i];
            if (point == null)
                continue;

            Gizmos.DrawWireSphere(point.position, openDistance);
            Gizmos.DrawLine(transform.position, point.position);
        }
    }
}
