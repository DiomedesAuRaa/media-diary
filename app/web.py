"""LAN-only HTML interface. Basic links/forms work without JavaScript."""
from __future__ import annotations
from datetime import datetime
import hashlib
import hmac
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.config import MEDIA_TYPES
from app.csv_store import storage_lock, read_entries, build_row, build_watchlist_row, prepend_entry, title_exists, replace_entry_by_key
from app.git_sync import sync_csv_async, get_sync_status
from app.providers import get_provider
from app.presentation import browse, shell, esc, normalized, records, date_value, LABELS

router=APIRouter()
_secret=secrets.token_bytes(32)
_used={}

def csrf():
    nonce=f'{int(time.time())}.{secrets.token_hex(16)}'
    return nonce+'.'+hmac.new(_secret,nonce.encode(),hashlib.sha256).hexdigest()

def check_token(token):
    try:
        stamp,nonce,digest=token.split('.')
        return abs(time.time()-int(stamp))<86400 and hmac.compare_digest(digest,hmac.new(_secret,f'{stamp}.{nonce}'.encode(),hashlib.sha256).hexdigest())
    except (ValueError,AttributeError):return False

def data():
    with storage_lock:
        return {typ+suffix:read_entries(typ,use_watchlist=bool(suffix)) for typ in MEDIA_TYPES for suffix in ('','_watchlist')}

def hidden(name,value):return f'<input type="hidden" name="{esc(name)}" value="{esc(value)}">'

def find_record(typ,mode,key):
    return next((r['row'] for r in records(data(),mode) if r['type']==typ and r['key']==key),None)

def typ_check(typ):
    if typ not in MEDIA_TYPES:raise HTTPException(404,'Unknown category')
    return MEDIA_TYPES[typ]

@router.get('/', response_class=HTMLResponse)
def index(request:Request):
    status=get_sync_status()
    publication='Public publication needs attention; local entries are safe.' if status.get('last_error') else 'Public diary update is pending.' if status.get('pending') else 'Changes sent for public publication.' if status.get('last_ok') else 'Your entries are saved locally.'
    notice=request.query_params.get('notice','')[:300]
    return browse(data(),normalized(request.query_params),notice=notice,publication=publication)

@router.get('/record',response_class=HTMLResponse)
def detail(request:Request):
    p=request.query_params;typ=p.get('type','movies');cfg=typ_check(typ);mode='later' if p.get('mode')=='later' else 'diary';key=p.get('key','');compact=p.get('compact')=='1';row=find_record(typ,mode,key)
    if row is None:raise HTTPException(404,'This entry changed. Return to the diary and try again.')
    params=urlencode({'type':typ,'mode':mode,'key':key,'compact':int(compact)})
    values=''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k,v in row.items() if v)
    action=f'<a class="primary" href="/log?{params}&intent=complete">Log as {"read" if typ=="books" else "watched"}</a>' if mode=='later' else f'<a class="primary" href="/log?{params}&intent=edit">Edit this entry</a><a href="/log?{params}&intent=repeat">Log another {"reading" if typ=="books" else "viewing"}</a>'
    body=f'<main id="main" class="detail"><a href="/?type={typ}&mode={mode}&compact={int(compact)}">Back to diary</a><h1>{esc(row[cfg["title_column"]])}</h1><dl>{values}</dl><div class="actions">{action}</div><details><summary>Remove entry</summary><p>Removal cannot be undone here.</p><form method="post" action="/remove">'+''.join(hidden(k,v) for k,v in {'type':typ,'mode':mode,'key':key,'compact':int(compact),'csrf':csrf()}.items())+'<button class="danger">Confirm removal</button></form></details></main>'
    return shell(body,compact=compact)

def render_form(p, error='', results=None):
    typ=p.get('type','movies');cfg=typ_check(typ);compact=str(p.get('compact','0'))=='1';intent=p.get('intent','new');mode=p.get('mode','diary');later=p.get('task','completed')=='later';row=find_record(typ,mode,p.get('key','')) if p.get('key') else None
    if intent in ('edit','repeat','complete') and row is None and not error:raise HTTPException(409,'This entry changed. Return to the diary and try again.')
    title=p.get('title',row.get(cfg['title_column'],'') if row else '');rating=p.get('rating',row.get('Rating','') if row and intent=='edit' else '');date=p.get('date',date_value(row.get(cfg['auto_fields'][0],'')) if row and intent=='edit' else '')
    fixed=intent in ('edit','repeat','complete')
    categories=''.join(f'<a href="/log?type={t}&compact={int(compact)}" {"aria-current=page" if t==typ else ""}>{LABELS[t]}</a>' for t in MEDIA_TYPES)
    tasks='' if fixed else f'<nav aria-label="Logging task"><a href="/log?type={typ}&compact={int(compact)}&task=completed" {"aria-current=page" if not later else ""}>Log completed</a><a href="/log?type={typ}&compact={int(compact)}&task=later" {"aria-current=page" if later else ""}>Save for later</a></nav>'
    heading={'edit':'Edit this entry','repeat':f'Log another {"reading" if typ=="books" else "viewing"}','complete':f'Log as {"read" if typ=="books" else "watched"}'}.get(intent,'Save for later' if later else 'Log completed')
    base={'type':typ,'task':'later' if later else 'completed','intent':intent,'key':p.get('key',''),'mode':mode,'compact':int(compact)}
    fields=''.join(hidden(k,v) for k,v in {**base,'csrf':p.get('csrf') if check_token(p.get('csrf','')) else csrf()}.items())
    fields+=f'<label for="title">Title</label><input id="title" name="title" required maxlength="500" value="{esc(title)}">'
    if not later:
        options='<option value="">Choose rating</option>'+''.join(f'<option value="{n}" {"selected" if str(n)==str(rating) else ""}>{n}/10</option>' for n in range(1,11))
        fields+=f'<label for="rating">Rating</label><select id="rating" name="rating" required>{options}</select><label for="date">Date {"read" if typ=="books" else "watched"}</label><input id="date" name="date" type="date" value="{esc(date)}" data-today="{0 if intent=="edit" else 1}"><p class="meta">Leave blank to use today. Existing dates remain unchanged when editing.</p>'
    for field in cfg['api_fields']:
        value=p.get(field,row.get(field,'') if row else '')
        fields+=f'<label>{esc(field)}<input name="{esc(field)}" value="{esc(value)}" maxlength="500"></label>'
    if intent=='complete':
        checked='checked' if p.get('remove_later')=='1' or 'csrf' not in p else ''
        fields+=f'<label><input type="checkbox" name="remove_later" value="1" {checked}> Remove from for later after saving</label>'
    if not fixed and not later:
        fields+='<label for="strategy">If this title is already logged</label><select name="strategy" id="strategy"><option value="ask">Ask me before adding a repeat</option><option value="rewatch">Log another reading/viewing</option></select>'
    lookup=''
    if intent!='edit':
        lookup='<details '+('open' if results is not None else '')+'><summary>Find title metadata (optional)</summary><p>Manual entry works without a provider.</p><form method="get" action="/log">'+''.join(hidden(k,v) for k,v in base.items())+f'<label for="lookup">Title to find</label><input id="lookup" name="lookup" value="{esc(p.get("lookup",title))}"><button>Search metadata</button></form>'
        if results is not None:
            lookup+='<ul class="lookup-results">'+''.join(f'<li><a href="/log?{esc(urlencode({**base,"external_id":r.get("id",""),"title":r.get("title","")}))}">{esc(r.get("subtitle") or r.get("title"))}</a></li>' for r in results)+'</ul>' if results else '<p>No matches. Enter the title manually below.</p>'
        lookup+='</details>'
    error_html=f'<p role="alert" class="notice error">{esc(error)}</p>' if error else ''
    return shell(f'<main id="main"><a href="/?type={typ}&compact={int(compact)}">Back to diary</a><h1>{heading} · {LABELS[typ]}</h1>{"" if fixed else f"<nav aria-label=Category>{categories}</nav>"}{tasks}<section class="form-card">{error_html}{lookup}<form method="post" action="/save" data-draft="{typ}-{intent}-{base["key"]}-{base["task"]}">{fields}<div class="actions"><button class="primary" data-save>Save</button><a data-cancel href="/?type={typ}&compact={int(compact)}">Cancel</a></div><p role="status" data-form-status></p></form></section></main>',compact=compact,title=heading)

@router.get('/log',response_class=HTMLResponse)
async def log(request:Request):
    p=dict(request.query_params);cfg=typ_check(p.get('type','movies'));error='';results=None
    if p.get('lookup'):
        try:results=await get_provider(cfg['provider']).search(p['lookup'][:300])
        except Exception:error='Metadata search is unavailable. You can enter the title manually.'
    if p.get('external_id'):
        try:p.update(await get_provider(cfg['provider']).lookup(p['external_id']))
        except Exception:error='Metadata lookup is unavailable. Your title is preserved; enter other details manually.'
    return render_form(p,error,results)

async def form_data(request):
    if request.headers.get('origin') and urlsplit(request.headers['origin']).netloc != request.url.netloc:raise HTTPException(403,'Use the diary form on this device.')
    if request.headers.get('content-type','').split(';')[0]!='application/x-www-form-urlencoded':raise HTTPException(415,'Use the diary HTML form.')
    raw=await request.body()
    if len(raw)>20000:raise HTTPException(413,'Form too large')
    p={k:v[-1] for k,v in parse_qs(raw.decode(),keep_blank_values=True).items()}
    if not check_token(p.get('csrf','')):raise HTTPException(403,'This form expired. Reload the diary.')
    return p

@router.post('/save',response_class=HTMLResponse)
async def save(request:Request):
    p=await form_data(request);typ=p.get('type','movies');cfg=typ_check(typ);intent=p.get('intent','new');later=p.get('task')=='later';token=p['csrf']
    try:
        if intent in ('edit','repeat','complete') and later:raise ValueError('Completed logging requires a rating and date.')
        title=p.get('title','').strip()
        if not title or len(title)>500:raise ValueError('Enter a title of 1–500 characters.')
        date=p.get('date','')
        if date:date=datetime.strptime(date,'%Y-%m-%d').strftime('%m/%d/%y')
        if not later:
            rating=int(p.get('rating',''))
            if not 1<=rating<=10:raise ValueError('Choose a rating from 1 to 10.')
        api={field:p.get(field,'')[:500] for field in cfg['api_fields']}
        with storage_lock:
            if token in _used:return RedirectResponse(_used[token][0],303)
            for key,(_,stamp) in list(_used.items()):
                if time.time()-stamp>86400:del _used[key]
            if intent=='edit':
                original=find_record(typ,'diary',p.get('key',''))
                if original is None:raise ValueError('This entry changed. Return to the diary and reopen it.')
                row=build_row(typ,title=title,rating=str(rating),date_rated=date or original[cfg['auto_fields'][0]],api_values=api)
                if replace_entry_by_key(typ,p['key'],row) is None:raise ValueError('The entry changed before saving. Please reopen it.')
            elif later:
                if title_exists(typ,title,use_watchlist=True):raise ValueError('This title is already saved for later.')
                prepend_entry(typ,build_watchlist_row(typ,title=title,api_values=api),use_watchlist=True)
            else:
                if intent not in ('repeat','complete') and title_exists(typ,title) and p.get('strategy')!='rewatch':raise ValueError('This title is already logged. Choose “Log another reading/viewing” below, or open its existing entry to edit.')
                if intent=='complete' and find_record(typ,'later',p.get('key','')) is None:raise ValueError('The for-later item changed. Reopen it before logging completion.')
                prepend_entry(typ,build_row(typ,title=title,rating=str(rating),date_rated=date or None,api_values=api))
                # Saving the diary comes first: a removal failure preserves the future item.
                if intent=='complete' and p.get('remove_later')=='1':
                    try:replace_entry_by_key(typ,p['key'],None,use_watchlist=True)
                    except OSError:
                        p['removal_failed']='1'
            sync_csv_async(typ,f'{typ}: diary form save')
            notice='Saved. Public diary updating.' if p.get('removal_failed')!='1' else 'Saved. The for-later item could not be removed; it is still safe in your list.'
            target='/?'+urlencode({'type':typ,'mode':'later' if later else 'diary','compact':p.get('compact','0'),'notice':notice})
            _used[token]=(target,time.time())
        response=RedirectResponse(target,303);response.headers['X-Diary-Saved']='1';return response
    except (ValueError,OSError) as exc:
        message=str(exc) if isinstance(exc,ValueError) else 'Could not save. Your draft is preserved; try again.'
        return HTMLResponse(render_form(p,message),status_code=422)

@router.post('/remove')
async def remove(request:Request):
    p=await form_data(request);typ=p.get('type','movies');typ_check(typ);later=p.get('mode')=='later';token=p['csrf']
    with storage_lock:
        if token in _used:return RedirectResponse(_used[token][0],303)
        if replace_entry_by_key(typ,p.get('key',''),None,use_watchlist=later) is None:raise HTTPException(409,'Entry changed. Return to diary and reopen it.')
        sync_csv_async(typ,f'{typ}: diary form remove')
        target='/?'+urlencode({'type':typ,'mode':'later' if later else 'diary','compact':p.get('compact','0'),'notice':'Entry removed. Public diary updating.'});_used[token]=(target,time.time())
    return RedirectResponse(target,303)
