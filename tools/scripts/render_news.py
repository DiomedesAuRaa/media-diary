#!/usr/bin/env python3
"""Render validated news data to bounded, self-contained category pages."""
import argparse
import html
import json
import math
import re
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


def validate_rendered_routes(outputs):
    """Fail a build if generated static navigation points at a missing page."""
    for filename, body in outputs.items():
        root = re.search(r'<html\b([^>]*)>', body)
        if not root:
            raise ValueError(f"Rendered route has no html root: {filename}")
        attrs = root.group(1)
        category = re.search(r'data-news-category="([a-z0-9-]+)"', attrs)
        page = re.search(r'data-news-page="([1-9][0-9]*)"', attrs)
        if not category or not page:
            raise ValueError(f"Rendered route lacks category/page metadata: {filename}")
        is_default = filename == "news.html"
        if is_default:
            if category.group(1) != "top" or page.group(1) != "1" or "data-compact=" in attrs:
                raise ValueError("Default news.html must remain top page 1 with automatic compact selection")
        else:
            named = re.fullmatch(r"news-([a-z0-9-]+)-([1-9][0-9]*)-(full|compact)\.html", filename)
            if not named or named.group(1) != category.group(1) or named.group(2) != page.group(1):
                raise ValueError(f"Filename and route metadata disagree: {filename}")
            mode = "compact" if filename.endswith("-compact.html") else "full"
            expected = f'data-compact="{1 if mode == "compact" else 0}"'
            if expected not in attrs or (mode == "compact") != ('class="compact"' in attrs):
                raise ValueError(f"Compact declaration does not match static route: {filename}")
        for href in re.findall(r'href="([^"]+)"', body):
            if href.startswith("news") and not href.startswith("https://"):
                target = re.split(r"[?#]", href, 1)[0]
                if target not in outputs:
                    raise ValueError(f"Broken static news link in {filename}: {href}")


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
                replacement = '<script>window.NEWS_PAGE_COUNTS=%s;</script><nav class="category-links" aria-label="News categories">%s</nav><main class="category%s" id="cat-%s"><h2>%s</h2>%s%s</main><nav class="pager" aria-label="News pages and display mode">%s</nav><div class="cache-info">Collection attempted %s</div>' % (
                    json.dumps(page_counts), "".join(nav), " compact" if mode == "compact" else "", esc(category), esc(heading), "".join(article_markup), status, "".join(links), esc(digest["lastAttemptAt"]))
                page_html = template.replace(marker, replacement).replace("<!-- GENERATED_AT -->", esc(digest.get("generatedAt") or "not yet"))
                root_attrs = f'data-news-category="{esc(category)}" data-news-page="{page}"'
                if route(category, page, mode) != "news.html":
                    root_attrs += f' data-compact="{1 if mode == "compact" else 0}"'
                    if mode == "compact":
                        root_attrs += ' class="compact"'
                page_html, replacements = re.subn(r'<html\b([^>]*)>', lambda match: f'<html{match.group(1)} {root_attrs}>', page_html, count=1)
                if replacements != 1:
                    raise ValueError("news.html template must contain an html root element")
                outputs[route(category, page, mode)] = page_html
    validate_rendered_routes(outputs)
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
