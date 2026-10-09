from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
import importlib.util
import json
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_public', ROOT / 'scripts/build_public.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

class LocalReferences(HTMLParser):
    def __init__(self):
        super().__init__(); self.refs=[]
    def handle_starttag(self, tag, attrs):
        values=dict(attrs)
        self.refs.extend(values[key] for key in ('href','src') if values.get(key))

class PublicBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory(prefix='combined-apps-tests-', dir=ROOT.parent)
        cls.output = Path(cls.temp.name) / '_site'
        builder.build(cls.output)
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_curated_artifact_paths_and_json_allowlist(self):
        files={str(path.relative_to(self.output)) for path in self.output.rglob('*') if path.is_file()}
        self.assertIn('.nojekyll', files)
        self.assertIn('index.html', files)
        self.assertIn('tools/home.html', files)
        self.assertIn('tools/today.html', files)
        self.assertIn('tools/schedule.html', files)
        self.assertIn('tools/assets/today.js', files)
        self.assertTrue((self.output/'tools/news.html').is_file())
        self.assertEqual({p for p in files if p.endswith('.json')}, {
            'movies.json','books.json','tv.json','movies_watchlist.json','books_watchlist.json','tv_watchlist.json',
            'tools/podcast-manifest.json','tools/reddit-digest.json','tools/sports-config.json','tools/sports-snapshot.json','tools/news-digest.json'})
        self.assertFalse(any('/scripts/' in '/' + p or '/tests/' in '/' + p or p.endswith('.csv') for p in files))
        self.assertFalse(any(p.startswith(('app/','public_diary/','data/')) for p in files))
        self.assertFalse(any('scores-' in p for p in files))
        tool_pages = {p for p in files if p.startswith('tools/') and p.endswith('.html')}
        self.assertTrue({'tools/home.html','tools/bible.html','tools/podcast-directory.html','tools/reddit-digest.html','tools/news.html','tools/weather.html','tools/standings.html','tools/sports-scores.html','tools/games/2048.html','tools/games/minesweeper.html','tools/games/snake.html','tools/games/tetris.html','tools/games/wordle.html'}.issubset(tool_pages))
        self.assertTrue((self.output/'compact.html').is_file())
        self.assertTrue(all(p == 'index.html' or p == 'compact.html' or p.startswith('tools/') or p.endswith('-full.html') or p.endswith('-compact.html') for p in files if p.endswith('.html')))
        for path in self.output.rglob('*.json'): json.loads(path.read_text())

    def test_all_local_html_assets_and_navigation_resolve(self):
        missing=[]
        for page in self.output.rglob('*.html'):
            parser=LocalReferences(); parser.feed(page.read_text(encoding='utf-8'))
            for ref in parser.refs:
                parsed=urlsplit(ref)
                if not parsed.scheme and not parsed.netloc:
                    target=(page.parent / parsed.path) if parsed.path else page
                    if not target.exists(): missing.append((page.relative_to(self.output),ref))
        self.assertEqual(missing, [])
        diary=(self.output/'index.html').read_text()
        self.assertIn('href="tools/home.html"', diary)
        self.assertIn('href="../"', (self.output/'tools/home.html').read_text())

    def test_workflow_output_path_and_forbidden_paths(self):
        self.assertEqual(builder.validate_output(ROOT/'_site'), ROOT/'_site')
        for path in (ROOT, ROOT/'data'/'output', ROOT/'tools'/'site'):
            with self.assertRaises(ValueError): builder.validate_output(path)

    def test_sports_config_rejects_untrusted_api_paths(self):
        self.assertTrue(builder.validate_sports_config(ROOT/'tools/sports-config.json'))
        with tempfile.TemporaryDirectory(prefix='combined-apps-sports-', dir=ROOT.parent) as temp:
            path=Path(temp)/'sports.json'
            path.write_text(json.dumps({'priority_teams': [], 'leagues': [{'name':'Bad','enabled':True,'espn_path':'https://evil.example','color':'#123456','standings':False}]}))
            with self.assertRaises(ValueError): builder.validate_sports_config(path)

    def test_public_renderer_has_no_lan_backend_routes_or_imports(self):
        sources='\n'.join(p.read_text(encoding='utf-8') for p in (ROOT/'public_diary').glob('*.py'))
        for forbidden in ('from app.', 'FastAPI', 'SYNC_STATE_PATH', 'DATA_ROOT', '/api/', '/log?', '/record?'):
            self.assertNotIn(forbidden, sources)

    def test_racing_score_configuration_is_validated(self):
        config = builder.validate_sports_config(ROOT/'tools/sports-config.json')
        racing = next(league for league in config['leagues'] if league['name'] == 'F1')
        self.assertEqual(racing['scores_type'], 'racing')
        racing['scores_type'] = 'untrusted-renderer'
        with TemporaryDirectory(prefix='combined-apps-racing-', dir=ROOT.parent) as temp:
            path = Path(temp)/'sports.json'
            path.write_text(json.dumps(config))
            with self.assertRaises(ValueError): builder.validate_sports_config(path)

    def test_nonempty_and_symlink_outputs_are_preserved(self):
        with TemporaryDirectory(prefix='combined-apps-safety-', dir=ROOT.parent) as temp:
            base=Path(temp); occupied=base/'occupied'; occupied.mkdir(); marker=occupied/'keep'; marker.write_text('keep')
            with self.assertRaises(ValueError): builder.build(occupied)
            self.assertEqual(marker.read_text(), 'keep')
            target=base/'target'; target.mkdir(); link=base/'link'; link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError): builder.build(link)
            self.assertTrue(target.is_dir())

    def test_missing_diary_dataset_is_rejected(self):
        old_root=builder.ROOT
        try:
            with TemporaryDirectory(prefix='combined-apps-missing-', dir=ROOT.parent) as temp:
                builder.ROOT=Path(temp)
                (builder.ROOT/'data').mkdir()
                with self.assertRaises(ValueError): builder.validate_inputs({'movies': ('Movie',), 'books': ('Book',), 'tv': ('Show',)})
        finally:
            builder.ROOT=old_root

    def test_symlinked_public_inputs_are_rejected(self):
        with TemporaryDirectory(prefix='combined-apps-input-', dir=ROOT.parent) as temp:
            base=Path(temp); input_root=base/'source'; input_root.mkdir(); outside=base/'outside.txt'; outside.write_text('private')
            link=input_root/'linked.txt'; link.symlink_to(outside)
            with self.assertRaises(ValueError): builder.copy_checked(link, base/'dest.txt', input_root)
            self.assertFalse((base/'dest.txt').exists())

if __name__ == '__main__': unittest.main()
