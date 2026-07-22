from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth import verify_api_key
from api.deps import get_session, get_collection_service
from api.schemas.collections import CollectionCreate, CollectionUpdate, CollectionResponse
from services.collection_service import CollectionService

router = APIRouter(prefix="/v1/collections", tags=["collections"])


@router.get("")
def list_collections(
    svc: CollectionService = Depends(get_collection_service),
    _auth: None = Depends(verify_api_key),
):
    return {"data": svc.list()}


@router.post("", status_code=201)
def create_collection(
    req: CollectionCreate,
    svc: CollectionService = Depends(get_collection_service),
    _auth: None = Depends(verify_api_key),
):
    return svc.create(req)


@router.get("/{collection_id}")
def get_collection(
    collection_id: str,
    svc: CollectionService = Depends(get_collection_service),
    _auth: None = Depends(verify_api_key),
):
    return svc.get(collection_id)


@router.patch("/{collection_id}")
def update_collection(
    collection_id: str,
    req: CollectionUpdate,
    svc: CollectionService = Depends(get_collection_service),
    _auth: None = Depends(verify_api_key),
):
    return svc.update(collection_id, req)


@router.delete("/{collection_id}")
def delete_collection(
    collection_id: str,
    svc: CollectionService = Depends(get_collection_service),
    _auth: None = Depends(verify_api_key),
):
    svc.delete(collection_id)
    return {"status": "deleted"}


@router.get("/{collection_id}/stats")
def collection_stats(
    collection_id: str,
    svc: CollectionService = Depends(get_collection_service),
    _auth: None = Depends(verify_api_key),
):
    return svc.get(collection_id)
