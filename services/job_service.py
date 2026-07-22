from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from api.errors import not_found
from api.schemas.jobs import JobResponse
from core.registry.models import IndexJobModel


class JobService:
    def __init__(self, session: Session):
        self.session = session

    def list(self, collection_id: str | None = None) -> list[JobResponse]:
        q = self.session.query(IndexJobModel)
        if collection_id:
            q = q.filter(IndexJobModel.collection_id == collection_id)
        q = q.order_by(IndexJobModel.created_at.desc()).limit(50)
        return [_job_to_response(j) for j in q.all()]

    def get(self, job_id: str) -> JobResponse:
        model = self.session.query(IndexJobModel).filter(IndexJobModel.id == job_id).first()
        if not model:
            raise not_found("IndexJob", job_id)
        return _job_to_response(model)

    def cancel(self, job_id: str) -> JobResponse:
        model = self.session.query(IndexJobModel).filter(IndexJobModel.id == job_id).first()
        if not model:
            raise not_found("IndexJob", job_id)
        model.state = "cancelled"
        model.finished_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(model)
        return _job_to_response(model)

    def create(self, collection_id: str, items_total: int = 0) -> IndexJobModel:
        model = IndexJobModel(
            collection_id=collection_id,
            state="queued",
            items_total=items_total,
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return model

    def update_progress(self, job_id: str, items_done: int, items_total: int | None = None, state: str | None = None) -> IndexJobModel:
        model = self.session.query(IndexJobModel).filter(IndexJobModel.id == job_id).first()
        if not model:
            raise not_found("IndexJob", job_id)
        model.items_done = items_done
        if items_total is not None:
            model.items_total = items_total
        if model.items_total > 0:
            model.progress = round(model.items_done / model.items_total * 100, 1)
        if state:
            model.state = state
            if state in ("done", "failed", "cancelled"):
                model.finished_at = datetime.now(timezone.utc)
        model.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(model)
        return model


def _job_to_response(j: IndexJobModel) -> JobResponse:
    return JobResponse(
        id=j.id,
        collection_id=j.collection_id,
        state=j.state or "queued",
        items_done=j.items_done or 0,
        items_total=j.items_total or 0,
        progress=j.progress or 0.0,
        error_message=j.error_message,
        created_at=j.created_at,
        updated_at=j.updated_at,
        finished_at=j.finished_at,
    )
