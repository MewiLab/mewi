using UnityEngine;

/// <summary>
/// Owns continuous self-status drift for one creature.
/// CreatureController only calls Tick; this class owns the decay rules.
/// </summary>
public sealed class CreatureSelfStatus
{
    const float FallbackFullnessDecayRate = 0.0000389f;
    const float FallbackEnergyDecayRate = 0.02f;
    const float MinTickInterval = 0.01f;

    CreatureBlackboard _board;
    CreatureConfig _config;

    public void Init(CreatureBlackboard board, CreatureConfig config)
    {
        _board = board;
        _config = config;
    }

    public void Tick(float deltaTime)
    {
        if (_board == null || deltaTime <= 0f)
            return;

        TickHealth(deltaTime);
        TickMood(deltaTime);
    }

    void TickHealth(float deltaTime)
    {
        float fullnessDecayRate = _config != null
            ? _config.fullnessDecayRate
            : FallbackFullnessDecayRate;

        _board.health.DecayFullness(fullnessDecayRate, deltaTime);
    }

    void TickMood(float deltaTime)
    {
        float tickInterval = Mathf.Max(MinTickInterval, _config != null ? _config.mindTickInterval : 1f);
        float fearDecayRate = _config != null ? _config.fearDecayRate : 0f;
        float trustDecayRate = _config != null ? _config.trustDecayRate : 0f;
        float energyDecayRate = _config != null ? _config.energyDecayRate : FallbackEnergyDecayRate;

        _board.mood.Decay(
            deltaTime,
            fearDecayRate / tickInterval,
            trustDecayRate / tickInterval,
            energyDecayRate / tickInterval);
    }
}
