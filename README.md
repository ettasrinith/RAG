# Knowledge Hub

A RAG workspace that indexes local folders, GitHub repositories, websites, and academic papers — then lets you search and chat over them with grounded answers and source links.

## Quick start

### 1. Clone and setup

```bash
git clone https://github.com/ettasrinith/RAG.git
cd RAG
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

### 2. Configure

Create `.env` from the template below and fill in the keys you need:

```bash
cp .env.example .env
```

| Key | Purpose |
|-----|---------|
| `ZEN_API_KEY` | Chat completions |
| `OPENAI_API_KEY` | Optional — embeddings or chat |
| `ANTHROPIC_API_KEY` | Optional — Claude chat |
| `GITHUB_PAT` | Index private GitHub repos |
| `OPENALEX_API_KEY` | Free — academic search |
| `S2_API_KEY` | Optional — raises Semantic Scholar rate limit |
| `KH_API_KEY` | Optional — require `X-API-Key` header on write endpoints |
| `CONFLUENCE_URL`, `CONFLUENCE_EMAIL`, etc. | Optional — Confluence connector |

Then edit `config.yaml` to set your repo path, chunk size, and connectors. The file uses `${VAR}` syntax for secrets — they are loaded from `.env` at runtime and never written back into `config.yaml`.

### 3. Run

```bash
uvicorn api.server:app --reload
```

Open **http://localhost:8000**.

### Or use Docker

```bash
docker compose up --build
```

## What it indexes

| Mode | Source |
|------|--------|
| **Local folder** | Any directory on disk — code, notes, docs, markdown |
| **GitHub repo** | Repo files via the GitHub API (requires PAT) |
| **Website** | Crawl a site with sitemap support, same-domain restriction, robots.txt respect |
| **arXiv papers** | Paste an arXiv ID or URL |
| **OpenAlex** | 250M+ scholarly works via the OpenAlex API |
| **Semantic Scholar** | 200M+ papers via the Graph API (no key needed) |
| **YouTube** | Video URLs — transcripts + metadata |
| **ZIP upload** | Upload a zip of notes/docs and index the contents |

## Architecture

```
api/          FastAPI backend (server, routes, middleware, filters)
core/         Indexing pipeline, vector store (LanceDB), connectors
services/     Deep research, literature review, parsing, search, recommendations
connectors/   Per-source connectors (GitHub, website, arXiv, OpenAlex, etc.)
ui/           Single-page frontend (HTML + JS + CSS)
config.yaml   Runtime configuration (secrets reference env vars)
```

## Configuration

- `config.yaml` — main config, `${ENV_VAR}` refs resolved from `.env` at load time. Tracked in git so everyone shares the same config structure, but **secrets are never committed** — they live only in `.env`.
- `.env` — secrets and API keys. **Gitignored.** Create it from `.env.example` and never commit it.

### Security note

`config.yaml` uses `${GITHUB_REPO}`, `${GITHUB_PAT}`, etc. as placeholders. These are resolved at runtime from `.env` and are never written back to `config.yaml` when you save settings.

## Development

```bash
make dev          # run server in dev mode
make test         # run pytest with coverage
make lint         # run ruff check + format check
make format       # auto-fix lint issues
make docker-up    # build and run via Docker
make docker-down  # stop Docker compose
```

## Notes

- The backend runs on port **8000** by default.
- Data is stored in `./data/` (LanceDB). This directory is gitignored.
- The frontend is a vanilla SPA — `ui/index.html` is the entry point.
- API key enforcement is opt-in: set `KH_API_KEY` in `.env` to require an
  `X-API-Key` header on write endpoints.

## Why .zcode is in .gitignore

`.zcode/` is a ZCode session/plan directory used by the AI coding agent.
It contains internal planning documents that are not part of the application
and should not be committed. The whole directory is gitignored.
