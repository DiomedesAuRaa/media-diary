# Media Diary

A personal movies, books and TV diary with ratings, rewatches, editing, deletion and per-category watchlists. Metadata comes from TMDb and Open Library. The editable app runs on the home LAN; GitHub Pages is a public read-only snapshot.

## Current deployment

The writer is deployed with Docker Desktop on the Mac mini at **http://192.168.1.131:8765**. Public browsing remains at **https://diomedesauraa.github.io/media-diary/**. Remote editing is disabled. See [DEPLOYMENT-MAC-MINI.md](DEPLOYMENT-MAC-MINI.md) for this Mac's paths, startup, backups, testing and recovery instructions. `compose.mac-mini.yml` records its deployment configuration; the active standalone project is under `/Users/josh/Desktop/media-stack/media-diary` and is separate from the main media stack updater.

The app immediately saves to six CSVs: ratings and watchlists for movies, books and TV. One background worker commits only those files and pushes to main. Failed pushes retry every minute and after restart, including already-committed changes. GitHub Actions tests the application, exports CSVs as JSON and publishes `docs/`. A local save, a Git push and a Pages deployment are separate stages.

CSV mutations are serialized and use atomic replacement. Run one Uvicorn worker. The LAN browser retrieves all ratings through pagination. UI data is escaped, provider/Git failures are sanitized, and the home form shows publication status. `/health` is liveness, `/ready` checks data accessibility, and `/api/types` includes publication and local-backup status.

## Local development

Use a normal local folder outside cloud sync. Python 3.12 is tested. Create a virtual environment and install `requirements.lock`, then configure `.env` from `.env.example`, leaving `GIT_SYNC_ENABLED=false` for disposable/local testing. Run `./run.sh` and open port 8765. The convenience script uses reload; Docker production does not.

Movies/TV require a TMDb API key. Books use Open Library without a key. `scripts/recommendations.py` is a separate optional Gemini CLI, not part of the API or Pages build. `python scripts/export_json.py` generates viewer JSON locally.

| Setting | Purpose |
|---|---|
| `TMDB_API_KEY` / `TMDB_API_KEY_FILE` | Metadata credential; a configured file takes precedence |
| `GIT_SYNC_ENABLED` | Enable the serialized publisher; default false |
| `REPO_ROOT` | Runtime Git checkout; defaults to application root for development |
| `DATA_ROOT` | CSV directory; defaults to `REPO_ROOT/data` |
| `GIT_REMOTE` / `GIT_BRANCH` | Publishing remote/branch, defaults origin/main |
| `GIT_SSH_COMMAND` | Protected SSH deploy-key and known-hosts configuration |
| `SYNC_STATE_PATH` | Persistent publication status file |
| `BACKUP_ROOT` | Optional daily CSV/Git snapshots, newest 14 retained |
| `GEMINI_API_KEY` | Optional recommendations CLI only |

Use an appropriately scoped credential for publication, such as the Mac's write-enabled repository deploy key. Embedded PAT URLs are no longer used by the publisher. Do not commit `.env`, private keys, credentials or runtime snapshots. Only one installation may write the diary. Changes pushed from another clone require deliberate reconciliation; the worker never force-pushes or automatically merges CSVs.

## Verification

Run `python -m unittest discover -s tests -v`. Tests use disposable data and local bare Git repositories; they do not contact production GitHub or providers. The Pages workflow runs the same suite before deployment. Python dependencies and the Docker base image are pinned; upgrades require review and rerunning tests.

The old `media-diary.service` file remains as a historical Pi template, not the current deployment. LAN editing retains the existing home-network trust model and has no application login. No public API route or remote editing tunnel is configured.
