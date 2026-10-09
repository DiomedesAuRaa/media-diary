#!/usr/bin/env python3
"""Validate public RSS digest before granting it repository publication."""
import argparse
import json
import math
import re
from pathlib import Path
from urllib.parse import urlparse

CONFIG_PATH = Path(__file__).resolve().with_name('reddit-config.json')

FIELDS = {'title','author','score','url','selftext','created_utc','num_comments','id','subreddit','link_url','is_self','upvote_ratio','flair','comments'}

def safe_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError('Invalid URL')
    parsed = urlparse(value)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,80,443):
        raise ValueError('Unsafe URL')

def validate(path, config_path=CONFIG_PATH):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Digest too large')
    data = json.loads(path.read_text())
    config = json.loads(config_path.read_text())
    expected_subreddits = config.get('subreddits') if isinstance(config, dict) else None
    expected_feeds = config.get('feeds') if isinstance(config, dict) else None
    if not isinstance(expected_subreddits, list) or not isinstance(expected_feeds, list):
        raise ValueError('Invalid publication configuration')
    expected_labels = [feed.get('label') for feed in expected_feeds if isinstance(feed, dict)]
    if len(expected_labels) != len(expected_feeds):
        raise ValueError('Invalid publication configuration')
    expected = {'schema_version','timestamp','generated_at','subreddits_count','total_posts','feeds','comments_feed','fetch_errors','data','refresh_status','last_attempt_at','feed_status'}
    if not isinstance(data, dict) or set(data) != expected or data['schema_version'] != 2 or data['refresh_status'] not in ('ok','partial','stale','unavailable'):
        raise ValueError('Invalid digest fields')
    feeds = data['feeds']
    if feeds != expected_labels:
        raise ValueError('Feed labels do not match publication configuration')
    if not isinstance(data['data'],dict) or list(data['data']) != expected_subreddits:
        raise ValueError('Invalid subreddit data')
    total = 0
    for subreddit,feed_data in data['data'].items():
        if not re.fullmatch(r'[A-Za-z0-9_]{1,50}',subreddit) or not isinstance(feed_data,dict) or set(feed_data)!=set(feeds):
            raise ValueError('Invalid subreddit fields')
        if subreddit not in data['feed_status'] or set(data['feed_status'][subreddit]) != set(feeds):
            raise ValueError('Missing refresh provenance')
        for label,posts in feed_data.items():
            status=data['feed_status'][subreddit][label]
            if not isinstance(status,dict) or set(status) != {'status','generated_at','last_attempt_at'} or status['status'] not in ('ok','stale','unavailable'):
                raise ValueError('Invalid feed provenance')
            if not isinstance(posts,list) or len(posts)>5:
                raise ValueError('Invalid posts')
            total+=len(posts)
            for post in posts:
                if not isinstance(post,dict) or not FIELDS.issubset(post) or set(post) - FIELDS - {'metadata_source'}:
                    raise ValueError('Invalid post fields')
                if 'metadata_source' in post and post['metadata_source'] != 'rss':
                    raise ValueError('Invalid metadata source')
                for field in ('title','author','id','subreddit','flair'):
                    if not isinstance(post[field],str) or len(post[field])>20000:
                        raise ValueError('Invalid post text')
                if not isinstance(post['selftext'], str) or len(post['selftext']) > 50000:
                    raise ValueError('Invalid post text')
                safe_url(post['url']); safe_url(post['link_url'])
                if post['subreddit'].casefold()!=subreddit.casefold() or not isinstance(post['is_self'],bool):
                    raise ValueError('Invalid RSS metadata')
                comments = post['comments']
                if not isinstance(comments, list) or len(comments) > 5:
                    raise ValueError('Invalid preserved comments')
                for comment in comments:
                    if (not isinstance(comment, dict) or set(comment) != {'author','body','score'}
                            or not isinstance(comment['author'], str) or len(comment['author']) > 200
                            or not isinstance(comment['body'], str) or len(comment['body']) > 20000
                            or not isinstance(comment['score'], (int,float)) or not math.isfinite(comment['score'])):
                        raise ValueError('Invalid preserved comment')
                for field in ('score','num_comments','created_utc','upvote_ratio'):
                    if not isinstance(post[field],(int,float)) or not math.isfinite(post[field]):
                        raise ValueError('Invalid numeric value')
    if data['total_posts'] != total or data['subreddits_count'] != len(data['data']):
        raise ValueError('Incorrect counts')
    return data

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('digest',type=Path)
    args=parser.parse_args()
    validate(args.digest)
    print('Reddit artifact schema validated')
