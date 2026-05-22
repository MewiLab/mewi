from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
PERSONA_DIR = PROMPTS_DIR / "persona"
DEFAULT_PERSONA = "cat"
DEFAULT_PERSONA_KEY = "default"


def load_persona(name: str = DEFAULT_PERSONA) -> str:
    """Load a persona prompt by name from app/agent/prompts/persona."""
    safe_name = _safe_prompt_name(name or DEFAULT_PERSONA)
    path = PERSONA_DIR / f"{safe_name}.md"
    if not path.exists():
        available = ", ".join(list_personas()) or "(none)"
        raise FileNotFoundError(f"Persona prompt not found: {safe_name!r}. Available: {available}")
    return path.read_text(encoding="utf-8").strip()


def load_persona_map(spec: str = "", default_persona: str = DEFAULT_PERSONA) -> dict[str, str]:
    """
    Load a creature_id -> persona text mapping.

    Spec format:
        default:cat,mewi:cat,sora:sora,miso:miso

    Unknown creature IDs should use the returned "default" entry.
    """
    mapping: dict[str, str] = {DEFAULT_PERSONA_KEY: load_persona(default_persona)}
    for raw_entry in (spec or "").split(","):
        entry = raw_entry.strip()
        if not entry:
            continue

        if ":" in entry:
            creature_id, persona_name = entry.split(":", 1)
        else:
            creature_id = entry
            persona_name = entry

        key = normalize_creature_id(creature_id)
        if not key:
            continue
        mapping[key] = load_persona(persona_name.strip() or default_persona)

    return mapping


def normalize_creature_id(creature_id: str) -> str:
    return (creature_id or "").strip().lower().replace(" ", "_")


def list_personas() -> list[str]:
    if not PERSONA_DIR.exists():
        return []
    return sorted(path.stem for path in PERSONA_DIR.glob("*.md") if path.is_file())


class PersonaManager:
    """Resolves persona prompt text for a given creature_id.

    Owns the creature_id -> persona text mapping plus the default fallback so
    consumers (the tick worker, the runtime) do not each re-implement the
    normalize-and-lookup pattern.
    """

    def __init__(self, personas: dict[str, str] | None = None) -> None:
        self._personas = dict(personas or {})
        self._default = self._personas.get(DEFAULT_PERSONA_KEY, "")

    @classmethod
    def from_spec(
        cls,
        spec: str = "",
        *,
        default_persona: str = DEFAULT_PERSONA,
    ) -> "PersonaManager":
        return cls(load_persona_map(spec, default_persona=default_persona))

    def for_creature(self, creature_id: str) -> str:
        return self._personas.get(self.key_for(creature_id), self._default)

    @staticmethod
    def key_for(creature_id: str) -> str:
        return normalize_creature_id(creature_id)

    def keys(self) -> list[str]:
        return sorted(self._personas.keys())

    def has_default(self) -> bool:
        return DEFAULT_PERSONA_KEY in self._personas


def _safe_prompt_name(name: str) -> str:
    value = name.strip()
    if not value:
        return DEFAULT_PERSONA
    if any(part in value for part in ("/", "\\", "..")):
        raise ValueError(f"Invalid prompt name: {name!r}")
    return value
