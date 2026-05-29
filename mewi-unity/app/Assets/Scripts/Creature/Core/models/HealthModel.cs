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
    [Range(0f, 1f)] public float fullness = 0.9f;
    [Range(0f, 1f)] public float blood = 0.2f;

    public float FoodNeed => 1f - fullness;

    public void Clamp()
    {
        water  = Mathf.Clamp01(water);
        fullness = Mathf.Clamp01(fullness);
        blood  = Mathf.Clamp01(blood);
    }

    public void AddFullness(float amount)
    {
        fullness = Mathf.Clamp01(fullness + Mathf.Max(0f, amount));
    }

    public void DecayFullness(float perSecond, float deltaTime)
    {
        if (perSecond <= 0f || deltaTime <= 0f) return;
        fullness = Mathf.Clamp01(fullness - deltaTime * perSecond);
    }

    /// <summary>For LLM prompt or debug display.</summary>
    public override string ToString()
    {
        return $"water:{water:F2} fullness:{fullness:F2} blood:{blood:F2}";
    }
}
