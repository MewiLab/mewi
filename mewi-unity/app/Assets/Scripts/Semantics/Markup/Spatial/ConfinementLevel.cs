// Authored on every ZoneVolume — "how enclosed does this place feel?".
// Used by reason node to bias behaviour: confined = wary in unfamiliar zones,
// safe in familiar ones.

public enum ConfinementLevel
{
    Open,      // outdoor, no walls — Harbor, Market square
    Semi,      // partial cover — Boat deck, awning area
    Confined,  // fully enclosed — Cabin, alley
}
