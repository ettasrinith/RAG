from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from api.errors import not_found, already_exists
from api.schemas.collections import CollectionCreate, CollectionUpdate, CollectionResponse
from core.registry.models import CollectionModel, IndexJobModel


class CollectionService:
    def __init__(self, session: Session):
        self.session = session

    def list(self) -> list[CollectionResponse]:
        models = self.session.query(CollectionModel).order_by(CollectionModel.created_at.desc()).all()
        return [_model_to_response(m) for m in models]

    def get(self, collection_id: str) -> CollectionResponse:
        model = self.session.query(CollectionModel).filter(CollectionModel.id == collection_id).first()
        if not model:
            raise not_found("Collection", collection_id)
        return _model_to_response(model)

    def create(self, req: CollectionCreate) -> CollectionResponse:
        existing = self.session.query(CollectionModel).filter(CollectionModel.name == req.name).first()
        if existing:
            raise already_exists("Collection", req.name)
        model = CollectionModel(
            name=req.name,
            kind=req.kind,
            source_config=req.source_config,
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return _model_to_response(model)

    def update(self, collection_id: str, req: CollectionUpdate) -> CollectionResponse:
        model = self.session.query(CollectionModel).filter(CollectionModel.id == collection_id).first()
        if not model:
            raise not_found("Collection", collection_id)
        if req.name is not None:
            model.name = req.name
        if req.kind is not None:
            model.kind = req.kind
        if req.source_config is not None:
            model.source_config = req.source_config
        model.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        self.session.refresh(model)
        return _model_to_response(model)

    def delete(self, collection_id: str) -> None:
        model = self.session.query(CollectionModel).filter(CollectionModel.id == collection_id).first()
        if not model:
            raise not_found("Collection", collection_id)
        self.session.delete(model)
        self.session.commit()

    def get_stats(self) -> list[dict]:
        models = self.session.query(CollectionModel).all()
        return [
            {
                "id": m.id,
                "name": m.name,
                "doc_count": m.doc_count,
                "last_indexed_at": m.last_indexed_at,
                "status": m.status,
            }
            for m in models
        ]


def _model_to_response(m: CollectionModel) -> CollectionResponse:
    return CollectionResponse(
        id=m.id,
        name=m.name,
        kind=m.kind,
        source_config=m.source_config or {},
        doc_count=m.doc_count or 0,
        last_indexed_at=m.last_indexed_at,
        status=m.status or "idle",
        created_at=m.created_at,
        updated_at=m.updated_at,
    )
