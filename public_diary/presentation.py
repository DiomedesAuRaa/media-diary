"""Escaped renderer for the public static diary."""
from __future__ import annotations
from datetime import datetime
from html import escape
import hashlib
import json
from urllib.parse import urlencode
from public_diary.config import MEDIA_TYPES

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
        for source_row in data.get(typ + ('_watchlist' if mode=='later' else ''), []):
            # Keep identity and rendered content inside the same explicit public allowlist.
            row={field: str(source_row.get(field) or '') for field in PUBLIC_FIELDS[typ]}
            digest=row_key(row); occurrence=seen.get(digest,0); seen[digest]=occurrence+1
            result.append({'type':typ, 'row':row, 'key':f'{digest}-{occurrence}'})
    return result

def date_value(value):
    for fmt in ('%m/%d/%y', '%Y-%m-%d', '%m/%d/%Y'):
        try:return datetime.strptime(value,fmt).strftime('%Y-%m-%d')
        except (ValueError,TypeError):pass
    return ''

def years(data, mode='diary'):
    values=set()
    for item in records(data, mode):
        typ=item['type']; row=item['row']
        value=date_value(row.get(MEDIA_TYPES[typ]['auto_fields'][0], ''))
        if value: values.add(value[:4])
    return sorted(values, reverse=True)

def filtered(data, state):
    rows=records(data,state['mode']); q=state['q'].casefold().strip()
    rows=[r for r in rows if (state['type']=='all' or r['type']==state['type']) and
          (state.get('year','all')=='all' or date_value(r['row'].get(MEDIA_TYPES[r['type']]['auto_fields'][0], '')).startswith(state['year'])) and
          (not q or q in ' '.join(r['row'].values()).casefold())]
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
    year=value('year','all')
    if year != 'all' and (len(year) != 4 or not year.isdigit() or int(year) < 1000): year='all'
    if value('mode','diary') == 'later': year='all'
    return {'type':value('type','all') if value('type','all') in LABELS else 'all',
            'mode':'later' if value('mode','diary')=='later' else 'diary',
            'sort':value('sort','recent') if value('sort','recent') in ('recent','rating','title') else 'recent',
            'q':value('q','')[:300], 'page':page, 'compact':value('compact','0')=='1', 'year':year}

def url(state, **changes):
    p={**state,**changes};p['compact']='1' if p.get('compact') else '0'
    return '?' + urlencode(p)

def shell(body, *, compact=False, title='Media Diary', prefix=''):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><link rel="stylesheet" href="{prefix}assets/diary.css"><script defer src="{prefix}assets/diary.js"></script></head><body class="{'compact' if compact else ''}"><a class="skip" href="#main">Skip to content</a><header><a class="brand" href="{prefix}index.html">Media Diary</a><a href="{prefix}tools/">Tools &amp; games</a></header>{body}<footer>Public diary · read only</footer></body></html>'''

def static_name(state):
    return f'{state["type"]}-{state["mode"]}-{state["sort"]}-{state["page"]}-{"compact" if state["compact"] else "full"}.html'

def detail_name(item, mode='diary'):
    return f'details/{item["type"]}-{mode}-{item["key"]}.html'

def detail(data, item, mode='diary'):
    """Render a snapshot-stable detail page from a PUBLIC_FIELDS-projected record."""
    typ=item['type']; row=item['row']; cfg=MEDIA_TYPES[typ]
    title=row.get(cfg['title_column'],'Untitled') or 'Untitled'
    publication=cfg['api_fields'][0]; creator=cfg['api_fields'][1]
    date=cfg['auto_fields'][0]
    fields=[('Title',title)]
    if mode=='diary': fields.append((('Date read' if typ=='books' else 'Date watched'),row.get(date,'')))
    fields.extend([('Rating', (row.get('Rating','')+'/10') if row.get('Rating') else ''),
                   (('Release date' if typ!='books' else 'Publication date'),row.get(publication,'')),
                   (('Director' if typ=='movies' else 'Author' if typ=='books' else 'Creator'),row.get(creator,''))])
    details=''.join(f'<dt>{esc(label)}</dt><dd>{esc(value) if value else "—"}</dd>' for label,value in fields)
    # Title matches are a readable history aid, not a claim that records share an identity.
    matches=[]
    folded=title.casefold().strip()
    for candidate in records(data,'diary'):
        if candidate['type']!=typ or candidate['row'].get(cfg['title_column'],'').casefold().strip()!=folded:
            continue
        cr=candidate['row']; matches.append((candidate,cr.get(date,''),cr.get(cfg['api_fields'][1],''),cr.get(cfg['api_fields'][0],''),cr.get('Rating','')))
    match_html=''.join(f'<li><a href="{esc(typ+"-diary-"+candidate["key"]+".html")}">{esc(candidate["row"].get(cfg["title_column"],title))}</a> · {esc("Date read" if typ=="books" else "Date watched")}: {esc(d) if d else "—"} · {esc(creator_label(typ))}: {esc(c) if c else "—"} · {esc("Publication date" if typ=="books" else "Release date")}: {esc(y) if y else "—"} · Rating: {esc(rating)+"/10" if rating else "—"}</li>' for candidate,d,c,y,rating in matches)
    back=f'../{typ}-{mode}-recent-1-full.html'
    body=f'''<main id="main" data-detail="1"><a class="back" href="{back}">← Back to diary</a><h1>{esc(title)}</h1><p class="detail-kind">{esc(LABELS[typ])}</p><dl class="detail-fields">{details}</dl><section aria-labelledby="history-title"><h2 id="history-title">Entries with this title</h2><p>These entries share a title and may refer to different editions, releases, or occasions.</p><ul class="match-history">{match_html or '<li>No diary title matches.</li>'}</ul></section></main>'''
    return shell(body,title=f'{title} · Media Diary',prefix='../')

def creator_label(typ):
    return {'movies':'Director','books':'Author','tv':'Creator'}[typ]

def year_summary(data, year='all'):
    parts=[]
    for typ in ('movies','books','tv'):
        cfg=MEDIA_TYPES[typ]; selected=[]; identities=set()
        for item in records(data,'diary'):
            if item['type']!=typ: continue
            row=item['row']; when=date_value(row.get(cfg['auto_fields'][0],''))
            if year!='all' and not when.startswith(year): continue
            selected.append(row)
            identity=(row.get(cfg['title_column'],'').casefold().strip(),row.get(cfg['api_fields'][1],'').casefold().strip(),row.get(cfg['api_fields'][0],'').casefold().strip())
            identities.add(identity)
        label={'movies':'Movies watched','books':'Books read','tv':'TV entries'}[typ]
        parts.append(f'<li data-summary-type="{typ}"><span>{label}</span> <strong>{len(selected)} entries</strong> <span class="approx-titles">Approx. distinct titles: {len(identities)}</span></li>')
    return '<details class="year-summary" data-year-summary><summary>Year summary · '+esc(year if year!='all' else 'All years')+'</summary><p>Counts cover the selected year (or all years), all media regardless of search or category, and diary entries. Approximate title matches use title, creator, and release/publication date and do not verify identity.</p><ul class="year-summary-counts">'+''.join(parts)+'</ul></details>'

def browse(data, state):
    def link(current, **changes):
        updated={**current,**changes}
        if updated['mode']=='later': updated['year']='all'
        return static_name(updated) + (url(updated) if updated.get('q') or updated.get('year','all')!='all' else '')
    rows=filtered(data,state);size=8 if state['compact'] else 20;pages=max(1,(len(rows)+size-1)//size)
    state={**state,'page':min(state['page'],pages)};selected=rows[(state['page']-1)*size:state['page']*size]
    nav=''.join(f'<a href="{link(state,type=k,page=1)}" {"aria-current=page" if state["type"]==k else ""}>{v}</a>' for k,v in LABELS.items())
    modes=''.join(f'<a href="{link(state,mode=k,page=1)}" {"aria-current=page" if state["mode"]==k else ""}>{v}</a>' for k,v in [('diary','Diary'),('later','For later')])
    options=''.join(f'<option value="{k}" {"selected" if state["sort"]==k else ""}>{v}</option>' for k,v in [('recent','Recent'),('rating','Highest rated'),('title','Title')])
    hidden=''.join(f'<input type="hidden" name="{k}" value="{esc("1" if state[k] is True else "0" if state[k] is False else state[k])}">' for k in ['type','mode','compact'])
    items=''
    for item in selected:
        typ=item['type'];r=item['row'];cfg=MEDIA_TYPES[typ];title=r.get(cfg['title_column'],'Untitled');date=r.get(cfg['auto_fields'][0],'');creator=r.get(cfg['api_fields'][-1],'')
        title_html=f'<a class="detail-link" href="{esc(detail_name(item,state["mode"])+url(state))}">{esc(title)}</a>'
        rating=f'<span class="rating">{esc(r.get("Rating"))}/10</span>' if state['mode']=='diary' else ''
        meta=('Read' if typ=='books' else 'Watched')+' '+date if state['mode']=='diary' else ('To read' if typ=='books' else 'To watch')
        if state['type']=='all':meta=LABELS[typ]+' · '+meta
        if creator:meta+=' · '+creator
        items+=f'<li class="entry"><div class="entry-title">{title_html}{rating}</div><p class="meta">{esc(meta)}</p></li>'
    if not items:
        empty='No entries match these filters.' if state.get('year','all')!='all' else ('No titles match this search.' if state['q'] else ('Your for-later list is empty.' if state['mode']=='later' else 'No entries yet.'))
        items=f'<li class="empty">{empty}</li>'
    pagination=f'<nav class="pagination" aria-label="Pages">'+(f'<a href="{link(state,page=state["page"]-1)}">Previous</a>' if state['page']>1 else '<span>Previous</span>')+f'<span>{state["page"]} / {pages}</span>'+(f'<a href="{link(state,page=state["page"]+1)}">Next</a>' if state['page']<pages else '<span>Next</span>')+'</nav>'
    action=''
    year_opts='<option value="all">Any year</option>'+''.join(f'<option value="{y}" {"selected" if state["year"]==y else ""}>{y}</option>' for y in years(data,state['mode']))
    summary=year_summary(data,state['year']) if state['mode']=='diary' else ''
    body=f'''<main id="main" class="browse" data-public="1"><h1>Media diary</h1><nav class="categories" aria-label="Category">{nav}</nav><div class="toolbar"><nav class="modes" aria-label="List">{modes}</nav>{action}<a class="view-switch" href="{link(state,compact=not state['compact'],page=1)}">{'Full view' if state['compact'] else 'Compact view'}</a></div><form class="find" method="get">{hidden}<label class="sr-only" for="q">Search titles, creators, and other diary fields</label><input id="q" name="q" type="search" placeholder="Search diary" value="{esc(state['q'])}" disabled><label class="sr-only" for="sort">Sort</label><select id="sort" name="sort" disabled>{options}</select><label class="sr-only" for="year">Filter by completion year</label><select id="year" name="year" disabled {"aria-disabled=true" if state['mode']=='later' else ""}>{year_opts}</select><button disabled>Find</button></form><p class="count">{len(rows)} entries</p><ul class="entries">{items}</ul>{pagination}{summary}</main>'''
    encoded=json.dumps(state).replace('<','\\u003c')
    sort_links=' · '.join(f'<a href="{link(state,sort=key,page=1,q="")}">{label}</a>' for key,label in [('recent','Recent'),('rating','Highest rated'),('title','Title')])
    body+=f'<script type="application/json" id="diary-state">{encoded}</script><noscript><p class="no-js">Search and year filters need JavaScript. Browse and sort: {sort_links}.</p></noscript>'
    return shell(body,compact=state['compact'])
