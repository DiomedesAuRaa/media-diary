# Media Diary public apps

This repository builds the read-only public media diary at the existing project root and the personal tools hub at `/media-diary/tools/`. The separate career site remains at its existing `Portfolio` URL.

The public diary exporter reads six CSVs in `data/` and exports only the approved fields in `public_diary/presentation.py`: title, date, release/publication date, rating and creator (director, author or show creator). Ratings, dates and watch/read lists are public. Review those records before committing changes.

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
