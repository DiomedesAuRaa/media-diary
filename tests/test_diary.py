import asyncio
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tarfile
import unittest
from unittest.mock import patch, AsyncMock

import httpx
from app import config, csv_store, git_sync, main, backups


class DiaryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.patchers = [
            patch.object(config, 'DATA_ROOT', self.data),
            patch.object(git_sync, 'REPO_ROOT', self.root),
            patch.object(git_sync, 'SYNC_STATE_PATH', self.root / 'publication.json'),
            patch.object(main, 'DATA_ROOT', self.data),
            patch.object(backups, 'REPO_ROOT', self.root),
            patch.dict(os.environ, {'GIT_SYNC_ENABLED': 'false', 'GIT_BRANCH': 'main', 'GIT_REMOTE': 'origin'}),
        ]
        for p in self.patchers: p.start()
        for typ in config.get_enabled_types():
            for watchlist in [False, True]:
                path = config.watchlist_path(typ) if watchlist else config.csv_path(typ)
                csv_store._write_rows(path, config.get_media_type(typ)['columns'], [])
        git_sync._status.update(last_ok=None, last_error=None, last_success_at=None, pending=True)

    def tearDown(self):
        for p in reversed(self.patchers): p.stop()
        self.temporary.cleanup()

    def request(self, method, path, **kwargs):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(run())

    def git(self, *args, cwd=None):
        return subprocess.run(['git', *args], cwd=cwd or self.root, check=True, capture_output=True, text=True).stdout.strip()

    def init_git(self):
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('add', 'data')
        self.git('commit', '-m', 'Fixture')
        remote = self.root / 'remote.git'
        self.git('init', '--bare', str(remote))
        self.git('remote', 'add', 'origin', str(remote))
        return remote

    def test_concurrent_writes_preserve_every_row(self):
        def save(i):
            row=csv_store.build_row('movies', title=f'Movie {i}', rating='8')
            csv_store.prepend_entry('movies', row)
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(save, range(80)))
        rows=csv_store.read_entries('movies')
        self.assertEqual(80,len(rows))
        self.assertEqual(80,len({r['Movie'] for r in rows}))

    def test_interrupted_replace_preserves_original(self):
        before=config.csv_path('books').read_bytes()
        with patch.object(csv_store.os,'replace',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                csv_store.prepend_entry('books', csv_store.build_row('books',title='Book',rating='9'))
        self.assertEqual(before,config.csv_path('books').read_bytes())
        self.assertEqual([],list(self.data.glob('.diary-*.tmp')))

    def test_all_types_watchlist_and_ratings_lifecycle(self):
        for typ in config.get_enabled_types():
            body={'title':f'{typ} fixture','api_values':{}}
            self.assertEqual(200,self.request('POST',f'/api/{typ}/watchlist',json=body).status_code)
            self.assertEqual(400,self.request('POST',f'/api/{typ}/watchlist',json=body).status_code)
            self.assertEqual(200,self.request('DELETE',f'/api/{typ}/watchlist',params={'title':body['title']}).status_code)
            body.update(rating=7,date_rated='10/08/26')
            self.assertEqual(200,self.request('POST',f'/api/{typ}/entries',json=body).status_code)
            body.update(rating=9,strategy='update')
            self.assertEqual('updated',self.request('POST',f'/api/{typ}/entries',json=body).json()['status'])
            body.update(rating=8,strategy='rewatch',date_rated='10/09/26')
            self.assertEqual(200,self.request('POST',f'/api/{typ}/entries',json=body).status_code)
            self.assertEqual(2,len(csv_store.read_entries(typ)))
            self.assertEqual(200,self.request('DELETE',f'/api/{typ}/entries',params={'title':body['title'],'date_rated':'10/08/26'}).status_code)
            self.assertEqual(1,len(csv_store.read_entries(typ)))

    def test_update_missing_does_not_create(self):
        r=self.request('POST','/api/movies/entries',json={'title':'Missing','rating':8,'strategy':'update'})
        self.assertEqual(404,r.status_code)
        self.assertEqual([],csv_store.read_entries('movies'))

    def test_pagination_covers_more_than_200(self):
        rows=[csv_store.build_row('movies',title=f'Movie {i}',rating='8') for i in range(230)]
        csv_store._write_rows(config.csv_path('movies'),config.get_media_type('movies')['columns'],rows)
        a=self.request('GET','/api/movies/entries?limit=200&offset=0').json()
        b=self.request('GET','/api/movies/entries?limit=200&offset=200').json()
        self.assertEqual(230,a['total'])
        self.assertEqual(rows,a['entries']+b['entries'])

    def test_watchlist_publishes_and_failed_push_retries_without_new_diff(self):
        remote=self.init_git()
        self.git('remote','set-url','origin',str(self.root/'unavailable.git'))
        csv_store.prepend_entry('books',csv_store.build_watchlist_row('books',title='Publish me'),use_watchlist=True)
        with patch.dict(os.environ,{'GIT_SYNC_ENABLED':'true'}):
            git_sync.sync_csv()
            self.assertFalse(git_sync.get_sync_status()['last_ok'])
            self.assertEqual('',self.git('diff','--cached','--name-only'))
            self.assertEqual('',self.git('diff','--name-only','--','data'))
            self.git('remote','set-url','origin',str(remote))
            git_sync.sync_csv()
            self.assertTrue(git_sync.get_sync_status()['last_ok'])
        published=self.git('--git-dir='+str(remote),'show','main:data/books_watchlist.csv')
        self.assertIn('Publish me',published)
        self.assertEqual('main',self.git('branch','--show-current'))

    def test_reject_unexpected_staged_code(self):
        self.init_git()
        (self.root/'unexpected.py').write_text('print("unexpected")')
        self.git('add','unexpected.py')
        with patch.dict(os.environ,{'GIT_SYNC_ENABLED':'true'}):
            git_sync.sync_csv()
        self.assertIn('Unexpected staged files',git_sync.get_sync_status()['last_error'])
        self.assertEqual('Fixture',self.git('log','-1','--format=%s'))

    def test_provider_errors_do_not_expose_secret_urls(self):
        provider=AsyncMock()
        provider.search.side_effect=RuntimeError('https://provider/?api_key=PRIVATE_VALUE')
        provider.lookup.side_effect=RuntimeError('https://provider/?api_key=PRIVATE_VALUE')
        with patch('app.routers.entries.get_provider',return_value=provider):
            for r in [self.request('GET','/api/movies/search?q=test'),self.request('POST','/api/movies/entries',json={'title':'test','rating':8,'external_id':'123'})]:
                self.assertEqual(500,r.status_code)
                self.assertNotIn('PRIVATE_VALUE',r.text)

    def test_backup_restore_preserves_data_and_history(self):
        self.init_git()
        csv_store.prepend_entry('tv',csv_store.build_row('tv',title='Unpublished',rating='7'))
        with patch.dict(os.environ,{'BACKUP_ROOT':str(self.root/'backups')}):
            self.assertTrue(backups.create_backup())
        restore=self.root/'restore'
        restore.mkdir()
        archive=next((self.root/'backups').glob('diary-*.tar.gz'))
        with tarfile.open(archive) as bundle:
            bundle.extractall(restore,filter='data')
        self.git('fsck','--no-dangling',cwd=restore/'repo')
        self.assertEqual(config.csv_path('tv').read_bytes(),(restore/'repo/data/tv.csv').read_bytes())
        manifest=json.loads((restore/'backup-manifest.json').read_text())
        self.assertEqual(6,len(manifest['csv_sha256']))

    def test_status_write_failure_does_not_reject_saved_entry(self):
        with patch.dict(os.environ,{'GIT_SYNC_ENABLED':'true'}), patch.object(git_sync,'_save_status',side_effect=OSError('unavailable')):
            response=self.request('POST','/api/books/entries',json={'title':'Saved locally','rating':8})
        self.assertEqual(200,response.status_code)
        self.assertEqual('Saved locally',csv_store.read_entries('books')[0]['Book'])

    def test_readiness_requires_all_files(self):
        self.assertEqual(200,self.request('GET','/ready').status_code)
        config.watchlist_path('tv').unlink()
        self.assertEqual(503,self.request('GET','/ready').status_code)


if __name__=='__main__':
    unittest.main()
