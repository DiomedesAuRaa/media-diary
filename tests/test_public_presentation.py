import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from public_diary.presentation import browse, detail, detail_name, filtered, normalized, records, year_summary


class PublicPresentationTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            'movies': [
                {'Movie': 'Older', 'Date Watched/Rated': '12/20/20', 'Date Released': '', 'Rating': '8', 'Director': ''},
                {'Movie': '<script>alert(1)</script>', 'Date Watched/Rated': '2024-02-29', 'Date Released': '', 'Rating': '9', 'Director': ''},
                {'Movie': 'Bad date', 'Date Watched/Rated': '02/30/24', 'Date Released': '', 'Rating': '7', 'Director': ''},
            ],
            'books': [], 'tv': [], 'movies_watchlist': [], 'books_watchlist': [], 'tv_watchlist': [],
        }

    def test_normalization_and_year_filter(self):
        self.assertEqual('all', normalized({})['type'])
        self.assertEqual('all', normalized({'mode': 'later', 'year': '2024'})['year'])
        state = normalized({'year': '2024'})
        self.assertEqual(['<script>alert(1)</script>'], [r['row']['Movie'] for r in filtered(self.data, state)])

    def test_year_is_honest_without_javascript_and_keeps_urls_small(self):
        html = browse(self.data, normalized({}))
        self.assertIn('id="year" name="year" disabled', html)
        self.assertIn('id="q" name="q" type="search"', html)
        self.assertIn('placeholder="Search diary" value="" disabled', html)
        self.assertIn('name="sort" disabled', html)
        self.assertIn('<button disabled>Find</button>', html)
        self.assertIn('<noscript><p class="no-js">Search and year filters need JavaScript.', html)
        self.assertIn('href="tools/"', html)
        self.assertNotIn('Portfolio', html)
        self.assertNotIn('/log?', html)
        self.assertIn('href="all-diary-recent-1-compact.html"', browse(self.data, normalized({'compact': '1'})))

    def test_renderer_escapes_public_titles(self):
        html = browse(self.data, normalized({'year': '2024'}))
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)

    def test_year_and_search_survive_category_and_sort_links(self):
        html = browse(self.data, normalized({'year': '2024', 'q': 'find me', 'sort': 'title'}))
        self.assertIn('movies-diary-title-1-full.html?type=movies', html)
        self.assertIn('year=2024', html)
        self.assertIn('q=find+me', html)
        script = (ROOT / 'public_diary' / 'static' / 'diary.js').read_text()
        self.assertIn("['type','mode','q','sort','page','compact','year']", script)
        self.assertIn('Number(state.year)<1000', script)
        self.assertIn("year:match[2]==='later'?'all':state.year", script)
        self.assertIn('textContent=text', script)
        self.assertNotIn('innerHTML', script)
        self.assertIn("history.pushState(state,'',href(state))", script)
        self.assertIn('if(e.state){state=e.state;load();}', script)

    def test_empty_year_result_names_active_filters(self):
        html = browse(self.data, normalized({'year': '1999'}))
        self.assertIn('No entries match these filters.', html)

    def test_detail_routes_and_title_match_history_are_projected_and_escaped(self):
        self.data['movies'] = [
            {'Movie':'<b>Same</b>', 'Date Watched/Rated':'2024-01-01', 'Date Released':'1999', 'Rating':'8', 'Director':'A & B', 'Private':'secret'},
            {'Movie':'<b>Same</b>', 'Date Watched/Rated':'2025-02-02', 'Date Released':'2001', 'Rating':'9', 'Director':'Other', 'Private':'secret2'},
            {'Movie':'<b>Same</b>', 'Date Watched/Rated':'2025-02-02', 'Date Released':'2001', 'Rating':'9', 'Director':'Other', 'Private':'secret2'},
        ]
        items=records(self.data)
        self.assertNotEqual(items[1]['key'],items[2]['key'])
        self.assertNotIn('Private',items[1]['row'])
        self.assertEqual(detail_name(items[1]), 'details/movies-diary-'+items[1]['key']+'.html')
        html=detail(self.data,items[1])
        self.assertIn('Entries with this title',html)
        self.assertIn('may refer to different editions',html)
        self.assertIn('Release date',html)
        self.assertIn('Director',html)
        self.assertIn('&lt;b&gt;Same&lt;/b&gt;',html)
        self.assertIn('A &amp; B',html)
        self.assertNotIn('secret',html)
        self.assertEqual(3,html.count('<li><a href="movies-diary-'))

    def test_native_and_enhanced_detail_links_share_bounded_return_state(self):
        html=browse(self.data,normalized({'year':'2024','type':'movies','sort':'title','page':'2','compact':'1'}))
        self.assertIn('details/movies-diary-',html)
        self.assertIn('q=&amp;page=1',html)
        self.assertIn('year=2024',html)
        js=(ROOT/'public_diary/static/diary.js').read_text()
        self.assertIn("anchor.href=row.detail+href(state).slice(href(state).indexOf('?'))",js)
        self.assertIn("detailMain.querySelector('.back').href='../'+bn+'?'+bp.toString()",js)

    def test_year_summary_is_all_media_and_independent_of_search(self):
        html=year_summary(self.data,'2024')
        self.assertIn('<details class="year-summary" data-year-summary>',html)
        for kind in ('movies','books','tv'):
            self.assertIn('data-summary-type="'+kind+'"',html)
        self.assertIn('do not verify identity',html)


if __name__ == '__main__':
    unittest.main()
