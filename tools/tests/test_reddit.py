import importlib.util
import sys
import json
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import fetch_reddit

CONFIG = {'subreddits':['nfl'], 'feeds':[{'label':'Hot','sort':'hot','timeframe':None}, {'label':'Best of Week','sort':'top','timeframe':'week'}]}
STAMP = '2026-10-08T00:00:00+00:00'
BODY = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Reddit</title><entry><title>Post</title><id>t3_abc</id><link href="https://www.reddit.com/r/nfl/comments/abc/post/"/><author><name>/u/example</name></author><updated>2026-10-07T12:00:00Z</updated></entry></feed>'

class RedditRefreshTests(unittest.TestCase):
    def test_preserves_failed_feed_and_provenance(self):
        previous=fetch_reddit.refresh(CONFIG,{},fetch=lambda url:BODY,now=STAMP,delay=0)
        def mixed(url):
            if 'top.rss' in url: raise OSError('failed')
            return BODY
        actual=fetch_reddit.refresh(CONFIG,previous,fetch=mixed,now='2026-10-09T00:00:00+00:00',delay=0)
        self.assertEqual(actual['refresh_status'],'partial')
        self.assertEqual(actual['data']['nfl']['Best of Week'],previous['data']['nfl']['Best of Week'])
        self.assertEqual(actual['feed_status']['nfl']['Best of Week']['generated_at'],STAMP)
        self.assertEqual(actual['feed_status']['nfl']['Best of Week']['status'],'stale')

    def test_all_failures_keep_original_generation_time(self):
        previous=fetch_reddit.refresh(CONFIG,{},fetch=lambda url:BODY,now=STAMP,delay=0)
        def fail(url): raise OSError('failed')
        actual=fetch_reddit.refresh(CONFIG,previous,fetch=fail,now='2026-10-09T00:00:00+00:00',delay=0)
        self.assertEqual(actual['timestamp'],STAMP)
        self.assertEqual(actual['generated_at'],previous['generated_at'])
        self.assertEqual(actual['refresh_status'],'stale')

    def test_budget_expiry_does_not_request_more_feeds(self):
        def unexpected(url): raise AssertionError('Request exceeded budget')
        actual=fetch_reddit.refresh(CONFIG,{},fetch=unexpected,now=STAMP,delay=0,budget=0)
        self.assertEqual(actual['refresh_status'],'unavailable')
        self.assertIsNone(actual['timestamp'])

    def test_active_url_is_not_a_post(self):
        with self.assertRaises(ValueError):
            fetch_reddit.parse_posts(BODY.replace(b'https://www.reddit.com/r/nfl/comments/abc/post/',b'javascript:alert(1)'), 'nfl')

    def test_rss_posts_identify_missing_reddit_metrics(self):
        post=fetch_reddit.parse_posts(BODY,'nfl')[0]
        self.assertEqual(post['metadata_source'],'rss')
        self.assertEqual((post['score'],post['num_comments'],post['comments']),(0,0,[]))

    def test_publication_validator_accepts_refresh_rejects_extra_or_script(self):
        spec=importlib.util.spec_from_file_location('validate_reddit',Path(__file__).resolve().parents[1]/'scripts/validate_reddit.py')
        validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
        data=fetch_reddit.refresh(CONFIG,{},fetch=lambda url:BODY,now=STAMP,delay=0)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'digest.json'
            config_path=Path(directory)/'reddit-config.json'
            config_path.write_text(json.dumps(CONFIG))
            path.write_text(json.dumps(data));validator.validate(path,config_path)
            data['data']['nfl']['Hot'][0]['metadata_source']='unknown'
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError): validator.validate(path,config_path)
            data['data']['nfl']['Hot'][0]['metadata_source']='rss'
            data['data']['nfl']['Hot'][0]['url']='javascript:alert(1)'
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError): validator.validate(path,config_path)

    def test_publication_rejects_unconfigured_subreddits_and_feed_labels(self):
        spec=importlib.util.spec_from_file_location('validate_reddit',Path(__file__).resolve().parents[1]/'scripts/validate_reddit.py')
        validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)
        data=fetch_reddit.refresh(CONFIG,{},fetch=lambda url:BODY,now=STAMP,delay=0)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'digest.json';config_path=Path(directory)/'reddit-config.json'
            config_path.write_text(json.dumps(CONFIG))
            data['data']['nfl']['Hot']='attacker controlled replacement'
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError): validator.validate(path,config_path)

if __name__=='__main__': unittest.main()
