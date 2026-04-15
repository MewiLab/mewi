## ADR 006: Migration to NCKU AIC Gemma 3 and Background Task Optimization

**Status:** Accepted  
**Date: 2026-04-06**

### Context
- The project migrated from OpenAI to **NCKU AIC Gemma 3 27B** via **Ollama protocol**.
- Fixed background worker (`agent_tasks.py`) issues by enforcing `.compile()` on the StateGraph.

### Decision
1. Switched `ChatOpenAI` to `ChatOllama` for compatibility.
2. Decoupled configuration into `.env` (managed by Pydantic).
3. Updated `tests/unit/api/upload.py` to support `201 Created` status codes.

### Consequences
- **Pros**: High-parameter model (27B) with zero API cost.
- **Note**: Development requires an active **NCKU VPN** connection.v