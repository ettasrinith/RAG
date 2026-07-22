from __future__ import annotations

import json
import queue
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from core.config import load_config
from core.chunker import chunk_text
from core.embedder import embed
from core.indexer import run_indexing
from core.registry.database import get_session
from core.registry.models import CollectionModel, IndexJobModel
from core.vector_store import VectorStore
from services.job_service import JobService


class IngestService:
    def __init__(self, session: Session, store: VectorStore):
        self.session = session
        self.store = store
        self.config = load_config()
        self.job_svc = JobService(session)
        self._active_jobs: dict[str, threading.Thread] = {}
        self._progress_queues: dict[str, queue.Queue] = {}

    def start_ingest(
        self,
        source: str,
        source_config: dict[str, Any],
        collection_id: str | None = None,
        collection_name: str | None = None,
    ) -> str:
        if collection_id:
            collection = self.session.query(CollectionModel).filter(CollectionModel.id == collection_id).first()
            if not collection:
                from api.errors import not_found
                raise not_found("Collection", collection_id)
        elif collection_name:
            collection = CollectionModel(
                name=collection_name,
                kind=source,
                source_config=source_config,
            )
            self.session.add(collection)
            self.session.commit()
            self.session.refresh(collection)
            collection_id = collection.id
        else:
            from api.errors import invalid_argument
            raise invalid_argument("Either collection_id or collection_name is required")

        job = self.job_svc.create(collection_id=collection_id, items_total=0)
        job_id = job.id
        progress_q: queue.Queue = queue.Queue()
        self._progress_queues[job_id] = progress_q

        def _progress_cb(event: dict):
            progress_q.put(event)
            if event.get("type") == "progress":
                done = event.get("done", 0)
                total = event.get("total", 0)
                state = event.get("state", "indexing")
                self.job_svc.update_progress(job_id, done, total, state)
            elif event.get("type") == "error":
                job_model = self.session.query(IndexJobModel).filter(IndexJobModel.id == job_id).first()
                if job_model:
                    job_model.state = "failed"
                    job_model.error_message = str(event.get("error", ""))
                    job_model.finished_at = datetime.now(timezone.utc)
                    self.session.commit()
            elif event.get("type") == "done":
                job_model = self.session.query(IndexJobModel).filter(IndexJobModel.id == job_id).first()
                if job_model:
                    job_model.state = "done"
                    job_model.finished_at = datetime.now(timezone.utc)
                    self.session.commit()

        def _run():
            try:
                result = run_indexing(
                    progress_cb=_progress_cb,
                    repo_path=source_config.get("repo_path"),
                    force_full=source_config.get("force_full", False),
                )
                if result:
                    _progress_cb({"type": "done", "result": result})
            except Exception as e:
                _progress_cb({"type": "error", "error": str(e)})
            finally:
                progress_q.put(None)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        self._active_jobs[job_id] = thread

        return job_id

    def get_progress_queue(self, job_id: str) -> queue.Queue | None:
        return self._progress_queues.get(job_id)

    def cancel_job(self, job_id: str):
        if job_id in self._active_jobs:
            self.job_svc.cancel(job_id)
            del self._active_jobs[job_id]
        if job_id in self._progress_queues:
            del self._progress_queues[job_id]
