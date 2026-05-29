// Controlled vocabulary for what kind of semantic place a ZoneVolume is.
// Serialized to lowercase string in the snapshot payload so the Python
// agent can read it without enum-to-int mapping.

public enum ZoneType
{
    District,   // broad named area: Harbor, Market
    Water,      // sea, river, pond, canal
    Path,       // walkable route: boardwalk, alley, shore path, dock walkway
    Vessel,     // boat, raft, barge — a platform that may move
    Building,   // interior of a roofed structure
    Courtyard,  // exterior space enclosed by walls, attached to a building
    Yard,       // open ground attached to a building, not enclosed
    Surface,    // specific named surface within a larger zone: Deck, Counter, Rooftop
}
