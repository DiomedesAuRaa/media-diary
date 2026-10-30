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

All sports views use `tools/assets/sports-data.js`: scores, upcoming games, standings/rankings and favorite games on Today. ESPN remains the no-key provider because it covers the configured mix of professional, college, soccer and racing leagues. Its public site endpoints are unofficial, with no established stability guarantee; this integration does not provide an SLA.

The browser requests only the selected league or configured favorite leagues initially, through the browser-accessible `site.web.api.espn.com` host. One shared client handles at most three concurrent requests, in-flight reuse, deadlines, device caching, projection and saved snapshot fallback. Scores use explicit calendar dates. Upcoming games request each day separately because the tested date-range requests returned errors. NCAA query groups/limits are chosen from observed endpoint behavior, not assumed pagination. A completed date window means each requested date was fetched; it is not an independent guarantee of exhaustive provider coverage.

Provider event, competition and team IDs are retained. Favorite IDs are scoped by league; legacy snapshots without IDs remain supported. Each F1 competition is a distinct session, and scheduled sessions without drivers are valid. Retrieval times describe when data was received, not an invented provider update time. Failed refreshes preserve last-good provenance. No API key, subscription, new server or public access to the private diary writer is required.

The scheduled collector publishes a bounded multi-day fallback and standings/rankings. GitHub requests a refresh every 15 minutes, but scheduling and publishing delays mean the snapshot is not a live feed. Browser refreshes do not wait for a Pages deployment. All publishers still build the full curated site and share the existing publication queue.

Run client fixtures with `node tools/tests/test_sports_data.js` and collector fixtures with `python -m unittest discover -s tools/tests -p 'test_sports.py'`. Neither fixture suite fetches or publishes live data.

## Nokia-first presentation

At keypad widths, the tools home shows short destination rows. Today leads with current weather and a favorite-team game; weather city controls and diary sort/year filters use native disclosures. Podcasts use a native show picker, keep episode progress on the device, and offer Continue listening when saved progress is available. Reload episode list reads the published manifest; it does not collect a new feed.

Bible chapters load when selected. Verse choices come from the returned chapter, passage hashes support Back/bookmarks, and the last passage is saved only in this browser for explicit resume. Reddit compact browsing starts with one community, offers native feed selection and dated saved snapshots, and keeps refresh reasons in a disclosure. Its collector still stops after a provider access denial or rate limit; rotating the first probe improves coverage but cannot guarantee fresh posts.

Games preserve their storage keys and scoped key capture. Snake/Tetris have explicit Start and Resume states and pause when leaving play; Wordle puts native text entry before the optional on-screen keyboard. The 2048 board retains explicit square fallbacks for older browsers.

Score-display fixtures run with `node tools/tests/test_score_display.js`. Browser viewport checks are useful layout evidence, but physical Nokia rendering, keypad behavior and podcast audio still need handset verification.
