from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import AgentTickServiceDep, verify_api_key
from app.models import TickJobResponse, TickPayload, TickSubmitResponse

router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(verify_api_key)])


@router.post(
    "/tick/{creature_id}",
    response_model=TickSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def agent_tick(
    creature_id: str,
    payload: TickPayload,
    service: AgentTickServiceDep,
) -> TickSubmitResponse:
    """
    The game would called this endpoint for action. It delegate the request to the service
    that has job/work pattern with redis
    """
    try:
        result = await service.submit_tick(
            creature_id,
            payload.model_dump(by_alias=True),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error: {type(exc).__name__} - {exc}",
        ) from exc

    return TickSubmitResponse(
        job_id=result["job_id"],
        creature_id=result["creature_id"],
        request_id=result.get("request_id", ""),
        status=result.get("status"),
        queue_depth=result.get("queue_depth", 0),
    )


@router.get("/tick/jobs/{job_id}", response_model=TickJobResponse)
async def get_tick_job(job_id: str, service: AgentTickServiceDep) -> TickJobResponse:
    job = await service.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tick job not found: {job_id}",
        )
    return TickJobResponse(
        job_id=job["job_id"],
        creature_id=job.get("creature_id", ""),
        request_id=job.get("request_id", ""),
        status=job.get("status", "pending"),
        tick=job.get("tick"),
        action=job.get("action_result"),
        reasoning=job.get("reasoning"),
        error=job.get("error"),
    )
