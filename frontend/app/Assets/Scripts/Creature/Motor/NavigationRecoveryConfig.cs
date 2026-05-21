using UnityEngine;

/// <summary>
/// Tunables for <see cref="NavigationWatchdog"/>. Lives in the adapter Inspector
/// so designers can tweak per-creature without touching code.
/// </summary>
[System.Serializable]
public class NavigationRecoveryConfig
{
    [Tooltip("How often the watchdog samples progress (seconds).")]
    public float progressCheckInterval = 0.25f;

    [Tooltip("Horizontal meters the animal must cover per check to count as 'making progress'.")]
    public float minProgressMeters = 0.15f;

    [Tooltip("Stuck this long without progress → try to repath.")]
    public float repathDelaySeconds = 2f;

    [Tooltip("Maximum repath attempts before warping.")]
    public int maxRepathAttempts = 2;

    [Tooltip("Hard ceiling: navigation must finish within this many seconds or the watchdog warps.")]
    public float hardTimeoutSeconds = 12f;

    [Tooltip("NavMesh.SamplePosition radius when projecting the warp landing point.")]
    public float warpNavMeshSampleRadius = 2f;
}
