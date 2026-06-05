from types import SimpleNamespace

import pytest

from app.repositories.mem0_memory_store import (
    _build_config,
    _validate_config_for_installed_mem0,
)


def _settings():
    return (
        SimpleNamespace(model="gpt-4o-mini", api_key="llm-key", base_url=""),
        SimpleNamespace(model="text-embedding-3-small", api_key="", base_url=""),
        SimpleNamespace(
            neo4j_url="bolt://localhost:7687",
            neo4j_username="neo4j",
            neo4j_password="secret",
            pgvector_dsn="postgresql://example",
        ),
    )


def test_mem0_config_uses_pgvector_connection_string() -> None:
    llm, embedding, memory = _settings()

    config = _build_config(llm, embedding, memory)

    assert config["vector_store"]["provider"] == "pgvector"
    assert config["vector_store"]["config"]["connection_string"] == "postgresql://example"
    assert config["vector_store"]["config"]["collection_name"] == "mewi_memories"
    assert config["embedder"]["config"]["api_key"] == "llm-key"


def test_mem0_config_drops_graph_store_when_installed_version_does_not_support_it(
    caplog,
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("MEM0_DIR", str(tmp_path / "mem0"))
    pytest.importorskip("mem0")
    from mem0.configs.base import MemoryConfig

    llm, embedding, memory = _settings()
    config = _build_config(llm, embedding, memory)

    accepted = _validate_config_for_installed_mem0(config, MemoryConfig)

    if "graph_store" not in MemoryConfig.model_fields:
        assert "graph_store" not in accepted
        assert "no graph_store field" in caplog.text
    else:
        assert accepted["graph_store"]["provider"] == "neo4j"
