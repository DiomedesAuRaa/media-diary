# Media Diary

A personal diary for movies, books and TV, with a home-network editor and a public read-only GitHub Pages viewer. Remote editing is intentionally off.

## Browse and log

The home editor opens directly to a searchable, paginated diary. Use Movies, Books, TV or All; switch between Diary and For later, then sort by recent consumption, rating or title. Log something opens a separate form. Native links, rating selects and HTML forms work without JavaScript; optional enhancement preserves drafts in the current browser tab, defaults dates to the device's local calendar and prevents repeated Save clicks.

Open an entry to edit it, log another viewing/reading, or remove it. A for-later entry can become a completed log; removal from the future list happens only after the completed log is saved. Editing uses the original row identity so changing its date does not select a different viewing.

`?compact=1` selects the compact home interface. Public `compact.html` provides the compact viewer with pre-rendered entries and real page links for the Nokia 2780 browser. The full viewer supports laptop and iPhone layouts. Public search uses JavaScript; category, sorting and page links also work without it. Physical handset testing remains necessary; viewport emulation alone does not certify a device.

## Public data and architecture

Exactly six datasets are published: ratings and future lists for movies, books and TV. Titles, ratings, reading/watching dates and creator/release metadata are deliberately public. `app/presentation.py` declares the approved fields; `scripts/export_json.py` exports only those fields and generates a fresh read-only publication directory containing known JSON, HTML and CSS/JavaScript assets. Generation failures preserve the last good output.

The FastAPI API remains compatible with `/api/{media_type}/entries`, `/watchlist` and `/search`. The HTML interface uses `/`, `/record`, `/log`, `/save` and `/remove`. The home API relies on a trusted LAN; it must not be exposed publicly. HTML mutations use signed expiring form tokens and same-origin checks, while the existing JSON API remains available to trusted clients.

CSV writes are serialized and atomically replaced. One application worker owns writes and a bounded Git publishing worker. Publishing stages only the six CSVs and retries failed pushes. Credentials, runtime Git state, backups and machine-specific operations belong outside this public source tree; deployment guidance is maintained separately by the operator.

## Development and validation

Use Python 3.12 and install `requirements.lock` into an isolated environment. Set `DATA_ROOT`/`REPO_ROOT` to disposable fixtures and `GIT_SYNC_ENABLED=false` for previews. Never test writes against production CSVs.

```sh
python -m unittest discover -s tests -q
python scripts/export_json.py
```

The tests use temporary storage and local Git remotes to verify concurrent saves, publishing retries, backup recovery, native forms, exact edits, repeated submissions, completion safety and publication boundaries.
