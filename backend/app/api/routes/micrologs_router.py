"""
/micrologs routes — thin controllers.

Pattern: Route → Service → Repository → DB
Routes should contain NO business logic.
"""

from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import SettingsDep, SupabaseDep
from app.models.microlog import MicrologCreate, MicrologInDB, MicrologRead
from app.repositories.microlog_repo import MicrologRepository
from app.services.embedding_service import EmbeddingService

router = APIRouter(prefix="/micrologs", tags=["micrologs"])


@router.get("/{user_id}", response_model=list[MicrologRead])
async def list_log(
    user_id: UUID,
    db: SupabaseDep,
    count: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Fetch a user's recent microlog entries."""
    repo = MicrologRepository(db)
    return repo.get_by_user(str(user_id), limit=count, offset=offset)


@router.post("/", status_code=201, response_model=MicrologRead)
async def create_log(
    body: MicrologCreate,
    db: SupabaseDep,
    settings: SettingsDep,
):
    """Create a microlog entry and embed its content."""
    embedding_svc = EmbeddingService(settings)
    vector = embedding_svc.embed_text(body.content)

    enriched = MicrologInDB(**body.model_dump(), embedding=vector or None)
    repo = MicrologRepository(db)
    return repo.create(enriched)