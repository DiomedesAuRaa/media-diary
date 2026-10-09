import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import fetch_feeds

spec = importlib.util.spec_from_file_location('validate_podcast', SCRIPTS / 'validate_podcast.py')
validate_podcast = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate_podcast)

class PodcastRefreshTests(unittest.TestCase):
    def test_failed_refresh_retains_last_good_episodes_and_time(self):
        old = [{'name':'Show','episodes':[{'title':'Old','date':'','dateSort':'','audioUrl':'https://example.com/old.mp3'}], 'generatedAt':'old'}]
        def fail(_url): raise OSError('network failure')
        result = fetch_feeds.refresh({'podcasts':[{'name':'Show','feed_url':'https://example.com/rss'}]}, old, fetch=fail, now='attempt')
        self.assertEqual(result[0]['episodes'], old[0]['episodes'])
        self.assertEqual(result[0]['generatedAt'], 'old')
        self.assertEqual(result[0]['fetchStatus'], 'stale')

    def test_only_audio_enclosures_are_exposed_and_manifest_validates(self):
        rss = b'<rss version="2.0"><channel><title>Show</title><item><title>Article</title><link>https://example.com/post</link></item><item><title>Episode</title><enclosure url="https://example.com/audio.mp3" type="audio/mpeg" /></item></channel></rss>'
        config = {'podcasts':[{'name':'Show','feed_url':'https://example.com/rss'}]}
        result = fetch_feeds.refresh(config, [], fetch=lambda _url:rss, now='2026-10-09T00:00:00+00:00')
        self.assertEqual([ep['title'] for ep in result[0]['episodes']], ['Episode'])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'manifest.json'
            path.write_text(json.dumps(result))
            validate_podcast.validate(path)
            result[0]['episodes'][0]['audioUrl'] = 'javascript:alert(1)'
            path.write_text(json.dumps(result))
            with self.assertRaises(ValueError): validate_podcast.validate(path)

if __name__ == '__main__': unittest.main()
