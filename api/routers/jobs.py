from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.deps import get_job_service
from api.schemas.jobs import JobResponse
from services.job_service import JobService

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    collection_id: str | None = Query(default=None),
    svc: JobService = Depends(get_job_service),
):
    return {"data": svc.list(collection_id)}


@router.get("/{job_id}")
def get_job(job_id: str, svc: JobService = Depends(get_job_service)):
    return svc.get(job_id)


@router.post("/{job_id}:cancel")
def cancel_job(job_id: str, svc: JobService = Depends(get_job_service)):
    return svc.cancel(job_id)
