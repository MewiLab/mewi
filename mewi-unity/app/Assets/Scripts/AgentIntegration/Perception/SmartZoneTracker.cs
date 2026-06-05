using UnityEngine;

/// <summary>
/// Deprecated compatibility component. ZoneScanner is now the only spatial
/// source of truth and writes the current zone hierarchy to CreatureBlackboard.
/// Keep this class so older prefabs with the component do not produce missing
/// script entries; it intentionally does nothing.
/// </summary>
[System.Obsolete("Use ZoneScanner instead. This component is a no-op.")]
public class SmartZoneTracker : MonoBehaviour
{
    public void Init(CreatureBlackboard board) { }
}
