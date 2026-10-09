#!/usr/bin/env python3
"""Build a curated static diary and tools site into a fresh Pages directory."""
from __future__ import annotations
import argparse
import csv
import importlib.util
import json
import os
import re
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIARY_DATA = (
    'movies.json', 'books.json', 'tv.json',
    'movies_watchlist.json', 'books_watchlist.json', 'tv_watchlist.json',
)
DIARY_PAGES = ('index.html', 'compact.html')
DIARY_ASSETS = ('diary.css', 'diary.js')
TOOL_PAGES = (
    'home.html', 'today.html', 'schedule.html', 'bible.html', 'podcast-directory.html', 'reddit-digest.html',
    'news.html', 'weather.html', 'standings.html', 'sports-scores.html',
    'games/2048.html', 'games/minesweeper.html', 'games/snake.html',
    'games/tetris.html', 'games/wordle.html',
)
TOOL_DATA = ('podcast-manifest.json', 'reddit-digest.json', 'sports-config.json', 'sports-snapshot.json', 'news-digest.json')
TOOL_ASSETS = ('assets/tool-ui.css', 'assets/tool-ui.js', 'assets/game-ui.css', 'assets/today.js')

def assert_no_symlink_components(path: Path, boundary: Path):
    path, boundary = Path(path).absolute(), Path(boundary).absolute()
    if boundary.is_symlink():
        raise ValueError(f'Unsafe symlink source directory: {boundary}')
    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise ValueError(f'Source is outside its approved tree: {path}') from exc
    current = boundary
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f'Unsafe symlink source path: {current}')

def approved_source_files():
    files = [
        ROOT / 'scripts/build_public.py', ROOT / 'scripts/export_json.py',
        ROOT / 'public_diary/__init__.py', ROOT / 'public_diary/config.py',
        ROOT / 'public_diary/presentation.py',
        ROOT / 'public_diary/static/diary.css', ROOT / 'public_diary/static/diary.js',
    ]
    files.extend(ROOT / 'data' / name for name in ('movies.csv','books.csv','tv.csv','movies_watchlist.csv','books_watchlist.csv','tv_watchlist.csv'))
    tools = ROOT / 'tools'
    files.extend(tools / name for name in TOOL_PAGES + TOOL_DATA + TOOL_ASSETS)
    files.extend(tools / 'scripts' / name for name in (
        'fetch_feeds.py','fetch_reddit.py','fetch_news.py','validate_podcast.py',
        'validate_reddit.py','validate_news.py','validate_sports.py','render_news.py','reddit-config.json','news-config.json',
    ))
    return files

def validate_source_tree():
    # Check every file and each ancestor before imports, config reads, or subprocesses.
    for path in approved_source_files():
        assert_no_symlink_components(path, ROOT)

def copy_checked(source: Path, destination: Path, root: Path):
    if not source.is_file() or source.is_symlink():
        raise ValueError(f'Missing or unsafe public input: {source}')
    if ROOT == root or ROOT in root.parents:
        assert_no_symlink_components(source, ROOT)
    else:
        assert_no_symlink_components(source, root)
    if root.resolve() not in source.resolve().parents:
        raise ValueError(f'Public input escapes approved tree: {source}')
    if source.suffix == '.json':
        json.loads(source.read_text(encoding='utf-8'))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)

def validate_inputs(public_fields):
    validate_source_tree()
    for name in ('movies.csv','books.csv','tv.csv','movies_watchlist.csv','books_watchlist.csv','tv_watchlist.csv'):
        path = ROOT / 'data' / name
        if not path.is_file() or path.is_symlink() or ROOT.resolve() not in path.resolve().parents:
            raise ValueError(f'Missing or unsafe diary dataset: data/{name}')
        with path.open(encoding='utf-8', newline='') as handle:
            header = next(csv.reader(handle), None)
        media_type = name.removesuffix('_watchlist.csv').removesuffix('.csv')
        if not header or not set(public_fields[media_type]).issubset(header):
            raise ValueError(f'Invalid diary dataset columns: data/{name}')

def validate_sports_config(path: Path):
    config = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(config, dict) or set(config) != {'priority_teams', 'leagues'}:
        raise ValueError('Invalid sports configuration fields')
    teams, leagues = config['priority_teams'], config['leagues']
    if not isinstance(teams, list) or len(teams) > 100 or any(not isinstance(name, str) or not name.strip() or len(name) > 60 for name in teams):
        raise ValueError('Invalid priority team list')
    if not isinstance(leagues, list) or not 1 <= len(leagues) <= 32:
        raise ValueError('Invalid league list')
    names = set()
    for league in leagues:
        allowed = {'name', 'enabled', 'espn_path', 'color', 'standings', 'standings_type', 'scores_type'}
        if not isinstance(league, dict) or set(league) - allowed or not {'name', 'enabled', 'espn_path', 'color', 'standings'} <= set(league):
            raise ValueError('Invalid league fields')
        name, path_value, color = league['name'], league['espn_path'], league['color']
        if not isinstance(name, str) or not name.strip() or len(name) > 60 or name in names:
            raise ValueError('Invalid or duplicate league name')
        names.add(name)
        if not isinstance(league['enabled'], bool) or not isinstance(league['standings'], bool):
            raise ValueError('Invalid league flags')
        if not isinstance(path_value, str) or not re.fullmatch(r'[a-z0-9.-]+(?:/[a-z0-9.-]+)*', path_value) or '..' in path_value:
            raise ValueError('Invalid ESPN path')
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{3,8}', color):
            raise ValueError('Invalid league color')
        if 'standings_type' in league and league['standings_type'] not in {'division', 'rankings', 'soccer', 'f1'}:
            raise ValueError('Invalid standings type')
        if 'scores_type' in league and league['scores_type'] not in {'default', 'racing'}:
            raise ValueError('Invalid scores type')
    return config

def validate_output(path: Path) -> Path:
    raw = path.absolute()
    current = Path(raw.anchor)
    for part in raw.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise ValueError(f'Output path contains a symlink: {current}')
    output = raw.resolve()
    if output == ROOT or output in ROOT.parents:
        raise ValueError('Output cannot replace or contain the source tree')
    if ROOT in output.parents and output != ROOT / '_site':
        raise ValueError('The only allowed in-tree output is _site')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output must be a fresh or empty directory')
    return output

def populate(output: Path):
    spec = importlib.util.spec_from_file_location('diary_export', ROOT / 'scripts/export_json.py')
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    validate_inputs(exporter.PUBLIC_FIELDS)
    with tempfile.TemporaryDirectory(prefix='combined-apps-diary-') as temp:
        generated = Path(temp) / 'generated'
        exporter.DOCS_DIR = generated
        exporter.generate()
        for name in DIARY_PAGES + DIARY_DATA:
            copy_checked(generated / name, output / name, generated)
        for name in DIARY_ASSETS:
            copy_checked(generated / 'assets' / name, output / 'assets' / name, generated)
        # Generated query states are explicit compatibility routes; the static JSON remains the search source.
        for source in generated.glob('*-*-*-*-*.html'):
            if source.name.split('-', 1)[0] in ('all','movies','books','tv'):
                copy_checked(source, output / source.name, generated)
    tools = ROOT / 'tools'
    validate_sports_config(tools / 'sports-config.json')
    subprocess.run([sys.executable, str(tools / 'scripts/validate_sports.py'), str(tools / 'sports-snapshot.json'), '--config', str(tools / 'sports-config.json')], check=True)
    # Validate feed JSON against its source-side configs before it can enter Pages.
    subprocess.run([sys.executable, str(tools / 'scripts/validate_podcast.py'), str(tools / 'podcast-manifest.json')], check=True)
    subprocess.run([sys.executable, str(tools / 'scripts/validate_reddit.py'), str(tools / 'reddit-digest.json')], check=True)
    for relative in TOOL_PAGES + TOOL_DATA + TOOL_ASSETS:
        copy_checked(tools / relative, output / 'tools' / relative, tools)
    # News is generated from validated RSS snapshots at build time, so it works without a live proxy or JavaScript.
    subprocess.run(
        [sys.executable, str(tools / 'scripts/render_news.py'), '--root', str(output / 'tools'),
         '--config', str(tools / 'scripts/news-config.json')],
        check=True,
    )
    copy_checked(tools / 'home.html', output / 'tools' / 'index.html', tools)
    (output / '.nojekyll').touch()

def build(path: Path):
    output = validate_output(path)
    validate_source_tree()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.combined-apps-build-', dir=output.parent))
    try:
        populate(staging)
        if output.exists():
            output.rmdir()
        os.replace(staging, output)
        print(f'Built curated public artifact: {output}')
    finally:
        if staging.exists():
            shutil.rmtree(staging)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
