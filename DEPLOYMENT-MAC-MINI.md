# Media diary on this Mac

The editable diary runs as the standalone `media-diary` Compose project on Docker Desktop. Home URL: http://192.168.1.131:8765. Public read-only URL: https://diomedesauraa.github.io/media-diary/.

`compose.yml` is the active deployment. Application source is in `source/`, a separate Git clone; image `media-diary:mac-mini-v1` contains application/static code and locked Python dependencies. Runtime data and Git state are in `~/Library/Application Support/media-stack/media-diary/repo`, publication status in `status/`, protected credentials in `secrets/`, and recovery snapshots in `backups/`. Do not print or commit credentials. The Synology Drive checkout is not runtime storage.

The LAN address is deliberately explicit. Reserve 192.168.1.131 for this Mac in the router. Changing the address requires updating Compose's port binding. No public API, remote editing tunnel, or router port forward is part of this setup. Home-LAN access retains the previous trust model without app login.

## Routine operations

- `./start.sh` starts or reconciles only this diary service. It never updates the main media stack.
- `docker compose -f compose.yml ps` shows state. Safe configuration validation is `docker compose -f compose.yml config --quiet`.
- To stop the writer for recovery/maintenance, use `docker compose -f compose.yml stop media-diary`.
- A restart uses `docker compose -f compose.yml restart media-diary`. The restart policy handles Docker daemon recovery for an already-created service. This project is intentionally outside the main stack's updater and NAS/VPN gate.
- No automatic application/image upgrades are installed. Review changes in `source/`, test against disposable state, build a new versioned image, and apply only this service. Preserve the previous image and a consistent pre-upgrade data/Git backup. Image rollback alone does not undo data changes.

The app serializes and atomically replaces CSVs. One publication worker stages only the six allowed CSVs, commits changes and retries pushes every minute even without another save. Local saves work during a GitHub outage. `/api/types` exposes sanitized publication and backup status; the home UI shows pending or delayed public updates. GitHub Actions builds Pages after a push; successful push is distinct from successful Pages deployment. The worker does not pull or merge remote edits; divergence fails closed and needs reconciliation.

## Backups and recovery

The publication worker creates a daily UTC snapshot of all six CSVs plus their Git history/index under the same write lock, after its bounded Git operation finishes. It retains the newest 14 `diary-YYYY-MM-DD.tar.gz` archives. Initial/final Pi checkpoints and deployment checkpoints have separate names and are retained. Snapshots include unpublished data. Credentials are separate protected files and are not in the repository archives.

These snapshots are local recovery copies; GitHub is the off-host copy of successfully pushed CSVs and application code. For recovery after disk loss, preserve the protected credentials securely or provision replacement credentials, and arrange an independent backup of local snapshots if unpublished changes must survive disk loss. Do not run two writers or restore files into a running writer.

Restore procedure:

1. Stop only `media-diary`; retain the current runtime repo and status directory as a checkpoint.
2. Extract a selected archive into a new temporary directory. Check its `backup-manifest.json` hashes and run `git fsck --no-dangling` on the extracted repo.
3. Restore `repo/data` and `repo/.git` together into the runtime repo, with permissions for host UID 501/GID 20. Older Pi checkpoints include the full repository. Preserve data that exists only in the current runtime before replacement.
4. Compare restored local history with GitHub. Resolve divergence deliberately; never force-push or blindly reset unpublished CSVs. Keep the remote SSH URL and protected key/known-hosts mounts configured.
5. Start only the diary, check `/ready`, browse counts and publication status. Verify the matching Pages workflow succeeds.

Docker Desktop must be running and macOS awake for LAN editing. Its startup preference starts Docker at sign-in, not necessarily before login. No reboot, sleep-policy change or main-stack LaunchAgent reload was performed during this migration. The diary has no NAS mount or Gluetun dependency.

## Tests

Run `python -m unittest discover -s tests -v` from the source environment, or mount `source/tests` read-only at `/tests` in the built image and run discovery there. Tests use temporary CSVs and local bare Git remotes, never production data/GitHub. They cover concurrency, interrupted atomic replacement, all media mutation flows, pagination, watchlist publishing, failed-push recovery, unexpected staged files, provider-error redaction, readiness and restoring unpublished data/history.
