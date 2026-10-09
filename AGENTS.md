# Public apps repository guidance

This is the public, read-only diary viewer and the public Nokia-oriented tools/games collection. Keep the career Portfolio site separate at its established URL. Do not add LAN writer/API modules, credentials, runtime data, backups or operations files here.

The six files in `data/` are public diary data. The renderer exports only its explicit `PUBLIC_FIELDS`; do not broaden this allowlist without review. Feed selections in `tools/sub.yaml`, `tools/scripts/reddit-config.json`, `tools/scripts/news-config.json` and `tools/sports-config.json`, plus generated feed digests, are public preferences/content. Weather location overrides, compact-mode settings and game progress/scores stay local to the browser. Both project sites use the same browser origin, so preserve existing localStorage keys.

`python3 scripts/build_public.py --output _site` is the complete Pages build. Keep its output allowlists curated; never copy the repository recursively. Feed refresh scripts belong under `tools/scripts/`, tests under `tools/tests/`, and generated feed JSON at the corresponding paths in `tools/`. Validate feed output before publication and retain last-good data on failures.

Tools use shared assets in `tools/assets/`. Preserve semantic controls, visible amber focus, navy/teal surfaces, touch-sized controls, normal scrolling and ordinary browser navigation. On screens at or below 280px, compact controls may use the existing smaller target size. Keep game key capture scoped to active gameplay and do not capture keys from text fields or navigation.

Treat feed text and URLs as untrusted. Render text safely and allow only intended HTTP(S) destinations. Keep the World English Bible label accurate. Weather defaults to Atlanta; city overrides remain device-local and geolocation stays optional.

Dynamic services use ToolUI.fetch with a 12-second header/body deadline and existing retry/error states. Keep provider requests bounded and preserve weather/Bible request-version guards. News uses build-time static category/pagination routes with a durable validated digest. Pages and feed workflows share a publication queue and every deploy builds the full current-main artifact. Never deploy a tools-only artifact over the diary.
