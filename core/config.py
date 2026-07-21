"""Loads config.yaml + .env and resolves env-var references."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


_ENV_REFS: dict = {}


def _resolve_env(value, path=()):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k.endswith("_env") and isinstance(v, str):
                val = os.environ.get(v, "")
                out[k[:-4]] = val
                _ENV_REFS[path + (k[:-4],)] = (v, val)
            else:
                out[k] = _resolve_env(v, path + (k,))
        return out
    if isinstance(value, list):
        return [_resolve_env(v, path + (i,)) for i, v in enumerate(value)]
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        var = value[2:-1]
        val = os.environ.get(var, "")
        if not val:
            # Unset env var -> treat as empty so connectors can fall back to a
            # ROOT-relative default instead of keeping the literal "${VAR}".
            _ENV_REFS[path] = (var, "")
            return ""
        _ENV_REFS[path] = (var, val)
        return val
    return value


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else ROOT / "config.yaml"
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return _resolve_env(raw)


def resolve_data_path(p: str | Path) -> Path:
    """Resolve a data path relative to the project ROOT so the app behaves the
    same regardless of the current working directory it is launched from.

    Absolute paths and existing paths are returned unchanged.
    """
    p = Path(p)
    if p.is_absolute():
        return p
    return (ROOT / p).resolve()


def save_config(config: dict, path: str | Path | None = None) -> None:
    """Persist config without leaking env-resolved secrets.

    Re-reads the raw file so ``${VAR}`` references survive, then merges in the
    (possibly edited) values -- skipping any key that originated from an env ref.
    """
    path = Path(path) if path else ROOT / "config.yaml"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            raw = {}
    else:
        raw = {}
    merged = _deep_merge_skip_refs(raw, config)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(merged, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _deep_merge_skip_refs(raw, resolved, path=()):
    if isinstance(resolved, dict):
        if not isinstance(raw, dict):
            raw = {}
        for k, v in resolved.items():
            child = path + (k,)
            if child in _ENV_REFS:
                _var, original = _ENV_REFS[child]
                if v == original:
                    # Unchanged -> keep the ${VAR} reference in the raw file.
                    continue
                # User overrode it -> persist the literal value instead.
            raw[k] = _deep_merge_skip_refs(raw.get(k), v, child)
        return raw
    if isinstance(resolved, list):
        return list(resolved)
    return resolved
