# Media diary workspace guidance

## Product and deployment boundaries

- The diary has a home-LAN writer and an independent public read-only GitHub Pages viewer. Remote editing is intentionally off. Keep this split unless the user explicitly changes it; never expose mutation/search routes through the public viewer.
- Confirm the authoritative source checkout before editing. The cloud-synced checkout may be stale and contain unrelated user CSV edits. Preserve those edits and do not replace current deployment fixes with older source.
- The Pi writer was migrated and removed on 2026-10-08. Do not resurrect it or run two writers. Runtime data and credentials are separate from application source; the production image executes immutable application/static code.
- Source changes, the runtime Git checkout, and public exports are different scopes. Never run tests against production CSVs or stage application changes through the data publisher. Application deployment does not replace the runtime data directory.

## UX and device requirements

- Support laptop, iPhone and Nokia 2780 in its normal browser. Use shared information hierarchy with a compact, bookmarkable presentation; do not assume installed KaiOS app softkeys or that viewport emulation proves handset support.
- Keep browsing and logging distinct. Changing a browse category must not silently change an open draft's category or selected provider metadata. Preserve drafts on failure and offer explicit cancellation.
- Completed logs and future lists need different fields/actions. Use contextual To read/To watch or shared For later labels. Preserve intentional rewatches/rereads; make updating an existing rating an explicit operation.
- Native forms/links provide the reliable baseline; JavaScript may enhance them. Keep useful records near the top, paginate long lists, preserve URLs/Back, use native compact rating controls and comfortable iPhone targets.
- Selected state, rating groups, errors/loading/success and focus must be accessible. Avoid removing the focused element during updates. Disable duplicate submissions while pending; do not claim a local save means Pages has deployed.
- Dates use local calendar time. Editing must identify the original record independently of a new date. Preserve 1–10 rating meaning and the existing CSV schema unless an explicitly reviewed migration requires otherwise.

## Storage, Git and recovery lessons

- Exactly six CSVs currently hold ratings and future lists for movies/books/TV. Serialize duplicate-check/read/write operations and use atomic replacement with flush/fsync. Run one application worker unless concurrency design is deliberately changed.
- A single bounded publication worker stages only the explicit data allowlist, including watchlists. Never stage all files or commit unrelated staged code. A failed push must retry already committed changes even without a new diff; persist and expose sanitized publication status.
- Keep Git network operations outside the short CSV write lock where safe. Bound subprocess/network calls, disable interactive credential prompts, fail closed on divergence and never force-push or automatically merge CSV conflicts.
- Preserve last-good public output on generation errors. Public JSON/HTML must use explicit dataset/field/asset allowlists, not indiscriminate copying of the repository.
- Recovery snapshots must include local/unpushed CSV data plus consistent Git state. Verify restore with hashes and Git integrity. Image rollback alone is not data recovery; stop the writer and reconcile new saves before any restore.
- Local snapshots are not off-host protection. Preserve original migration checkpoints separately from rotating daily archives. Backups/secrets must never be staged or published.

## Security and verification

- LAN editing currently relies on trusted home-network access, not application authentication. Keep the listener on the intended LAN interface and preserve independent health/readiness checks. Do not mount the Docker socket, NAS media share or VPN namespace for this app.
- Never print or commit credential values, private keys, environment files or credential-bearing errors/URLs. Use protected credential files and a repository-scoped publishing credential. Provider exceptions can contain API-key query strings; expose sanitized messages only.
- Treat titles, metadata, feeds and external URLs as untrusted: text rendering/escaping appropriate to context, safe URL schemes and no interpolated inline handlers. Preserve the migration's injection/error-redaction fixes.
- Ratings, watched/read dates and future interests are public if exported or tracked in a public repo. Confirm intended disclosure; hidden UI fields/links are not privacy controls and current-file deletion does not erase history.
- Start with Git status and preserve existing work. Audit-only tasks do not mutate deployments; when implementation is authorized, complete scoped tests and deployment without adding unnecessary approval gates. Do not restart unrelated services or reload the main stack LaunchAgent.
- Use disposable CSVs and local bare Git remotes for meaningful mutation/concurrency/retry/recovery tests. Use isolated preview state for browser/form tests; never publish fixture entries into the user's diary.
- Verify API compatibility, full pagination, search/manual logging, all three media types, repeats/edits/deletes, future-list completion, failed publication recovery, generated public artifacts and restart persistence. State when actual handset, reboot/sleep, router or off-host recovery checks were not performed.
