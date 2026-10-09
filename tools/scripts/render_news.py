#!/usr/bin/env python3
"""Render validated news data to bounded, self-contained category pages."""
import argparse
import html
import json
import math
from pathlib import Path

try:
    from .validate_news import validate_digest
except ImportError:  # Supports direct script execution from workflow steps.
    from validate_news import validate_digest

CATEGORY_NAMES = {"top": "Top", "general": "World", "tech": "Tech", "sports": "Sports", "business": "Business", "science": "Science", "devops": "DevOps"}
PAGE_SIZES = {"full": 20, "compact": 8}


def esc(value):
    return html.escape(str(value), quote=True)


def route(category, page, mode):
    if category == "top" and page == 1 and mode == "full":
        return "news.html"
    return f"news-{category}-{page}-{mode}.html"


def render(root: Path, config_path=None):
    root = Path(root)
    template_path = root / "news.html"
    digest_path = root / "news-digest.json"
    config_path = Path(config_path) if config_path else root / "scripts/news-config.json"
    template = template_path.read_text(encoding="utf-8")
    marker = "<!-- NEWS_SECTIONS -->"
    if template.count(marker) != 1:
        raise ValueError("news.html must contain exactly one NEWS_SECTIONS marker")
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_digest(digest, config)

    collected = {}
    statuses = {}
    for category in config["categories"]:
        entries, seen, notes = [], set(), []
        for row in digest["feeds"]:
            if row["category"] != category:
                continue
            if row["status"] != "ok":
                notes.append(row["name"] + " (" + row["status"] + ")")
            for item in row["items"]:
                key = (" ".join(item["title"].split()).casefold(), item["url"].rstrip("/").casefold())
                if key not in seen:
                    seen.add(key)
                    entries.append((row["name"], item))
        collected[category] = entries
        statuses[category] = notes

    outputs = {}
    page_counts = {}
    for category in config["categories"]:
        count = len(collected[category])
        page_counts[category] = {mode: max(1, math.ceil(count / page_size)) for mode, page_size in PAGE_SIZES.items()}
    # Full and compact modes page through every approved category headline.
    # All route links remain static HTML.
    for category in config["categories"]:
        heading = CATEGORY_NAMES.get(category, category.title())
        for mode, page_size in PAGE_SIZES.items():
            entries = collected[category]
            pages = max(1, math.ceil(len(entries) / page_size))
            for page in range(1, pages + 1):
                first = (page - 1) * page_size
                visible = entries[first:first + page_size]
                article_markup = []
                for source, item in visible:
                    article_markup.append('<article class="headline"><a href="%s" rel="noopener noreferrer">%s</a><div class="headline-meta">%s%s</div></article>' % (
                        esc(item["url"]), esc(item["title"]), esc(source), " · " + esc(item["date"]) if item["date"] else ""))
                if not visible:
                    article_markup.append('<p class="empty">No headlines are available in this category.</p>')
                nav = []
                for other in config["categories"]:
                    current = other == category
                    other_category_page = min(page, page_counts[other][mode])
                    nav.append('<a class="category-link" href="%s"%s>%s</a>' % (
                        esc(route(other, other_category_page, mode)), ' aria-current="page"' if current else "", esc(CATEGORY_NAMES.get(other, other.title()))))
                other_mode = "full" if mode == "compact" else "compact"
                other_page = min(page, page_counts[category][other_mode])
                links = ['<a class="%s" href="%s">%s</a>' % (
                    "full-link" if mode == "compact" else "compact-link",
                    esc(route(category, other_page, other_mode)),
                    "Full view" if mode == "compact" else "Compact" )]
                if pages > 1:
                    for number in range(1, pages + 1):
                        links.append('<a class="page-link" href="%s"%s>%d</a>' % (
                            esc(route(category, number, mode)), ' aria-current="page"' if number == page else "", number))
                status = '<p class="status">Some feeds are using saved headlines or are temporarily unavailable: %s.</p>' % esc(", ".join(statuses[category])) if statuses[category] else ""
                replacement = '<script>window.NEWS_PAGE_COUNTS=%s;</script><nav class="category-links" aria-label="News categories">%s</nav><nav class="pager" aria-label="News pages and display mode">%s</nav><div class="cache-info">Updated %s · collection attempted %s</div><main class="category%s" id="cat-%s"><h2>%s</h2>%s%s</main>' % (
                    json.dumps(page_counts), "".join(nav), "".join(links), esc(digest.get("generatedAt") or "not yet"), esc(digest["lastAttemptAt"]), " compact" if mode == "compact" else "", esc(category), esc(heading), "".join(article_markup), status)
                page_html = template.replace(marker, replacement).replace("<!-- GENERATED_AT -->", esc(digest.get("generatedAt") or "not yet"))
                outputs[route(category, page, mode)] = page_html
    for filename, body in outputs.items():
        destination = root / filename
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(body, encoding="utf-8")
        temporary.replace(destination)
    return outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path, help="Configuration used to validate the digest; can remain outside the public artifact")
    args = parser.parse_args()
    outputs = render(args.root, args.config)
    print(f"Rendered {len(outputs)} static news pages")


if __name__ == "__main__":
    main()
