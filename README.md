# Media Diary public apps

This repository builds the read-only public media diary at the existing project root and the personal tools hub at `/media-diary/tools/`. The separate career site remains at its existing `Portfolio` URL.

The public diary exporter reads six CSVs in `data/` and exports only the approved fields in `public_diary/presentation.py`: title, date, release/publication date, rating, creator (director, author or show creator), and the optional `Note` field (up to 2,000 characters). Notes are intentionally public and appear on individual entry detail pages. Older CSVs without a `Note` header remain valid and export an empty note. Ratings, dates and watch/read lists are public. Review those records before committing changes.

Tool feed inputs are public too. `tools/sub.yaml` lists podcast subscriptions; `tools/scripts/reddit-config.json` lists selected communities and feed types; `tools/scripts/news-config.json` selects RSS news sources/categories; `tools/sports-config.json` selects leagues. The news digest, podcast manifest and Reddit digest contain feed results and timestamps and are published as JSON. News headlines are rendered into static HTML during the build and do not call a proxy at page load. Weather city choice, compact mode, game progress and high scores stay in browser localStorage and are not included in the artifact. The browser uses the same GitHub Pages origin as the career site, so localStorage is shared by both project paths.

## Build and verify

Build with Python's standard library only:

```sh
python3 scripts/build_public.py --output /tmp/media-diary-site
```

The output must be fresh or empty. `_site/` is the only supported output inside the repository. The builder stages to a temporary sibling and publishes only the explicit diary/tool page, asset and JSON allowlists. It does not copy source scripts, feed configuration, tests or CSV files into the Pages artifact.

Run the static artifact checks with:

```sh
python3 -m unittest discover -s tests
```

Feed generator tests need `tools/requirements-podcast.txt`. Fetch jobs must validate generated manifests/digests before publishing them. Do not run the fetchers when testing a build; fixtures cover feed behavior without live requests.

The games preserve their existing localStorage keys. The legacy Portfolio score JSON files are not consumed by the game pages and are not included in the combined source or artifact.

## Daily tools

`tools/today.html` combines current weather, three published top headlines and configured favorite-team games. Sections load independently and provide their own error/retry states. Weather defaults to Atlanta and honors the existing device-local city preference. It never requests device location automatically.

`tools/schedule.html` shows upcoming games returned by the published scoreboards within the next seven days, with device-local kickoff times and broadcast names where supplied. It explicitly describes scoreboard coverage; a missing game is not evidence that a team has no upcoming fixture. League and favorite filters are ordinary native controls. Favorite aliases match complete provider team names or abbreviations, preventing Michigan State from matching Michigan.

Feed health reports and their refresh scheduler remain private Mac operations files, outside this repository and the Pages artifact.

## Sports data

Scores fetch current scoreboards directly from ESPN's browser-accessible `site.web.api.espn.com` host when opened, with at most three requests running at once. Selected leagues and favorite games that are live or starting soon can refresh every minute while the page is visible. Retrieval times describe when the browser received data. Failed requests retain saved results or fall back to `tools/sports-snapshot.json`, with errors and original timestamps shown. No new public server or API key is required.

Standings, Today and schedule still read the published snapshot. The sports workflow requests a refresh every 15 minutes, but GitHub scheduling and deployment can add substantial delay. Each endpoint retains its last successful data on refresh failure. The direct ESPN routes are unofficial and can change; the snapshot remains an important fallback.

The collector uses no provider credentials and keeps only the fields needed by the renderers. Sports, news, podcast, Reddit and ordinary Pages deployments share one publication queue and always build the full current site. Only Actions owns these schedules; a future Mac collector must replace that ownership rather than create a second publisher. Keep private APIs, runtime state and credentials in the private backend/deployment workspace.

## Nokia-first presentation

At keypad widths, the tools home shows short destination rows. Today leads with current weather and a favorite-team game; weather city controls and diary sort/year filters use native disclosures. Podcasts use a native show picker, keep episode progress on the device, and offer Continue listening when saved progress is available. Reload episode list reads the published manifest; it does not collect a new feed.

Bible chapters load when selected. Verse choices come from the returned chapter, passage hashes support Back/bookmarks, and the last passage is saved only in this browser for explicit resume. Reddit compact browsing starts with one community, offers native feed selection and dated saved snapshots, and keeps refresh reasons in a disclosure. Its collector still stops after a provider access denial or rate limit; rotating the first probe improves coverage but cannot guarantee fresh posts.

Games preserve their storage keys and scoped key capture. Snake/Tetris have explicit Start and Resume states and pause when leaving play; Wordle puts native text entry before the optional on-screen keyboard. The 2048 board retains explicit square fallbacks for older browsers.

Score-display fixtures run with `node tools/tests/test_score_display.js`. Browser viewport checks are useful layout evidence, but physical Nokia rendering, keypad behavior and podcast audio still need handset verification.
