# Knowledge Hub — Top-Class UI Redesign Plan

## Vision
Build a unified search + chat interface inspired by Onyx.app, Perplexity AI, and Google Scholar. One clean page that auto-detects intent: document search shows results, questions get AI answers with citations.

---

## Architecture: Single-Page App, Three Modes

### Mode 1: Search (default) — Google Scholar / Onyx style
- Centered search box on clean white page
- Query goes in, results come out as structured cards
- Each card: title, source pill, snippet (3 lines), file path, relevance score
- Right sidebar or top bar: filters (source type, date range, repo)
- Result count: "12 results for 'vector databases'"
- Click a result → opens file in viewer (or external URL)

### Mode 2: Chat — Perplexity style
- When user types a question (detected or toggled), switch to chat mode
- AI streams answer with inline citations [1] [2] [3]
- Source cards appear below the answer
- Follow-up question suggestions
- Typing indicator while streaming

### Mode 3: Deep Research — Onyx style
- Multi-step reasoning for complex queries
- Shows "Researching..." with progress steps
- Final answer with full source list

---

## File Changes Required

### 1. `ui/index.html` — Complete Rewrite
**Structure:**
```
┌─────────────────────────────────────────────────┐
│  Logo    [Search] [Chat] [Index]    Status Dot  │  ← Top bar
├─────────────────────────────────────────────────┤
│                                                 │
│          Knowledge Hub                          │  ← Hero (search page)
│    ┌─────────────────────────────────┐          │
│    │ 🔍 Search your knowledge...  [→]│          │  ← Big search box
│    └─────────────────────────────────┘          │
│    [All Sources ▾] [All Types ▾] [Hybrid ✓]    │  ← Filter row
│                                                 │
│    12 results for "vector databases"            │  ← Result count
│                                                 │
│    ┌─────────────────────────────────────────┐  │
│    │ test3.md                                │  │  ← Result card
│    │ [file] [test_md] [0.713]                │  │
│    │ Vector databases are specialized...     │  │
│    └─────────────────────────────────────────┘  │
│                                                 │
│    ┌─────────────────────────────────────────┐  │
│    │ search.md                               │  │
│    │ [file] [test_md] [0.523]                │  │
│    │ Embeddings turn text into vectors...    │  │
│    └─────────────────────────────────────────┘  │
│                                                 │
└─────────────────────────────────────────────────┘
```

**Key elements:**
- `<header class="topbar">` — Logo + nav tabs + status
- `<main class="main">` — Three page sections
- Search page: hero with big search box, filters, results area
- Chat page: message thread + input bar
- Index page: source config panels + progress

### 2. `ui/styles.css` — Complete Rewrite
**Design system:**
- Font: Inter (Google Fonts) — clean, modern
- Colors: minimal — white bg, blue accent (#2563eb), subtle grays
- Cards: white surface, 1px border, 12px radius, subtle shadow
- Search box: large (48px height), centered, with shadow on focus
- Result cards: title in blue (link color), meta pills, 3-line snippet
- Toggle switches instead of checkboxes
- Responsive: mobile-first

**Key CSS classes:**
- `.topbar` — fixed top nav
- `.search-hero` — centered search area with title
- `.search-input-wrap` — large search box with icon
- `.result-card` — search result card
- `.pill` — small tag badges (source, score)
- `.toggle` — custom toggle switches
- `.chat-wrap` — full-height chat container
- `.source-tabs` — horizontal tab bar for index sources
- `.panels` — config panel container

### 3. `ui/app.js` — Major Changes
**New/changed functions:**
- `navigate(page)` — tab switching (default: search)
- `doSearch(e)` — renders result cards with file links
- `sendChat(e)` — streams chat with inline citations
- `renderResults(hits, query)` — structured result cards
- `renderChatMessage(msg)` — markdown rendering for chat

**Key behavior:**
- Search results link to `/file?path=...` for local files
- Score displayed as pill on each card
- Source type displayed as colored pill
- Snippet truncated to 3 lines with CSS clamp

### 4. `api/server.py` — Enhancements needed
- `/file` endpoint already exists (renders file as HTML)
- Add `/api/search` as alias for POST /search (RESTful)
- Ensure search results include all metadata (title, url, source, repo, score, snippet)

### 5. `core/vector_store.py` — Already fixed
- `to_arrow()` API fix applied
- FTS working after tantivy install

---

## Detailed UI Specifications

### Search Results Card
```
┌──────────────────────────────────────────────────┐
│ test3.md                                    0.71 │  ← title + score
│                                                  │
│ [file] [test_md]                                  │  ← source pills
│                                                  │
│ Vector databases are specialized database         │  ← snippet (3 lines)
│ systems designed to store, manage, and query      │
│ high-dimensional vectors efficiently...           │
│                                                  │
│ data/test_md/test3.md                            │  ← file path (monospace)
└──────────────────────────────────────────────────┘
```

### Chat Message
```
┌──────────────────────────────────────────────────┐
│ 🤖 Vector databases store high-dimensional       │
│ vectors. The most popular ones include LanceDB,  │
│ Pinecone, Weaviate, and Milvus [1][2][3].        │
│                                                  │
│ [1] test3.md — Vector Databases and Similarity   │
│ [2] search.md — Vector Search                    │
│ [3] intro.md — Introduction to RAG               │
└──────────────────────────────────────────────────┘
```

### Index Page
```
┌──────────────────────────────────────────────────┐
│ Add Content                                      │
│ Configure a source and index it.                 │
│                                                  │
│ [📁 Folder] [GitHub] [🌐 Website] [📄 arXiv]    │
│                                                  │
│ ┌────────────────────────────────────────────┐   │
│ │ Project or notes folder                    │   │
│ │ [C:/Users/you/project        ] [Browse]   │   │
│ └────────────────────────────────────────────┘   │
│                                                  │
│ ☐ Force full re-index   [Save] [Start] [Stop]   │
│                                                  │
│ ┌────────────────────────────────────────────┐   │
│ │ Indexing Progress                    Idle  │   │
│ │ ████████████████████░░░░░  78%            │   │
│ │ 6 docs, 8 chunks                          │   │
│ └────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

---

## Implementation Order

### Phase 1: Core UI (do first)
1. Rewrite `ui/index.html` with new structure
2. Rewrite `ui/styles.css` with design system
3. Rewrite `ui/app.js` with new search rendering

### Phase 2: Polish
4. Add smooth transitions between pages
5. Add loading states and animations
6. Improve mobile responsiveness

### Phase 3: Features
7. Add file viewer styling improvements
8. Add search history (localStorage)
9. Add keyboard shortcuts (/ to focus search)

---

## Key Design Decisions

1. **Search is the default page** — not Index. Users come to search.
2. **Results link to files** — `/file?path=...` for local, external URL for web.
3. **Score shown as pill** — subtle, not prominent. Users care about relevance, not numbers.
4. **Source type as pill** — colored by type (file=gray, web=blue, arxiv=green).
5. **Snippet is 3 lines max** — CSS `-webkit-line-clamp: 3`.
6. **Chat mode for questions** — toggle between search and chat.
7. **No sidebar** — clean, single-column layout. Filters inline below search box.
8. **Inter font** — clean, professional, widely available.
