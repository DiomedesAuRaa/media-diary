"""Shared, escaped presentation for the LAN app and public static diary."""
from __future__ import annotations
from datetime import datetime
from html import escape
import hashlib
import json
from urllib.parse import urlencode
from app.config import MEDIA_TYPES

LABELS = {'all': 'All', 'movies': 'Movies', 'books': 'Books', 'tv': 'TV'}
PUBLIC_FIELDS = {
    'movies': ('Movie', 'Date Watched/Rated', 'Date Released', 'Rating', 'Director'),
    'books': ('Book', 'Date Read/Rated', 'Date Published', 'Rating', 'Author'),
    'tv': ('Show', 'Date Watched/Rated', 'Date Premiered', 'Rating', 'Creator'),
}

def esc(value): return escape(str(value or ''), quote=True)

def row_key(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]

def records(data, mode='diary'):
    result=[]
    for typ in MEDIA_TYPES:
        seen={}
        for row in data.get(typ + ('_watchlist' if mode=='later' else ''), []):
            digest=row_key(row); occurrence=seen.get(digest,0); seen[digest]=occurrence+1
            result.append({'type':typ, 'row':row, 'key':f'{digest}-{occurrence}'})
    return result

def date_value(value):
    for fmt in ('%m/%d/%y', '%Y-%m-%d', '%m/%d/%Y'):
        try:return datetime.strptime(value,fmt).strftime('%Y-%m-%d')
        except (ValueError,TypeError):pass
    return ''

def filtered(data, state):
    rows=records(data,state['mode']); q=state['q'].casefold().strip()
    rows=[r for r in rows if (state['type']=='all' or r['type']==state['type']) and (not q or q in ' '.join(r['row'].values()).casefold())]
    def key(r):
        cfg=MEDIA_TYPES[r['type']]; row=r['row']; title=row.get(cfg['title_column'],'').casefold()
        if state['sort']=='title':return (title,r['type'])
        if state['sort']=='rating':
            try:rating=float(row.get('Rating') or 0)
            except ValueError:rating=0
            return (-rating,title)
        date=date_value(row.get(cfg['auto_fields'][0],''))
        return (date,title)
    rows.sort(key=key,reverse=state['sort']=='recent')
    return rows

def normalized(params):
    def value(k,default):return str(params.get(k,default))
    try: page=max(1,min(100000,int(value('page',1))))
    except ValueError:page=1
    return {'type':value('type','movies') if value('type','movies') in LABELS else 'movies',
            'mode':'later' if value('mode','diary')=='later' else 'diary',
            'sort':value('sort','recent') if value('sort','recent') in ('recent','rating','title') else 'recent',
            'q':value('q','')[:300], 'page':page, 'compact':value('compact','0')=='1'}

def url(state, **changes):
    p={**state,**changes};p['compact']='1' if p.get('compact') else '0'
    return '?' + urlencode(p)

def shell(body, *, compact=False, public=False, title='Media Diary'):
    assets='assets/' if public else '/static/'
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><link rel="stylesheet" href="{assets}diary.css"><script defer src="{assets}diary.js"></script></head><body class="{'compact' if compact else ''}"><a class="skip" href="#main">Skip to content</a><header><a class="brand" href="{'index.html' if public else '/'}">Media Diary</a><a href="https://diomedesauraa.github.io/Portfolio/home.html">Home</a></header>{body}<footer>{'Public diary · read only' if public else 'Home diary · editing on your LAN'}</footer></body></html>'''

def static_name(state):
    return f'{state["type"]}-{state["mode"]}-{state["sort"]}-{state["page"]}-{"compact" if state["compact"] else "full"}.html'

def browse(data, state, *, public=False, notice='', publication=''):
    def link(current, **changes):
        updated={**current,**changes}
        return static_name(updated) + (url(updated) if updated.get('q') else '') if public else url(updated)
    rows=filtered(data,state);size=8 if state['compact'] else 20;pages=max(1,(len(rows)+size-1)//size)
    state={**state,'page':min(state['page'],pages)};selected=rows[(state['page']-1)*size:state['page']*size]
    nav=''.join(f'<a href="{link(state,type=k,page=1)}" {"aria-current=page" if state["type"]==k else ""}>{v}</a>' for k,v in LABELS.items())
    modes=''.join(f'<a href="{link(state,mode=k,page=1)}" {"aria-current=page" if state["mode"]==k else ""}>{v}</a>' for k,v in [('diary','Diary'),('later','For later')])
    options=''.join(f'<option value="{k}" {"selected" if state["sort"]==k else ""}>{v}</option>' for k,v in [('recent','Recent'),('rating','Highest rated'),('title','Title')])
    hidden=''.join(f'<input type="hidden" name="{k}" value="{esc("1" if state[k] is True else "0" if state[k] is False else state[k])}">' for k in ['type','mode','compact'])
    items=''
    for item in selected:
        typ=item['type'];r=item['row'];cfg=MEDIA_TYPES[typ];title=r.get(cfg['title_column'],'Untitled');date=r.get(cfg['auto_fields'][0],'');creator=r.get(cfg['api_fields'][-1],'')
        detail=f'/record?{urlencode({"type":typ,"mode":state["mode"],"key":item["key"],"compact":int(state["compact"])})}'
        title_html=esc(title) if public else f'<a href="{detail}">{esc(title)}</a>'
        rating=f'<span class="rating">{esc(r.get("Rating"))}/10</span>' if state['mode']=='diary' else ''
        meta=('Read' if typ=='books' else 'Watched')+' '+date if state['mode']=='diary' else ('To read' if typ=='books' else 'To watch')
        if state['type']=='all':meta=LABELS[typ]+' · '+meta
        if creator:meta+=' · '+creator
        items+=f'<li class="entry"><div class="entry-title">{title_html}{rating}</div><p class="meta">{esc(meta)}</p></li>'
    if not items:items='<li class="empty">'+('No titles match this search.' if state['q'] else ('Your for-later list is empty.' if state['mode']=='later' else 'No entries yet.'))+'</li>'
    pagination=f'<nav class="pagination" aria-label="Pages">'+(f'<a href="{link(state,page=state["page"]-1)}">Previous</a>' if state['page']>1 else '<span>Previous</span>')+f'<span>{state["page"]} / {pages}</span>'+(f'<a href="{link(state,page=state["page"]+1)}">Next</a>' if state['page']<pages else '<span>Next</span>')+'</nav>'
    action='' if public else f'<a class="primary" href="/log?type={state["type"] if state["type"]!="all" else "movies"}&compact={int(state["compact"])}">Log something</a>'
    body=f'''<main id="main" {"data-public=1" if public else ""}><nav class="categories" aria-label="Category">{nav}</nav><div class="toolbar"><nav class="modes" aria-label="List">{modes}</nav>{action}<a class="view-switch" href="{link(state,compact=not state['compact'],page=1)}">{'Full view' if state['compact'] else 'Compact view'}</a></div><form class="find" method="get">{hidden}<label class="sr-only" for="q">Search all diary fields</label><input id="q" name="q" type="search" placeholder="Search diary" value="{esc(state['q'])}"><label class="sr-only" for="sort">Sort</label><select id="sort" name="sort">{options}</select><button>Find</button></form>{f'<p role="status" class="notice">{esc(notice)}</p>' if notice else ''}<p class="count">{len(rows)} items</p><ul class="entries">{items}</ul>{pagination}{f'<details class=publication><summary>Publication status</summary><p role=status>{esc(publication)}</p></details>' if publication else ''}</main>'''
    if public:
        encoded=json.dumps(state).replace('<','\\u003c')
        body+=f'<script type="application/json" id="diary-state">{encoded}</script><noscript><p>Search needs JavaScript. Use Title sorting and the category/page links to browse without it.</p></noscript>'
    return shell(body,compact=state['compact'],public=public)
