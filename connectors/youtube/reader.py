"""YouTube transcript connector — indexes video transcripts with timestamped chunks."""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import parse_qs, urlparse

import httpx

from connectors.base import BaseConnector, Document

YOUTUBE_VIDEO_PATTERNS = [
    re.compile(r"^https?://(?:www\.)?youtube\.com/watch\?(.+)$", re.I),
    re.compile(r"^https?://youtu\.be/([A-Za-z0-9_-]{11})", re.I),
    re.compile(r"^https?://(?:www\.)?youtube\.com/shorts/([A-Za-z0-9_-]{11})", re.I),
]


class YouTubeTranscriptConnector(BaseConnector):
    name = "youtube"

    def __init__(self, config: dict):
        super().__init__(config)
        self.urls = self._normalize_inputs(config.get("urls"))
        self.video_ids = self._normalize_inputs(config.get("video_ids"))
        self.label = (config.get("label") or "youtube-transcripts").strip() or "youtube-transcripts"
        self.languages = self._normalize_inputs(config.get("languages")) or ["en"]
        self.include_timestamps = bool(config.get("include_timestamps", True))
        self.timeout = float(config.get("request_timeout_seconds", 20))
        self.min_text_chars = int(config.get("min_text_chars", 40))

    def get_repo_name(self) -> str:
        return self.label

    def _normalize_inputs(self, value) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            return [line.strip() for line in value.splitlines() if line.strip()]
        if isinstance(value, Iterable):
            return [str(v).strip() for v in value if str(v).strip()]
        return [str(value).strip()]

    def _extract_video_id(self, raw: str) -> str | None:
        text = (raw or "").strip()
        if not text:
            return None
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
            return text
        parsed = urlparse(text)
        if parsed.netloc.endswith("youtube.com"):
            if parsed.path == "/watch":
                return parse_qs(parsed.query).get("v", [None])[0]
            shorts = re.match(r"^/shorts/([A-Za-z0-9_-]{11})", parsed.path)
            if shorts:
                return shorts.group(1)
        if parsed.netloc == "youtu.be":
            parts = [p for p in parsed.path.split("/") if p]
            if parts:
                return parts[0]
        return None

    def _video_ids(self) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for raw in [*self.video_ids, *self.urls]:
            video_id = self._extract_video_id(raw)
            if video_id and video_id not in seen:
                ids.append(video_id)
                seen.add(video_id)
        return ids

    def _fetch_transcript(self, video_id: str) -> list[dict]:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError as exc:
            raise RuntimeError("youtube-transcript-api is not installed") from exc

        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=self.languages)
        except Exception:
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
        return transcript or []

    def _fetch_video_metadata(self, video_id: str) -> dict:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        try:
            resp = httpx.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return {
                "title": data.get("title", ""),
                "author": data.get("author_name", ""),
                "thumbnail_url": data.get("thumbnail_url", ""),
                "provider_name": data.get("provider_name", "YouTube"),
            }
        except Exception:
            return {"title": video_id, "author": "", "thumbnail_url": "", "provider_name": "YouTube"}

    def _format_seconds(self, seconds: float) -> str:
        total = max(0, int(seconds))
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def load_documents(self) -> Iterator[Document]:
        ids = self._video_ids()
        if not ids:
            raise ValueError("Provide at least one YouTube video URL or video ID")

        for video_id in ids:
            transcript = self._fetch_transcript(video_id)
            if not transcript:
                continue
            meta = self._fetch_video_metadata(video_id)

            lines: list[str] = []
            for item in transcript:
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                start = float(item.get("start", 0.0) or 0.0)
                if self.include_timestamps:
                    lines.append(f"[{self._format_seconds(start)}] {text}")
                else:
                    lines.append(text)
            content = "\n".join(lines).strip()
            if len(content) < self.min_text_chars:
                continue

            url = f"https://www.youtube.com/watch?v={video_id}"
            yield Document(
                id=f"youtube:{video_id}",
                content=content,
                title=meta.get("title") or f"YouTube {video_id}",
                source=self.name,
                url=url,
                author=meta.get("author", ""),
                created_at=None,
                updated_at=datetime.now(timezone.utc),
                metadata={
                    "path": video_id,
                    "video_id": video_id,
                    "channel": meta.get("author", ""),
                    "thumbnail_url": meta.get("thumbnail_url", ""),
                    "provider_name": meta.get("provider_name", "YouTube"),
                    "mode": "youtube",
                },
            )
