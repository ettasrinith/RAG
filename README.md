[README.md](https://github.com/user-attachments/files/30117348/README.md)
# Knowledge Hub

Minimal RAG workspace for indexing GitHub repositories and local folders, then searching and chatting over them with citations.

## What this project does

- Index a **local code/project folder**
- Index a **GitHub repository using a personal access token (PAT)**
- Optionally index **GitHub commits**
- Search with hybrid retrieval
- Chat with grounded answers and source links

## Current focus

This project is now focused on:
- **GitHub repos / local folders**
- **Website crawling for reusable information pulling**
- **Code, notes, docs, markdown, project material**

Removed from focus:
- Jira
- Confluence

## Good use cases for school / college

This can become a very strong student project if you use it for academic knowledge instead of only company knowledge.

### Best directions

1. **Study Material RAG**
   - index lecture notes
   - index PDFs converted to text/markdown
   - index assignments, lab files, and class summaries
   - ask: "explain unit 3 in simple words"

2. **Programming Course Assistant**
   - index DSA notes, coding assignments, Java/Python labs
   - ask: "where is binary search implemented?"
   - ask: "compare stack vs queue from my notes"

3. **College Project Knowledge Base**
   - index your final year project repo
   - index documentation, reports, meeting notes
   - ask architecture and implementation questions

4. **Research Paper Assistant**
   - index extracted paper text, summaries, experiment notes
   - ask for comparisons, definitions, literature review help

5. **Placement Prep RAG**
   - index aptitude notes, CS fundamentals, OS/DBMS/CN notes
   - ask targeted interview prep questions

## Recommended project idea for you

### Student Knowledge Assistant
Build this as a clean academic RAG app where a student can:
- upload/index subject notes
- index coding folders or GitHub repos
- ask semester subject questions
- get cited answers
- search project files quickly
- revise before exams

That is a much better and more relatable portfolio project for school/college.

## Setup

```bash
cd knowledge-hub
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn api.server:app --reload
```

Then open:

```text
http://localhost:8000
```

## Indexing modes

### 1. Local folder mode
Use a local project/repo path and index files directly.

### 2. GitHub token mode
Provide:
- GitHub repo: `owner/repo`
- GitHub PAT
- optional branch

This indexes repository files through the GitHub API.

### 3. Website crawler mode
Use the generic website crawler to pull information from:
- college notice websites
- documentation portals
- blogs
- research pages
- help centers
- course websites
- internal knowledge sites

Crawler features:
- start URLs
- optional sitemap URLs
- same-domain restriction
- include / exclude patterns
- max pages
- max depth
- robots.txt respect
- cleaned content extraction for RAG

This is not only for Gmail-related use. It is a reusable information pulling connector.

### 4. arXiv paper mode
Paste arXiv IDs or arXiv URLs and index:
- paper metadata
- abstract
- PDF-extracted full text when available

### 5. OpenAlex mode
Index 250M+ scholarly works via the OpenAlex API. Set a free API key
(`OPENALEX_API_KEY` in `.env`) and provide a keyword query or a list of
OpenAlex/DOI IDs. Indexes title, authors, venue, year, citation count, DOI,
and the reconstructed abstract.

### 6. Semantic Scholar mode
Index 200M+ papers via the Semantic Scholar Graph API — the open,
no-key substitute for broad "Google Scholar-like" academic search. Provide a
keyword query or IDs/DOIs. Indexes metadata, abstract, generated TLDR, and
citation counts. Optionally set `S2_API_KEY` to raise the rate limit.

### 7. Confluence mode
Index pages from an Atlassian Confluence wiki (internal company/team
knowledge). Provide a `base_url` plus either an email + API token
(Confluence Cloud) or a personal access token (Server/Data Center). Filter by
CQL query and/or space keys. Page bodies are converted to plain text.

### 8. YouTube transcript mode
Paste video URLs or IDs and index:
- transcript text
- timestamps
- title and channel metadata

### 9. ZIP upload mode
Upload a ZIP of notes, docs, markdown, or project files. The app safely extracts
supported files and indexes them as a document collection.

### Optional
Enable GitHub commit indexing if you also want commit history in retrieval.

## Notes

- Backend API: `api/server.py`
- Frontend: `ui/index.html` + `ui/app.js` + `ui/styles.css`
- Indexing pipeline: `core/indexer.py`
- GitHub files connector: `connectors/github/files.py`

## Configuration

- `config.yaml` references environment variables with the `${VAR}` syntax
  (e.g. `repo: ${GITHUB_REPO}`, `pat: ${GITHUB_PAT}`). Fill those in `.env` —
  they are resolved automatically at load time and **preserved as references**
  when you save settings (secrets are never written back into `config.yaml`).
- Set `KH_API_KEY` in the environment (and `.env`) to require an `X-API-Key`
  header on write endpoints (`/config`, `/sync/start`, `/sync/clear`). It is
  opt-in: if unset, the API is open (fine for a local single-user machine).
- Incremental sync, the folder hierarchy index, and the knowledge graph run
  automatically when a repo path / `local_path` is configured — no extra flags.

## Next recommended build for college

If you want the best academic version of this project, next build:
- file upload for notes / PDFs
- subject-wise folders
- semester tags
- flashcard generation
- quiz generation from notes
- exam revision mode
- citation highlighting

That would make this a strong **student AI assistant / academic RAG system**.
