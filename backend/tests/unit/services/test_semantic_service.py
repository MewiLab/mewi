"""
Unit tests for SemanticService.

Every test exercises a single invariant so failures are immediately actionable.
No mocks needed — SemanticService is stateless and pure.
"""

import pytest

from app.services.semantic_service import SemanticService


@pytest.fixture
def svc() -> SemanticService:
    return SemanticService()


# ── Snapshot factory ─────────────────────────────────────────────────────────

def _snap(
    action: str = "idle",
    fear: float = 0.0,
    trust: float = 0.0,
    curiosity: float = 0.5,
    social: float = 0.0,
    energy: float = 1.0,
    hunger: float = 0.0,
    entities: list | None = None,
    request_id: str = "req-001",
) -> dict:
    """Minimal Unity-schema snapshot matching TickPayload.model_dump(by_alias=True)."""
    return {
        "requestId": request_id,
        "self": {
            "location":       {"x": 0.0, "y": 0.0, "z": 0.0},
            "current_action": action,
        },
        "mood": {
            "fear":      fear,
            "trust":     trust,
            "curiosity": curiosity,
            "social":    social,
            "energy":    energy,
        },
        "health": {"hunger": hunger},
        "entities": entities or [],
    }


# ── _label ────────────────────────────────────────────────────────────────────

class TestLabel:
    def test_zero_is_low(self, svc):
        assert svc._label(0.0) == "low"

    def test_below_threshold_is_low(self, svc):
        assert svc._label(0.29) == "low"

    def test_lower_boundary_is_moderate(self, svc):
        assert svc._label(0.3) == "moderate"

    def test_midpoint_is_moderate(self, svc):
        assert svc._label(0.5) == "moderate"

    def test_upper_boundary_is_moderate(self, svc):
        assert svc._label(0.7) == "moderate"

    def test_above_boundary_is_high(self, svc):
        assert svc._label(0.71) == "high"


class TestLocationContext:
    def test_zone_string_location_is_used_in_summary_header(self, svc):
        summary = svc.generate_summary(
            [_snap()],
            location="Harbor,Dock",
            timestamp="2026-05-18T00:00:00+00:00",
        )

        assert summary.startswith("[2026-05-18T00:00:00+00:00 @ Harbor,Dock]")

    def test_one_is_high(self, svc):
        assert svc._label(1.0) == "high"


# ── _trend ────────────────────────────────────────────────────────────────────

class TestTrend:
    def test_stable_returns_none(self, svc):
        assert svc._trend("Fear", 0.1, 0.2) is None

    def test_stable_across_entire_moderate_band(self, svc):
        assert svc._trend("Energy", 0.3, 0.7) is None

    def test_rising_low_to_high(self, svc):
        assert svc._trend("Hunger", 0.1, 0.9) == "Hunger went from low to high"

    def test_rising_low_to_moderate(self, svc):
        assert svc._trend("Fear", 0.1, 0.5) == "Fear went from low to moderate"

    def test_falling_high_to_low(self, svc):
        assert svc._trend("Energy", 0.9, 0.1) == "Energy went from high to low"

    def test_falling_moderate_to_low(self, svc):
        assert svc._trend("Trust", 0.5, 0.2) == "Trust went from moderate to low"


# ── generate_summary ──────────────────────────────────────────────────────────

class TestGenerateSummary:

    # ── Guard cases ───────────────────────────────────────────────────────────

    def test_empty_list_returns_sentinel(self, svc):
        assert svc.generate_summary([]) == "No perception data available."

    def test_returns_a_string(self, svc):
        assert isinstance(svc.generate_summary([_snap()]), str)

    def test_single_snapshot_does_not_raise(self, svc):
        svc.generate_summary([_snap(action="stretching", fear=0.9, hunger=0.8)])

    # ── Action ────────────────────────────────────────────────────────────────

    def test_action_from_last_snapshot_appears(self, svc):
        snaps = [_snap(action="sleeping"), _snap(action="chasing")]
        assert "chasing" in svc.generate_summary(snaps)

    def test_missing_current_action_defaults_to_resting(self, svc):
        snap = {"self": {}, "mood": {}, "health": {}, "entities": []}
        result = svc.generate_summary([snap])
        assert "resting" in result

    # ── Mood words ────────────────────────────────────────────────────────────

    def test_high_trust_adds_trusting(self, svc):
        assert "trusting" in svc.generate_summary([_snap(trust=0.9)])

    def test_high_fear_adds_fearful(self, svc):
        assert "fearful" in svc.generate_summary([_snap(fear=0.9)])

    def test_high_curiosity_adds_curious(self, svc):
        assert "curious" in svc.generate_summary([_snap(curiosity=0.9)])

    def test_high_social_adds_social(self, svc):
        assert "social" in svc.generate_summary([_snap(social=0.9)])

    def test_low_energy_adds_tired(self, svc):
        assert "tired" in svc.generate_summary([_snap(energy=0.1)])

    def test_all_default_values_gives_calm(self, svc):
        assert "calm" in svc.generate_summary([_snap()])

    def test_multiple_mood_words_joined(self, svc):
        result = svc.generate_summary([_snap(trust=0.9, curiosity=0.9)])
        assert "trusting" in result
        assert "curious" in result

    # ── Trends ────────────────────────────────────────────────────────────────

    def test_hunger_trend_when_rises(self, svc):
        result = svc.generate_summary([_snap(hunger=0.1), _snap(hunger=0.9)])
        assert "Hunger" in result
        assert "low to high" in result

    def test_energy_trend_when_falls(self, svc):
        result = svc.generate_summary([_snap(energy=0.9), _snap(energy=0.1)])
        assert "Energy" in result
        assert "high to low" in result

    def test_no_trend_sentence_when_single_snapshot(self, svc):
        result = svc.generate_summary([_snap(fear=0.5, energy=0.5)])
        assert "went from" not in result

    def test_no_trend_sentence_when_stable(self, svc):
        snaps = [_snap(hunger=0.1), _snap(hunger=0.2)]  # both "low"
        assert "went from" not in svc.generate_summary(snaps)

    # ── Entities ──────────────────────────────────────────────────────────────

    def test_entity_tags_appear_in_output(self, svc):
        snap = _snap(entities=[
            {"id": "e1", "tags": ["lantern", "wood"], "distance": 2.0, "direction": "north"}
        ])
        result = svc.generate_summary([snap])
        assert "lantern" in result
        assert "wood" in result

    def test_duplicate_tags_across_snapshots_deduplicated(self, svc):
        snaps = [
            _snap(entities=[{"id": "e1", "tags": ["lantern"], "distance": 1.0, "direction": "n"}]),
            _snap(entities=[{"id": "e1", "tags": ["lantern"], "distance": 1.0, "direction": "n"}]),
            _snap(entities=[{"id": "e2", "tags": ["box"],     "distance": 5.0, "direction": "s"}]),
        ]
        result = svc.generate_summary(snaps)
        assert result.count("lantern") == 1
        assert "box" in result

    def test_entity_id_is_used_when_tags_are_absent(self, svc):
        snap = _snap(entities=[{"id": "e1", "distance": 2.0, "direction": "n"}])
        result = svc.generate_summary([snap])
        assert "e1" in result

    def test_feelings_summary_appears_in_output(self, svc):
        snap = _snap()
        snap["feelings"] = {"summary": "It smelled a distant bonfire"}
        result = svc.generate_summary([snap])
        assert "bonfire" in result

    def test_feelings_arrays_are_described_in_output(self, svc):
        snap = _snap()
        snap["feelings"] = {
            "smells": ["smoke"],
            "sounds": ["waterfall"],
            "signals": ["warmth"]
        }
        result = svc.generate_summary([snap])
        assert "smelled smoke" in result
        assert "heard waterfall" in result
        assert "detected warmth" in result

    def test_zone_labels_are_included_when_present(self, svc):
        snap = _snap()
        snap["spatial_context"] = {"zones": [{"id": "market", "type": "area"}]}
        result = svc.generate_summary([snap])
        assert "market" in result

    def test_zone_details_are_included_when_present(self, svc):
        snap = _snap()
        snap["spatial_context"] = {
            "zones": [{"id": "dock", "type": "surface", "confinement": "Open", "surface": "wet wood"}]
        }
        result = svc.generate_summary([snap])
        assert "dock" in result
        assert "wet wood" in result

    def test_feelings_from_earlier_snapshot_are_kept_in_window(self, svc):
        first = _snap(request_id="req-001")
        first["feelings"] = {"sounds": ["sudden left near: barrel thud"]}
        last = _snap(request_id="req-002")
        result = svc.generate_summary([first, last])
        assert "barrel thud" in result

    def test_unknown_feeling_arrays_are_described(self, svc):
        snap = _snap()
        snap["feelings"] = {"textures": ["slick below contact: wet dock boards"]}
        result = svc.generate_summary([snap])
        assert "textures" in result
        assert "wet dock boards" in result

    def test_no_entities_omits_noticed_sentence(self, svc):
        assert "noticed" not in svc.generate_summary([_snap()])

    def test_empty_tags_falls_back_to_entity_id(self, svc):
        snap = _snap(entities=[{"id": "e1", "tags": [], "distance": 1.0, "direction": "n"}])
        result = svc.generate_summary([snap])
        assert "e1" in result

    # ── Robustness: missing / partial keys ───────────────────────────────────

    def test_missing_mood_key_uses_default(self, svc):
        """Snapshot with no 'mood' key must not raise."""
        snap = {"requestId": "r1", "self": {"current_action": "idle"}, "health": {}, "entities": []}
        result = svc.generate_summary([snap])
        assert isinstance(result, str) and len(result) > 0

    def test_missing_health_key_uses_default(self, svc):
        snap = {"requestId": "r1", "self": {"current_action": "idle"}, "mood": {}, "entities": []}
        result = svc.generate_summary([snap])
        assert isinstance(result, str) and len(result) > 0

    def test_completely_bare_snapshot_does_not_raise(self, svc):
        result = svc.generate_summary([{}])
        assert isinstance(result, str) and len(result) > 0

    def test_partial_mood_dict_uses_defaults(self, svc):
        """Mood dict with only 'fear' — other keys must default."""
        snap = _snap()
        snap["mood"] = {"fear": 0.9}   # trust/curiosity/social/energy absent
        result = svc.generate_summary([snap])
        assert "fearful" in result

    def test_entity_without_tags_key_falls_back_to_id(self, svc):
        snap = _snap(entities=[{"id": "e1", "distance": 2.0}])  # no "tags" key
        result = svc.generate_summary([snap])
        assert "e1" in result


class TestPromptContext:
    def test_prompt_context_translates_payload_to_high_level_meaning(self, svc):
        snap = _snap(
            action="idle",
            fear=0.2,
            trust=0.3,
            curiosity=0.5,
            social=0.4,
            energy=0.54,
            hunger=1.0,
            entities=[
                {"id": "Cat", "tags": [], "distance": 1.2, "direction": "front"},
                {"id": "SM_Boat_1_01", "tags": ["prop.boat"], "distance": 3.8, "direction": "front_left"},
                {"id": "SM_Lantern_2_01", "tags": ["prop.lantern"], "distance": 3.8, "direction": "front_left"},
            ],
        )
        snap["agent_id"] = "cat"
        snap["self"]["location"] = "Bamboo_Boardwalk"
        snap["spatial_context"] = {
            "zones": [
                {"id": "Harbor", "type": "district", "confinement": "", "surface": ""},
                {"id": "Bamboo_Boardwalk", "type": "path", "confinement": "Semi", "surface": "Wood"},
            ]
        }

        context = svc.build_prompt_context(snap)

        assert "Bamboo Boardwalk" in context["situation"]
        assert "food is urgent" in context["body_state"]
        assert any("boat" in target and "SM_Boat_1_01" in target for target in context["relevant_targets"])
        assert any("lantern" in target for target in context["relevant_targets"])
        assert not any("Cat;" in target or "target: Cat" in target for target in context["relevant_targets"])
        assert "3.8" not in " ".join(context["relevant_targets"])
        assert "front_left" not in " ".join(context["relevant_targets"])
