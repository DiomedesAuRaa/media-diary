# Media Diary App

Personal media tracker in a git repo — ship movies first, architect for books, TV, and more later.

---

## Decisions locked in

| Decision | Choice |
|---|---|
| Source of truth | Git repo (`media-diary`) — app code + CSV data together |
| Storage format | One CSV per media type under `data/` |
| Entry (rate/add) | FastAPI on Pi (or Mac for dev) — proxies APIs, hides keys |
| Browse anywhere | GitHub Pages — auto-built from CSV on each push |
| Pi as sole writer | Rate via app only; avoid hand-editing CSV to prevent merge conflicts |
| Mac clone | Use a normal git clone, not Synology Drive sync folder as working copy |

Existing `movies/movies.csv` migrates to `data/movies.csv` with identical columns so `movies/recommendations.py` keeps working (moved to `scripts/recommendations.py`).

---

## Known limitations (explicit, not implicit)

**Pi offline = can't add entries.** If the Pi is unreachable (travel, reboot, network issue), the write endpoint is unavailable. Offline queuing, a mobile app, or a fallback write path are all out of scope for v1. This is intentional — git-as-database requires a single writer, and adding a second writer introduces merge conflicts. Name the constraint, don't fight it.

**GitHub Pages viewer lags by one push.** The Pages export runs after a git push. If the Pi push fails (see git_sync failure handling below), the viewer will be stale until the next successful push. This is acceptable for a personal diary.

---

## Extensible architecture

Each media type is a config entry, not a fork of the app. Adding books later = new CSV + provider + config row, not a rewrite.

```
flowchart TB
  subgraph ui [Browser UI]
    Nav[Media tabs: Movies / Books / TV]
    Form[Generic form per type]
  end
  subgraph api [FastAPI]
    Registry[media_types config]
    Router["/api/{type}/..."]
    CSV[csv_store.py]
    Git[git_sync.py]
    Providers[providers/]
  end
  subgraph data [Git repo data/]
    MoviesCSV[movies.csv]
    BooksCSV[books.csv future]
    TvCSV[tv.csv future]
  end
  subgraph external [External APIs]
    TMDB[TMDb — movies + TV]
    OL[Open Library — books]
  end
  Nav --> Form
  Form --> Router
  Router --> Registry
  Router --> Providers
  Providers --> TMDB
  Providers --> OL
  Router --> CSV
  CSV --> MoviesCSV
  CSV --> BooksCSV
  CSV --> TvCSV
  CSV --> Git
  Git --> GitHub[(GitHub)]
```

---

## Media type registry (`app/config.py`)

Each type defines columns, which fields are user vs API-filled, and which provider to use:

```python
# Conceptual — movies v1 fully implemented; others stubbed for later
MEDIA_TYPES = {
    "movies": {
        "label": "Movies",
        "csv": "data/movies.csv",
        "columns": ["Movie", "Date Watched/Rated", "Date Released", "Rating", "Director"],
        "title_column": "Movie",
        "user_fields": ["Rating"],              # you enter
        "auto_fields": ["Date Watched/Rated"],  # today, editable
        "api_fields": ["Date Released", "Director"],
        "provider": "tmdb_movie",
        "enabled": True,
    },
    "books": {
        "label": "Books",
        "csv": "data/books.csv",
        "columns": ["Book", "Date Read/Rated", "Date Published", "Rating", "Author"],
        "title_column": "Book",
        "user_fields": ["Rating"],
        "auto_fields": ["Date Read/Rated"],
        "api_fields": ["Date Published", "Author"],
        "provider": "openlibrary",
        "enabled": False,  # flip when ready
    },
    "tv": {
        "label": "TV Shows",
        "csv": "data/tv.csv",
        "columns": ["Show", "Date Watched/Rated", "Date Premiered", "Rating", "Creator"],
        "title_column": "Show",
        "user_fields": ["Rating"],
        "auto_fields": ["Date Watched/Rated"],
        "api_fields": ["Date Premiered", "Creator"],
        "provider": "tmdb_tv",
        "enabled": False,
    },
}
```

---

## Generic API routes

v1 implements movies; routes work for any enabled type.

| Route | Purpose |
|---|---|
| `GET /api/types` | List enabled media types + column metadata for UI |
| `GET /api/{type}/search?q=` | Title search via type's provider |
| `GET /api/{type}/lookup/{external_id}` | Fetch metadata (director, release date, etc.) |
| `GET /api/{type}/entries?limit=20` | Recent entries from CSV |
| `POST /api/{type}/entries` | Validate, prepend row, git commit + push |
| `GET /api/health` | Returns unpushed commit count; surface in UI as sync status |

---

## Provider layer (`app/providers/`)

| Provider | Used for | API | Key needed |
|---|---|---|---|
| `tmdb_movie` | Movies | TMDb search + credits | `TMDB_API_KEY` (free) |
| `tmdb_tv` | TV (future) | TMDb TV search + credits | Same key |
| `openlibrary` | Books (future) | Open Library search | None |

---

## CSV + git layer

### `csv_store.py`

- Prepend row (newest first); note that this rewrites the entire file on every entry — fine for a personal diary indefinitely, but worth knowing
- **File lock required:** use a threading lock (or `fcntl.flock`) to serialize writes; a single-writer Pi makes this trivial, but two rapid-fire requests would corrupt the CSV without it
- Duplicate detection keyed on `(title, year)` not just title — "Batman" is not a useful dedup key
- Duplicate behavior: **non-blocking warning with explicit confirm-to-proceed** — re-watching a film is legitimate; blocking the write is wrong
- Date format: MM/DD/YY

### `git_sync.py`

**Write ordering matters.** The sequence is:

```
1. Acquire file lock
2. Write CSV row (prepend)
3. git add data/{type}.csv
4. git commit -m "{type}: rate {title} {rating}"
5. Release lock
6. Respond 200 to UI  ← before push
7. git push  ← async, in background thread
```

Commit before responding. A crash between step 4 and 7 means the entry is safe in local git history and will push on the next successful push. A crash between step 2 and 3 means the row is written but not committed — that's the worst case (data exists, git doesn't know about it). Acceptable for a personal tool; document it so future-you knows to check `git status` if something seems off.

**Push failure handling:**

```python
# After async push fails, detect and surface on next request
def unpushed_count() -> int:
    result = subprocess.run(
        ["git", "log", "origin/main..HEAD", "--oneline"],
        capture_output=True, text=True
    )
    return len(result.stdout.strip().splitlines())
```

- `GET /api/health` returns `{"unpushed": 2}` — surface this in the UI ("2 entries not synced to GitHub")
- Do not retry push in a background loop; retry on the next user action (next `POST /api/{type}/entries` triggers a push attempt before committing the new row)
- Pi reboot doesn't lose data — commits are local; push retries when the service restarts and a new entry comes in

---

## Movies data model (v1 — unchanged from your CSV)

| Column | Example | Source |
|---|---|---|
| Movie | Michael Clayton | You (search + pick) |
| Date Watched/Rated | 07/31/25 | Auto: today |
| Date Released | 10/12/07 | TMDb |
| Rating | 10 | You |
| Director | Tony Gilroy | TMDb |

Edge cases:
- Show year in search results to disambiguate titles
- Co-directors joined with `,`
- Duplicate warning on `(title, year)` match, non-blocking confirm
- Date format MM/DD/YY throughout

---

## Future media types (not built in v1, but planned)

### Books
- CSV: `Book`, `Date Read/Rated`, `Date Published`, `Rating`, `Author`
- API: Open Library — free, no key
- Enable: add `data/books.csv` header row, set `enabled: True`, implement `openlibrary.py`

### TV shows
- CSV: `Show`, `Date Watched/Rated`, `Date Premiered`, `Rating`, `Creator`
- API: TMDb TV endpoints — same `TMDB_API_KEY`
- Enable: add `data/tv.csv`, implement `tmdb_tv.py` (reuse most of movie provider)
- Note: v1 rates whole shows; season/episode granularity can be a later column if needed

### Adding a new type later (checklist)

1. Add config entry in `app/config.py`
2. Create `data/{type}.csv` with header row
3. Implement provider in `app/providers/`
4. Enable in config — UI and routes pick it up automatically
5. Add tab to Pages viewer export

---

## Repo layout

```
media-diary/                         # GitHub repo: DiomedesAuRaa/media-diary
  data/
    movies.csv                       # migrated from movies/movies.csv
  app/
    main.py                          # FastAPI entrypoint
    config.py                        # MEDIA_TYPES registry
    csv_store.py                     # generic CSV read/write + file lock
    git_sync.py                      # commit + push after save; unpushed_count()
    providers/
      tmdb.py                        # tmdb_movie (+ tmdb_tv stub)
      openlibrary.py                 # stub for books
    routers/
      entries.py                     # generic /api/{type}/ routes
  static/
    index.html                       # entry UI; tabs driven by /api/types
  scripts/
    recommendations.py               # moved from movies/; accepts --csv arg (see below)
    export_json.py                   # data/*.csv → docs/*.json for Pages
  docs/
    index.html                       # read-only viewer (GitHub Pages)
    movies.json                      # generated by Action
  tests/
    test_csv_store.py                # prepend, dedupe, date format, file lock
    test_providers.py                # mock TMDB responses
  run.sh                             # local dev: venv + uvicorn
  media-diary.service                # Pi systemd template
  requirements.txt
  .env                               # gitignored
  .env.example                       # committed; documents required vars
  .gitignore
  .github/
    workflows/
      pages.yml
  README.md
```

Do not use Synology Drive as the git working directory. Clone to `~/code/media-diary` on Mac; clone to `/home/pi/media-diary` on Pi.

---

## Environment variables (`.env.example`)

```bash
TMDB_API_KEY=your_key_here
GIT_PUSH_TOKEN=your_token_here       # fine-grained token, repo write only
GIT_USER_EMAIL=your@email.com
GIT_USER_NAME=YourName
```

Commit `.env.example`; gitignore `.env`. You will thank yourself when setting up the Pi six months from now.

---

## End-to-end flows

### Save a movie (entry)

```
sequenceDiagram
  participant You
  participant Browser
  participant FastAPI
  participant TMDB
  participant CSV as data/movies.csv
  participant Git

  You->>Browser: Search title, pick film, set rating
  Browser->>FastAPI: POST /api/movies/entries
  FastAPI->>TMDB: credits lookup
  TMDB-->>FastAPI: director, release date
  FastAPI->>CSV: acquire lock, prepend row
  FastAPI->>Git: git add + git commit (sync)
  FastAPI-->>Browser: 200 success + unpushed count
  FastAPI->>Git: git push (async, background)
  Git-->>GitHub: trigger Pages Action
```

### Browse on phone anywhere

```
flowchart LR
  Push[git push] --> Action[GitHub Action]
  Action --> JSON[docs/movies.json]
  JSON --> Pages[github.io/media-diary]
  Phone[Phone on cellular] --> Pages
```

| Task | Where | URL |
|---|---|---|
| Rate a movie | Pi app (home Wi-Fi) | `http://<your-pi-ip>:8765` |
| Browse diary | GitHub Pages | `https://diomedesauraa.github.io/media-diary/` |
| Recommendations | Mac terminal | `git pull && python scripts/recommendations.py` |

GitHub Pages remains read-only — TMDb key and CSV writes stay on the Pi.

---

## GitHub Actions (`pages.yml`)

The Action exports CSVs to JSON and commits back to the repo. Key design points:

```yaml
on:
  push:
    branches: [main]

jobs:
  export:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python scripts/export_json.py   # reads data/*.csv → docs/*.json
      - run: |
          git config user.email "action@github.com"
          git config user.name "GitHub Action"
          git add docs/*.json
          git diff --cached --quiet || git commit -m "export: update json"
          git push
```

**Re-trigger guard:** `git diff --cached --quiet || git commit` — if no CSVs changed, JSON won't change, the commit is skipped, and the Action does not push, which means it does not re-trigger itself. Call this out explicitly so you don't chase a phantom loop.

**Permissions:** the Action needs write access to commit back. Set `permissions: contents: write` at the job level, or use a PAT.

---

## Pi deployment (Phase 2)

```bash
git clone git@github.com:DiomedesAuRaa/media-diary.git /home/pi/media-diary
cd /home/pi/media-diary
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env   # fill in keys
```

`media-diary.service`:

```ini
[Unit]
Description=Media Diary FastAPI
After=network.target

[Service]
WorkingDirectory=/home/pi/media-diary
EnvironmentFile=/home/pi/media-diary/.env
ExecStart=/home/pi/media-diary/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8765
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`Restart=always` with `RestartSec=5` is load-bearing here: if the app crashes mid-push, it comes back up and will surface unpushed commits on the next request. Document it as such, not just as boilerplate.

App updates on Pi: `git pull && systemctl restart media-diary`

**LAN only** — do not expose port 8765 to the internet without auth.

---

## `recommendations.py` migration

The script moves from `movies/recommendations.py` to `scripts/recommendations.py`. The CSV path changes from `movies/movies.csv` to `data/movies.csv`. Make the path a CLI argument rather than a hardcoded string:

```python
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--csv", default="data/movies.csv")
args = parser.parse_args()
```

This keeps the script working across both old and new paths during migration, and future-proofs it for books/TV without touching the script logic.

Usage stays the same: `python scripts/recommendations.py` (uses default) or `python scripts/recommendations.py --csv data/movies.csv`.

---

## UI approach

Single `static/index.html` styled like your Portfolio pages:

- **Top nav:** Movies | Books (soon) | TV (soon) — disabled tabs greyed until enabled
- **Form:** title search with autocomplete, rating 1–10, date defaulting to today
- **Preview:** director + release date after selecting a search result
- **Sync indicator:** unpushed commit count from `GET /api/health` — show "All synced" or "2 entries pending sync" quietly in the corner
- **Recent entries:** last 20 rows from current media type's CSV
- **JS:** fetches `/api/types` to render forms dynamically — adding books later is mostly backend

Pages viewer (`docs/index.html`): same tab pattern, read-only tables from exported JSON.

---

## Implementation phases

### Phase 1 — Core + movies (Mac)
1. Init repo, migrate CSV to `data/movies.csv`
2. Build registry, `csv_store`, `git_sync`, TMDb provider, generic routes
3. Entry UI for movies
4. Test locally at `localhost:8765`
5. Wire up Pages Action — get the browse URL live while still on Mac *(don't wait for Pi)*

### Phase 2 — Pi
1. Clone repo, systemd service, deploy key
2. Switch write endpoint from Mac to Pi
3. Bookmark `http://<your-pi-ip>:8765` on phone

### Phase 3 — Expand (when you want)
1. Enable books: Open Library provider + `data/books.csv`
2. Enable TV: TMDb TV provider + `data/tv.csv`
3. Optional: link from `Portfolio/home.html`

> **Phase ordering change from original plan:** Pages goes live at the end of Phase 1, not Phase 3. The Action runs on every push regardless of where the push originates — you get the read-only browse URL immediately and don't have to wait until the Pi is set up.

---

## Tests

`csv_store.py` is the one piece of code where a silent bug corrupts your data. Five tests here pay for themselves:

```
tests/
  test_csv_store.py
    - test_prepend_adds_row_at_top
    - test_prepend_preserves_existing_rows
    - test_duplicate_detection_keyed_on_title_and_year
    - test_duplicate_warning_is_non_blocking
    - test_date_format_is_MM_DD_YY
  test_providers.py
    - test_tmdb_search_returns_results (mock HTTP)
    - test_tmdb_lookup_extracts_director (mock HTTP)
```

Run with `pytest tests/` before pushing.

---

## Architectural considerations

A few higher-level questions worth having answers to before you start cutting code:

### 1. Git as a database is the right call — but own the tradeoffs

Git-as-storage is a genuinely good fit here: free hosting, human-readable history, built-in backup via GitHub, no infra to maintain. The tradeoff is that it's a single-writer system. You've correctly locked this in with "Pi as sole writer," but it's worth internalizing *why* — it's not just a preference, it's a hard constraint of the architecture. If you ever want to add a second write path (phone app, travel laptop), you'll need a merge strategy or a different storage layer. For a personal diary, this is fine indefinitely. Know where the ceiling is.

### 2. The async push gap is your main operational risk

The window between "CSV committed locally" and "CSV pushed to GitHub" is the only real failure mode in this system. Everything else is stateless or recoverable. The unpushed-commit counter in `/api/health` handles observability. The `Restart=always` systemd config handles recovery. The write ordering (commit before responding, push async) handles data safety. These three things together make the async gap manageable. If you find yourself wanting more — e.g., push retries with backoff — that's a signal the Pi's internet connection is unreliable, and the right fix is network stability, not retry logic.

### 3. GitHub Pages + CSV export is the right read path

The alternative would be exposing the Pi's FastAPI to the internet with auth. That's more complexity, more attack surface, and requires the Pi to be reachable from outside your LAN. The Pages approach gives you a read-only public URL for free, with no Pi exposure. The only downside is staleness (one push lag), which doesn't matter for a diary. Stick with it.

### 4. TMDb provider reuse for TV is clean — but test the credits endpoint

The movie and TV TMDb endpoints are similar but not identical. Movie credits use `/movie/{id}/credits`; TV credits use `/tv/{id}/credits` and return `created_by` rather than a `crew` list for director. When you implement `tmdb_tv.py`, the provider interface stays the same (`search`, `lookup` returning standardized fields), but the internal extraction logic differs. Build `tmdb_movie.py` with a clear internal interface so `tmdb_tv.py` is a clean subclass or parallel implementation, not a copy-paste with hacks.

### 5. `export_json.py` is a natural place to add computed fields

Right now it's a mechanical CSV → JSON converter. But since it runs on every push, it's also a good place to add fields the browser can use without recomputing: `total_watched`, `average_rating`, `watched_this_year`. These make the Pages viewer more useful with no additional infra. Worth designing `export_json.py` to output a metadata block alongside the entries array from the start:

```json
{
  "meta": { "total": 142, "avg_rating": 7.8, "exported_at": "2025-07-31T..." },
  "entries": [ ... ]
}
```

### 6. Keep `static/index.html` and `docs/index.html` as genuinely separate concerns

The write UI (`static/index.html`) is served by FastAPI from the Pi, behind your LAN. The read UI (`docs/index.html`) is served by GitHub Pages, publicly. Don't try to merge them into one file with conditional logic — they have different data sources, different auth requirements, and will diverge over time. Two files is cleaner.

### 7. The config registry pattern will pay off — don't shortcut it in v1

It's tempting to hardcode a few things for movies in v1 and "clean it up later." Don't. The generic route pattern (`/api/{type}/entries`) and the registry lookup (`MEDIA_TYPES[type]`) are what make adding books a config change rather than a code change. If you hardcode even one `if type == "movies"` in the router, you'll have two by the time you add books. Treat the registry as the authority from day one.

---

## What we're not doing

- Synology SMB mount (git replaces this)
- Separate repo per media type (one repo scales cleaner)
- Client-side API keys on GitHub Pages
- Heavy frameworks (React, k3s) for a personal form app
- Breaking existing movie CSV format or recommendation script behavior
- Exposing port 8765 to the internet without auth
- Background push retry loops (retry on next user action instead)
- Offline write queuing (Pi offline = can't add entries; this is intentional)