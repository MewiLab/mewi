using UnityEngine;

/// <summary>
/// The cat's slow-changing internal state.
/// Written by PeriodicMind, read by Tactical layer to bias behavior selection.
/// All values 0–1.
/// 
/// PeriodicMind mutates MoodModel by reference — but only if it's a class. You access _board.mood and modify fields directly. 
/// If MoodModel is a struct, you're modifying a copy and nothing persists. Make sure MoodModel and HealthModel are classes, not structs.
/// </summary>
[System.Serializable]
public class MoodModel
{
    [Range(0f, 1f)] public float trust     = 0.3f;  // toward player
    [Range(0f, 1f)] public float curiosity = 0.5f;
    [Range(0f, 1f)] public float fear      = 0.2f;
    [Range(0f, 1f)] public float energy    = 0.7f;
    [Range(0f, 1f)] public float social    = 0.4f;  // desire for company

    /// <summary>Clamp all values to 0–1 after modification.</summary>
    public void Clamp()
    {
        trust     = Mathf.Clamp01(trust);
        curiosity = Mathf.Clamp01(curiosity);
        fear      = Mathf.Clamp01(fear);
        energy    = Mathf.Clamp01(energy);
        social    = Mathf.Clamp01(social);
    }

    /// <summary>For LLM prompt or debug display.</summary>
    public override string ToString()
    {
        return $"trust:{trust:F2} curiosity:{curiosity:F2} fear:{fear:F2} energy:{energy:F2} social:{social:F2}";
    }
}
