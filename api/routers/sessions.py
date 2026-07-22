"""Chat session management — CRUD for persistent chat history."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import verify_api_key
from api.deps import get_session
from core.registry.models import ChatSessionModel, ChatMessageModel

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    title: str = Field(default="New chat", max_length=500)


class SessionUpdate(BaseModel):
    title: str = Field(..., max_length=500)


class MessageCreate(BaseModel):
    role: str = Field(..., pattern=r"^(user|assistant)$")
    content: str = Field(..., min_length=1)
    sources: list[dict] | None = None


class FeedbackUpdate(BaseModel):
    feedback: str | None = Field(default=None, pattern=r"^(up|down)$")
    feedback_reason: str | None = Field(default=None, max_length=1000)


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: str | None = None
    updated_at: str | None = None
    message_count: int = 0


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    sources: list[dict] | None = None
    feedback: str | None = None
    feedback_reason: str | None = None
    created_at: str | None = None


@router.get("", response_model=list[SessionResponse])
def list_sessions(
    session: Session = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    sessions = session.query(ChatSessionModel).order_by(
        ChatSessionModel.updated_at.desc()
    ).all()
    return [
        SessionResponse(
            id=s.id,
            title=s.title,
            created_at=s.created_at.isoformat() if s.created_at else None,
            updated_at=s.updated_at.isoformat() if s.updated_at else None,
            message_count=len(s.messages),
        )
        for s in sessions
    ]


@router.post("", response_model=SessionResponse)
def create_session(
    req: SessionCreate,
    session: Session = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    s = ChatSessionModel(title=req.title)
    session.add(s)
    session.commit()
    session.refresh(s)
    return SessionResponse(
        id=s.id,
        title=s.title,
        created_at=s.created_at.isoformat() if s.created_at else None,
        updated_at=s.updated_at.isoformat() if s.updated_at else None,
        message_count=0,
    )


@router.get("/{session_id}", response_model=list[MessageResponse])
def get_messages(
    session_id: str,
    session: Session = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    s = session.query(ChatSessionModel).filter(ChatSessionModel.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            sources=m.sources_json,
            feedback=m.feedback,
            feedback_reason=m.feedback_reason,
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m in s.messages
    ]


@router.patch("/{session_id}", response_model=SessionResponse)
def update_session(
    session_id: str,
    req: SessionUpdate,
    session: Session = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    s = session.query(ChatSessionModel).filter(ChatSessionModel.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    s.title = req.title
    session.commit()
    session.refresh(s)
    return SessionResponse(
        id=s.id,
        title=s.title,
        created_at=s.created_at.isoformat() if s.created_at else None,
        updated_at=s.updated_at.isoformat() if s.updated_at else None,
        message_count=len(s.messages),
    )


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    session: Session = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    s = session.query(ChatSessionModel).filter(ChatSessionModel.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    session.delete(s)
    session.commit()
    return {"deleted": True}


@router.post("/{session_id}/messages", response_model=MessageResponse)
def add_message(
    session_id: str,
    req: MessageCreate,
    session: Session = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    s = session.query(ChatSessionModel).filter(ChatSessionModel.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    msg = ChatMessageModel(
        session_id=session_id,
        role=req.role,
        content=req.content,
        sources_json=req.sources,
    )
    session.add(msg)
    # Auto-title from first user message
    if req.role == "user" and s.title == "New chat":
        s.title = req.content[:100]
    session.commit()
    session.refresh(msg)
    return MessageResponse(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        sources=msg.sources_json,
        feedback=msg.feedback,
        feedback_reason=msg.feedback_reason,
        created_at=msg.created_at.isoformat() if msg.created_at else None,
    )


@router.patch("/{session_id}/messages/{message_id}/feedback")
def update_feedback(
    session_id: str,
    message_id: str,
    req: FeedbackUpdate,
    session: Session = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    msg = session.query(ChatMessageModel).filter(
        ChatMessageModel.id == message_id,
        ChatMessageModel.session_id == session_id,
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    msg.feedback = req.feedback
    msg.feedback_reason = req.feedback_reason
    session.commit()
    return {"updated": True}
