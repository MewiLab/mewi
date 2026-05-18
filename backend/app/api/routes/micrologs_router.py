from uuid import UUID
from fastapi import APIRouter, Depends, Query
from app.api.deps import SettingsDep, SupabaseDep, verify_api_key
from app.models.microlog import MicrologCreate, MicrologRead
from app.repositories.microlog_repo import MicrologRepository
from app.services.microlog_service import MicrologService

router = APIRouter(prefix="/micrologs", tags=["micrologs"], dependencies=[Depends(verify_api_key)])


@router.get("/{user_id}", response_model=list[MicrologRead])
async def list_logs(
    user_id: UUID,
    db: SupabaseDep,
    count: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    repo = MicrologRepository(db)
    return repo.get_by_user(str(user_id), limit=count, offset=offset)


@router.post("/", status_code=201, response_model=MicrologRead)
async def create_log(
    body: MicrologCreate,
    db: SupabaseDep,
    settings: SettingsDep,
):
    svc = MicrologService(settings=settings, supabase=db)
    return svc.create(body)