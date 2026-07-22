"""Upload helpers for ZIP ingestion."""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from core.config import resolve_data_path
from core.logging import get_logger

log = get_logger("uploads")

ZIP_ROOT = resolve_data_path("./data/uploads")
ZIP_ROOT.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".rst", ".pdf", ".docx",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".scala",
    ".go", ".rs", ".rb", ".php", ".cs", ".cpp", ".c", ".h", ".hpp",
    ".html", ".css", ".scss", ".json", ".xml", ".yml", ".yaml", ".toml",
}


def sanitize_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in (value or "upload").strip())
    cleaned = cleaned.strip("-_")
    return cleaned[:80] or "upload"


def create_upload_dir(prefix: str = "zip") -> Path:
    base = ZIP_ROOT / prefix
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="job-", dir=str(base)))


def cleanup_upload_dir(path: str | Path | None) -> None:
    if not path:
        return
    try:
        shutil.rmtree(Path(path), ignore_errors=True)
    except Exception as e:
        log.warning("cleanup_upload_dir failed: %s", e)


def _safe_destination(root: Path, member_name: str) -> Path:
    name = member_name.replace("\\", "/").strip("/")
    if not name:
        raise ValueError("invalid archive entry")
    # Resolve real paths to handle symlinks in the chain
    root_real = root.resolve()
    dest = (root / name).resolve()
    # Verify the destination is actually inside the root directory
    if root_real not in dest.parents and dest != root_real:
        raise ValueError("unsafe archive entry")
    return dest


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    """Detect if a ZIP entry is a symlink (Unix external attributes)."""
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def extract_zip_safe(zip_path: str | Path, output_dir: str | Path,
                     allowed_extensions: set[str] | None = None,
                     max_total_bytes: int = 200 * 1024 * 1024,
                     max_files: int = 4000) -> list[str]:
    zip_path = Path(zip_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    allowed = {ext.lower() for ext in (allowed_extensions or ALLOWED_EXTENSIONS)}

    extracted: list[str] = []
    total = 0
    count = 0

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue

            # Block symlink entries — they can be used for path traversal
            if _is_symlink_entry(info):
                log.warning("blocked symlink entry in zip: %s", info.filename)
                raise ValueError(f"symlink entries are not allowed: {info.filename}")

            count += 1
            if count > max_files:
                raise ValueError("zip file contains too many entries")
            total += int(info.file_size or 0)
            if total > max_total_bytes:
                raise ValueError("zip file is too large when extracted")

            dest = _safe_destination(output_dir, info.filename)
            ext = dest.suffix.lower()
            if allowed and ext and ext not in allowed:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)

            # Verify final destination is a regular file (not a symlink that
            # could have been created by the OS or a prior extraction step)
            try:
                if not os.path.isfile(dest) or os.path.islink(dest):
                    dest.unlink(missing_ok=True)
                    raise ValueError(f"extracted entry is not a regular file: {info.filename}")
            except OSError as e:
                log.warning("post-extract verification failed for %s: %s", info.filename, e)
                raise ValueError(f"post-extract verification failed: {info.filename}")

            extracted.append(str(dest))

    return extracted
