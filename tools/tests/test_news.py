import copy
import json
import re
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_news
import render_news
import validate_news


CONFIG = json.loads((ROOT / "scripts/news-config.json").read_text())
STAMP = "2026-10-09T12:00:00+00:00"
RSS = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>test</title>
<item><title>Same headline</title><link>https://example.com/story</link><pubDate>Fri, 09 Oct 2026 11:00:00 GMT</pubDate></item>
<item><title>Same headline</title><link>https://example.com/story</link></item>
<item><title>Second &amp; safe</title><link>https://example.com/second</link></item>
</channel></rss>'''


class NewsTests(unittest.TestCase):
    def test_success_deduplicates_and_keeps_headlines_only(self):
        result = fetch_news.refresh(CONFIG, None, fetch=lambda spec: fetch_news.parse_headlines(RSS, spec["limit"]), now=STAMP, budget=2)
        self.assertEqual(result["feeds"][0]["status"], "ok")
        self.assertEqual(len(result["feeds"][0]["items"]), 2)
        self.assertEqual(set(result["feeds"][0]["items"][0]), {"title", "url", "date"})
        self.assertEqual(result["feeds"][0]["items"][0]["date"], "2026-10-09")
        self.assertTrue(validate_news.validate_digest(result, CONFIG))

    def test_partial_failure_retains_last_good_rows(self):
        old = fetch_news.refresh(CONFIG, None, fetch=lambda spec: fetch_news.parse_headlines(RSS, spec["limit"]), now=STAMP, budget=2)
        def flaky(spec):
            if spec["id"] == "npr-top":
                raise OSError("fixture failure")
            return fetch_news.parse_headlines(RSS, spec["limit"])
        result = fetch_news.refresh(CONFIG, old, fetch=flaky, now="2026-10-09T13:00:00+00:00", budget=2)
        self.assertEqual(result["feeds"][0]["status"], "stale")
        self.assertEqual(result["feeds"][0]["items"], old["feeds"][0]["items"])
        self.assertEqual(result["feeds"][1]["status"], "ok")

    def test_all_failure_and_empty_initial_snapshot(self):
        result = fetch_news.refresh(CONFIG, None, fetch=lambda _: (_ for _ in ()).throw(OSError("down")), now=STAMP, budget=2)
        self.assertTrue(all(row["status"] == "unavailable" and not row["items"] for row in result["feeds"]))
        self.assertIsNone(result["generatedAt"])
        self.assertTrue(validate_news.validate_digest(result, CONFIG))
        old = fetch_news.refresh(CONFIG, None, fetch=lambda spec: fetch_news.parse_headlines(RSS, spec["limit"]), now=STAMP, budget=2)
        stale = fetch_news.refresh(CONFIG, old, fetch=lambda _: (_ for _ in ()).throw(OSError("down")), now="2026-10-10T12:00:00+00:00", budget=2)
        self.assertTrue(all(row["status"] == "stale" for row in stale["feeds"]))
        self.assertEqual(stale["generatedAt"], old["generatedAt"])
        self.assertEqual([row["items"] for row in stale["feeds"]], [row["items"] for row in old["feeds"]])

    def test_total_deadline_is_honored_when_worker_stalls(self):
        def slow(_spec):
            time.sleep(0.4)
            return fetch_news.parse_headlines(RSS, 8)
        started = time.monotonic()
        result = fetch_news.refresh(CONFIG, None, fetch=slow, now=STAMP, budget=0.05)
        self.assertLess(time.monotonic() - started, 0.25)
        self.assertTrue(all(row["status"] == "unavailable" for row in result["feeds"]))

    def test_schema_identity_limits_timestamps_and_urls_fail_closed(self):
        result = fetch_news.refresh(CONFIG, None, fetch=lambda spec: fetch_news.parse_headlines(RSS, spec["limit"]), now=STAMP, budget=2)
        broken = copy.deepcopy(result); broken["feeds"][0]["id"] = "different"
        with self.assertRaises(ValueError): validate_news.validate_digest(broken, CONFIG)
        broken = copy.deepcopy(result); broken["feeds"][0]["items"][0]["url"] = "file:///etc/passwd"
        with self.assertRaises(ValueError): validate_news.validate_digest(broken, CONFIG)
        broken = copy.deepcopy(result); broken["feeds"][0]["items"] = []
        with self.assertRaises(ValueError): validate_news.validate_digest(broken, CONFIG)
        broken = copy.deepcopy(result); broken["feeds"][0]["lastAttemptAt"] = "yesterday"
        with self.assertRaises(ValueError): validate_news.validate_digest(broken, CONFIG)
        badconfig = copy.deepcopy(CONFIG); badconfig["feeds"][0]["limit"] = 99
        with self.assertRaises(ValueError): validate_news.validate_config(badconfig)
        for url in ("http://127.0.0.1/rss", "https://user@example.org/rss", "https://example.org:8443/rss", "http://[bad/rss"):
            with self.assertRaises(ValueError): validate_news.public_url(url)

    def test_static_renderer_escapes_content_has_pagination_and_no_js_fallback(self):
        config = copy.deepcopy(CONFIG)
        for spec in config["feeds"][:3]: spec["category"] = "top"
        old = fetch_news.refresh(config, None, fetch=lambda spec: fetch_news.parse_headlines(RSS, spec["limit"]), now=STAMP, budget=2)
        counts = (8, 8, 8)
        for feed_index, amount in enumerate(counts):
            old["feeds"][feed_index]["items"] = [{"title": f"Headline {feed_index}-{i}", "url": f"https://example.com/{feed_index}-{i}", "date": "2026-10-09"} for i in range(amount)]
        old["feeds"][0]["items"][0]["title"] = '<img src=x onerror="bad">'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "scripts").mkdir()
            (root / "scripts/news-config.json").write_text(json.dumps(config))
            (root / "news-digest.json").write_text(json.dumps(old))
            (root / "news.html").write_text('<!doctype html><html><body><!-- NEWS_SECTIONS --><!-- GENERATED_AT --></body></html>')
            outputs = render_news.render(root)
        output = outputs["news.html"]
        self.assertIn("&lt;img src=x onerror=&quot;bad&quot;&gt;", output)
        self.assertNotIn('<img src=x onerror="bad">', output)
        self.assertIn("NEWS_PAGE_COUNTS", output)
        self.assertIn('href="news-top-2-full.html"', output)
        self.assertIn('href="news-top-1-compact.html"', output)
        self.assertIn('href="news-top-2-compact.html"', outputs["news-top-2-full.html"])
        self.assertIn("news-tech-1-full.html", outputs)
        self.assertIn("news-tech-1-compact.html", outputs)
        source = (ROOT / "news.html").read_text()
        self.assertIn("NEWS_SECTIONS", source)
        self.assertIn("compact", source)
        self.assertIn("URLSearchParams", source)
        self.assertEqual(output.count('<article class="headline"'), 20)
        second_page = outputs["news-top-2-full.html"]
        self.assertEqual(second_page.count('<article class="headline"'), 4)
        compact = outputs["news-top-1-compact.html"]
        self.assertEqual(compact.count('<article class="headline"'), 8)
        self.assertEqual(outputs["news-top-2-compact.html"].count('<article class="headline"'), 8)
        self.assertEqual(outputs["news-top-3-compact.html"].count('<article class="headline"'), 8)
        compact_links = [outputs[f"news-top-{page}-compact.html"] for page in (1, 2, 3)]
        self.assertEqual(sum(page.count('<article class="headline"') for page in compact_links), 24)
        for body in outputs.values():
            for href in re.findall(r'href="([^"]+)"', body):
                if href.startswith("news") and not href.startswith("https://"):
                    self.assertIn(href, outputs, f"broken static news link: {href}")


if __name__ == "__main__":
    unittest.main()
