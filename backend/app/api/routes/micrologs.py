"""
/micrologs routes — thin controllers.

Pattern: Route → Service → Repository → DB
Routes should contain NO business logic.
"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query

from app.api.deps import RedisDep, SettingsDep, SupabaseDep
from app.models.microlog import MicrologCreate, MicrologInDB, MicrologRead
from app.repositories.microlog_repo import MicrologRepository
from app.services.embedding import EmbeddingService
from app.workers.agent_tasks import agent_thinking_task

router = APIRouter(prefix="/micrologs", tags=["micrologs"])


@router.get("/{user_id}", response_model=list[MicrologRead])
async def list_logs(
    user_id: UUID,
    db: SupabaseDep,
    count: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Fetch a user's recent microlog entries."""
    repo = MicrologRepository(db)
    return repo.get_by_user(str(user_id), limit=count, offset=offset)


@router.post("/", response_model=MicrologRead, status_code=201)
async def create_log(
    body: MicrologCreate,
    background_tasks: BackgroundTasks,
    db: SupabaseDep,
    redis: RedisDep,
    settings: SettingsDep,
):
    """Create a microlog entry, embed its content, and kick off agent thinking."""
    # 1. Embed
    embedding_svc = EmbeddingService(settings)
    vector = embedding_svc.embed_text(body.content)

    # 2. Persist
    enriched = MicrologInDB(**body.model_dump(), embedding=vector or None)
    repo = MicrologRepository(db)
    row = repo.create(enriched)

    # 3. Background agent task
    background_tasks.add_task(
        agent_thinking_task,
        log_id=row["id"],
        user_id=str(body.user_id),
        content=body.content,
        supabase=db,
        redis=redis,
        settings=settings,
    )

    return row
