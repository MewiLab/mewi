using System;
using System.Collections.Generic;
using UnityEngine;

[DisallowMultipleComponent]
public sealed class KeyboardProximityCatTargetSource : MonoBehaviour, IPlayerTargetSource
{
    [Header("Player")]
    [SerializeField] Transform playerRoot;
    [SerializeField] CreatureBlackboard playerBlackboard;

    [Header("Acquisition")]
    [SerializeField, Min(0.1f)] float acquisitionRadiusMeters = 3.5f;
    [SerializeField, Range(-1f, 1f)] float minimumFacingDot = 0.35f;
    [SerializeField, Min(0f)] float distanceWeight = 0.35f;
    [SerializeField, Min(0f)] float facingWeight = 1.0f;
    [SerializeField] bool requireEntityCatTag;
    [SerializeField] bool rememberTargetOnPlayerBlackboard = true;

    readonly List<PlayerCatTargetLock> _candidates = new List<PlayerCatTargetLock>();
    PlayerCatTargetLock _current;
    int _currentIndex = -1;

    public float AcquisitionRadiusMeters => acquisitionRadiusMeters;
    public float MinimumFacingDot => minimumFacingDot;
    public IReadOnlyList<PlayerCatTargetLock> CurrentCandidates => _candidates;

    void Awake()
    {
        ResolvePlayer();
    }

    void OnValidate()
    {
        acquisitionRadiusMeters = Mathf.Max(0.1f, acquisitionRadiusMeters);
    }

    public bool TryAcquireNearest(out PlayerCatTargetLock target)
    {
        RebuildCandidates();
        if (_candidates.Count == 0)
        {
            Clear();
            target = default;
            return false;
        }

        _currentIndex = 0;
        _current = _candidates[0];
        RememberCurrentTarget();
        target = _current;
        return true;
    }

    public bool TryCycle(int direction, out PlayerCatTargetLock target)
    {
        RebuildCandidates();
        if (_candidates.Count == 0)
        {
            Clear();
            target = default;
            return false;
        }

        if (_currentIndex < 0)
        {
            string currentId = _current.TargetId;
            _currentIndex = FindCandidateIndex(currentId);
        }

        int step = direction < 0 ? -1 : 1;
        _currentIndex = _currentIndex < 0
            ? 0
            : PositiveModulo(_currentIndex + step, _candidates.Count);

        _current = _candidates[_currentIndex];
        RememberCurrentTarget();
        target = _current;
        return true;
    }

    public bool TryGetCurrent(out PlayerCatTargetLock target)
    {
        if (!_current.IsValid || !IsCandidateStillValid(_current))
        {
            target = default;
            return false;
        }

        target = _current;
        return true;
    }

    public void Clear()
    {
        _current = default;
        _currentIndex = -1;
    }

    public void RebuildCandidates()
    {
        ResolvePlayer();
        _candidates.Clear();

        if (playerRoot == null)
            return;

        CreatureBlackboard[] boards = FindObjectsByType<CreatureBlackboard>(
            FindObjectsInactive.Exclude,
            FindObjectsSortMode.None);

        Vector3 playerPosition = playerRoot.position;
        Vector3 playerForward = playerRoot.forward;
        if (playerForward.sqrMagnitude <= 0.0001f)
            playerForward = Vector3.forward;
        playerForward.Normalize();

        for (int i = 0; i < boards.Length; i++)
        {
            CreatureBlackboard board = boards[i];
            if (!IsValidNpcCat(board))
                continue;

            Vector3 toTarget = board.transform.position - playerPosition;
            float distance = toTarget.magnitude;
            if (distance > acquisitionRadiusMeters)
                continue;

            Vector3 direction = distance > 0.001f ? toTarget / distance : playerForward;
            float facingDot = Vector3.Dot(playerForward, direction);
            if (facingDot < minimumFacingDot)
                continue;

            string targetId = ResolveTargetId(board);
            if (string.IsNullOrWhiteSpace(targetId))
                continue;

            _candidates.Add(new PlayerCatTargetLock(
                board,
                targetId,
                distance,
                facingDot,
                1.0f));
        }

        _candidates.Sort(CompareLocks);
        if (_current.IsValid)
            _currentIndex = FindCandidateIndex(_current.TargetId);
    }

    bool IsCandidateStillValid(PlayerCatTargetLock target)
    {
        if (!target.IsValid)
            return false;

        RebuildCandidates();
        int index = FindCandidateIndex(target.TargetId);
        if (index < 0)
            return false;

        _currentIndex = index;
        _current = _candidates[index];
        return true;
    }

    bool IsValidNpcCat(CreatureBlackboard board)
    {
        if (board == null)
            return false;
        if (playerBlackboard != null && board == playerBlackboard)
            return false;
        if (playerRoot != null && board.transform.root == playerRoot.root)
            return false;

        SmartObject smart = FindOnTarget<SmartObject>(board.transform);
        bool isPlayer =
            (smart != null && (smart.HasTag("entity.player") || smart.HasTag("player"))) ||
            Contains(board.transform.root.name, "player");
        if (isPlayer)
            return false;

        bool isCat = smart == null || smart.HasTag("entity.cat") || smart.HasTag("cat") || Contains(board.transform.root.name, "cat");
        return !requireEntityCatTag || isCat;
    }

    void RememberCurrentTarget()
    {
        if (!rememberTargetOnPlayerBlackboard || playerBlackboard == null || !_current.IsValid)
            return;

        playerBlackboard.RememberPerceivedTarget(
            _current.TargetId,
            _current.TargetCat.transform,
            _current.TargetCat.transform.position);
    }

    int CompareLocks(PlayerCatTargetLock a, PlayerCatTargetLock b)
    {
        float aScore = Score(a);
        float bScore = Score(b);
        int byScore = bScore.CompareTo(aScore);
        if (byScore != 0)
            return byScore;
        return string.Compare(a.TargetId, b.TargetId, StringComparison.OrdinalIgnoreCase);
    }

    float Score(PlayerCatTargetLock target)
    {
        float normalizedDistance = acquisitionRadiusMeters > 0f
            ? Mathf.Clamp01(target.DistanceMeters / acquisitionRadiusMeters)
            : 1f;
        return target.FacingDot * facingWeight - normalizedDistance * distanceWeight;
    }

    int FindCandidateIndex(string targetId)
    {
        if (string.IsNullOrWhiteSpace(targetId))
            return -1;

        for (int i = 0; i < _candidates.Count; i++)
        {
            if (string.Equals(_candidates[i].TargetId, targetId, StringComparison.OrdinalIgnoreCase))
                return i;
        }

        return -1;
    }

    string ResolveTargetId(CreatureBlackboard board)
    {
        if (board == null)
            return "";
        if (!string.IsNullOrWhiteSpace(board.CreatureId))
            return board.CreatureId.Trim().ToLowerInvariant();

        SmartObject smart = FindOnTarget<SmartObject>(board.transform);
        if (smart != null && !string.IsNullOrWhiteSpace(smart.Label))
            return smart.Label.Trim().ToLowerInvariant();

        return board.transform.root.name.Trim().ToLowerInvariant();
    }

    void ResolvePlayer()
    {
        if (playerRoot == null)
            playerRoot = transform;
        if (playerBlackboard == null && playerRoot != null)
            playerBlackboard = playerRoot.GetComponent<CreatureBlackboard>()
                ?? playerRoot.GetComponentInParent<CreatureBlackboard>()
                ?? playerRoot.GetComponentInChildren<CreatureBlackboard>();
    }

    static int PositiveModulo(int value, int modulo)
    {
        if (modulo <= 0) return 0;
        int result = value % modulo;
        return result < 0 ? result + modulo : result;
    }

    static bool Contains(string value, string needle)
        => !string.IsNullOrWhiteSpace(value) &&
           !string.IsNullOrWhiteSpace(needle) &&
           value.IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0;

    static T FindOnTarget<T>(Transform target) where T : Component
    {
        if (target == null)
            return null;
        return target.GetComponent<T>()
            ?? target.GetComponentInParent<T>()
            ?? target.GetComponentInChildren<T>();
    }
}
