using UnityEngine;

/// <summary>
/// The cat's slow-changing internal state.
/// Written by [Not yet defined]
/// All values 0–1.
/// </summary>
[System.Serializable]
public class HealthModel
{
    [Range(0f, 1f)] public float water = 0.3f; 
    [Range(0f, 1f)] public float hunger  = 0.1f;
    [Range(0f, 1f)] public float blood = 0.2f;

    public void Clamp()
    {
        water  = Mathf.Clamp01(water);
        hunger = Mathf.Clamp01(hunger);
        blood  = Mathf.Clamp01(blood);
    }

    /// <summary>For LLM prompt or debug display.</summary>
    public override string ToString()
    {
        return $"water:{water:F2} food:{hunger:F2} blood:{blood:F2}";
    }
}
