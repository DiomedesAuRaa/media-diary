import csv
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_diary
from app import config, csv_store, web
from app.presentation import browse, normalized, records
from scripts import export_json

class WebTest(unittest.TestCase):
    setUp=test_diary.DiaryTest.setUp
    tearDown=test_diary.DiaryTest.tearDown
    request=test_diary.DiaryTest.request

    def form(self,path):
        response=self.request('GET',path)
        self.assertEqual(200,response.status_code)
        from html import unescape
        return {name:unescape(value) for name,value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"',response.text)}

    def save(self,form,**fields):
        return self.request('POST','/save',data={**form,**fields})

    def test_no_js_browse_paginates_escapes_and_searches_all_types(self):
        for i in range(25):csv_store.prepend_entry('movies',csv_store.build_row('movies',title=f'Movie {i}',rating='8'))
        csv_store.prepend_entry('books',csv_store.build_row('books',title='<script>Rare title</script>',rating='9'))
        first=self.request('GET','/?compact=1')
        self.assertEqual(8,first.text.count('<li class="entry">'))
        self.assertIn('page=2',first.text)
        result=self.request('GET','/?type=all&q=Rare&sort=rating')
        self.assertIn('&lt;script&gt;Rare title&lt;/script&gt;',result.text)
        self.assertEqual(1,result.text.count('<li class="entry">'))

    def test_native_save_nonce_replay_and_csrf(self):
        form=self.form('/log?type=movies&compact=1')
        saved=self.save(form,title='Native movie',rating='8',date='2026-10-08')
        self.assertEqual(303,saved.status_code)
        self.assertEqual(303,self.save(form,title='Native movie',rating='8',date='2026-10-08').status_code)
        self.assertEqual(1,len(csv_store.read_entries('movies')))
        form['csrf']='invalid'
        self.assertEqual(403,self.save(form,title='Not saved',rating='8').status_code)

    def test_edit_original_identity_and_date_with_duplicate_titles(self):
        for date in ('10/01/26','10/02/26'):csv_store.prepend_entry('movies',csv_store.build_row('movies',title='Repeated',rating='7',date_rated=date))
        key=records(web.data())[1]['key']
        form=self.form('/log?type=movies&intent=edit&key='+key)
        self.assertEqual(303,self.save(form,title='Repeated',rating='9',date='2026-10-03').status_code)
        rows=csv_store.read_entries('movies')
        self.assertEqual(['10/02/26','10/03/26'],[r['Date Watched/Rated'] for r in rows])
        self.assertEqual(['7','9'],[r['Rating'] for r in rows])
        # An old form must not retarget another same-title row.
        form['csrf']=web.csrf()
        self.assertEqual(422,self.save(form,title='Repeated',rating='5',date='2026-10-04').status_code)

    def test_completion_saves_before_removal_and_preserves_on_failure(self):
        csv_store.prepend_entry('books',csv_store.build_watchlist_row('books',title='Read me',api_values={'Author':'Author'}),use_watchlist=True)
        key=records(web.data(),'later')[0]['key'];form=self.form('/log?type=books&mode=later&intent=complete&key='+key)
        with patch.object(web,'replace_entry_by_key',side_effect=OSError('disk unavailable')):
            response=self.save(form,title='Read me',rating='9',date='2026-10-08',remove_later='1',Author='Author')
        self.assertEqual(303,response.status_code)
        self.assertEqual(1,len(csv_store.read_entries('books')))
        self.assertEqual(1,len(csv_store.read_entries('books',use_watchlist=True)))
        self.assertIn('could+not+be+removed',response.headers['location'])
        self.assertEqual(303,self.save(form,title='Read me',rating='9').status_code)
        self.assertEqual(1,len(csv_store.read_entries('books')))

    def test_completion_success_and_explicit_repeat(self):
        csv_store.prepend_entry('tv',csv_store.build_watchlist_row('tv',title='Watch me'),use_watchlist=True)
        key=records(web.data(),'later')[0]['key'];form=self.form('/log?type=tv&mode=later&intent=complete&key='+key)
        self.assertEqual(303,self.save(form,title='Watch me',rating='6',remove_later='1').status_code)
        self.assertEqual([],csv_store.read_entries('tv',use_watchlist=True))
        form=self.form('/log?type=tv')
        self.assertEqual(422,self.save(form,title='Watch me',rating='7',strategy='ask').status_code)
        self.assertEqual(303,self.save(form,title='Watch me',rating='7',strategy='rewatch').status_code)
        self.assertEqual(2,len(csv_store.read_entries('tv')))

    def test_failed_save_retains_fields_and_rejects_cross_origin(self):
        form=self.form('/log?type=books')
        response=self.save(form,title='Keep my draft',rating='11',Author='Person')
        self.assertEqual(422,response.status_code)
        self.assertIn('value="Keep my draft"',response.text)
        self.assertIn('value="Person"',response.text)
        self.assertEqual(403,self.request('POST','/save',data={**form,'title':'Bad','rating':'8'},headers={'origin':'https://other.invalid'}).status_code)

    def test_public_allowlist_and_static_links_and_last_good_on_error(self):
        docs=self.root/'published';docs.mkdir();(docs/'old.txt').write_text('last good')
        # Extra CSV field never reaches publication.
        path=self.data/'movies.csv'
        fields=config.get_media_type('movies')['columns']+['Private notes']
        with path.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerow({'Movie':'Public title','Rating':'8','Private notes':'DO NOT PUBLISH'})
        exports={name:self.data/path.name for name,path in export_json.EXPORTS.items()}
        with patch.object(export_json,'DOCS_DIR',docs),patch.object(export_json,'EXPORTS',exports):
            with patch.object(export_json,'browse',side_effect=RuntimeError('failed generation')):
                with self.assertRaises(RuntimeError):export_json.main()
            self.assertEqual('last good',(docs/'old.txt').read_text())
            export_json.main()
        self.assertNotIn('DO NOT PUBLISH',(docs/'movies.json').read_text())
        html=(docs/'compact.html').read_text()
        self.assertIn('Public title',html)
        self.assertIn('books-diary-recent-1-compact.html',html)
        self.assertNotIn('/save',html)
        self.assertFalse((docs/'old.txt').exists())
