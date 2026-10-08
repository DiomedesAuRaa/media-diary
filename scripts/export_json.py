#!/usr/bin/env python3
"""Publish only explicitly approved diary datasets/fields, plus read-only HTML."""
from __future__ import annotations
import csv
import json
import sys
import shutil
import tempfile
import os
from pathlib import Path

REPO_ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(REPO_ROOT))
from app.presentation import PUBLIC_FIELDS, browse, normalized, filtered, static_name
DATA_DIR=REPO_ROOT/'data'
DOCS_DIR=REPO_ROOT/'docs'
EXPORTS={name+suffix:DATA_DIR/f'{name+suffix}.csv' for name in PUBLIC_FIELDS for suffix in ('','_watchlist')}

def export_csv(name,csv_path):
    fields=PUBLIC_FIELDS[name.removesuffix('_watchlist')]
    rows=[]
    if csv_path.exists():
        with csv_path.open(encoding='utf-8',newline='') as handle:
            rows=[{field:row.get(field,'') for field in fields} for row in csv.DictReader(handle)]
    DOCS_DIR.mkdir(parents=True,exist_ok=True)
    (DOCS_DIR/f'{name}.json').write_text(json.dumps({'entries':rows},indent=2),encoding='utf-8')
    return rows

def generate():
    data={name:export_csv(name,path) for name,path in EXPORTS.items()}
    assets=DOCS_DIR/'assets';assets.mkdir(parents=True,exist_ok=True)
    for name in ('diary.css','diary.js'):shutil.copyfile(REPO_ROOT/'static'/name,assets/name)
    # Delete only our own prior page names; unrelated documents are left alone.
    for page in DOCS_DIR.glob('*-*-*-*-*.html'):
        if page.name.split('-')[0] in ('all','movies','books','tv'):page.unlink()
    for typ in ('all','movies','books','tv'):
        for mode in ('diary','later'):
            for sort in ('recent','rating','title'):
                for compact in (False,True):
                    state=normalized({'type':typ,'mode':mode,'sort':sort,'compact':int(compact)})
                    count=len(filtered(data,state));size=8 if compact else 20
                    for page in range(1,max(1,(count+size-1)//size)+1):
                        state['page']=page
                        (DOCS_DIR/static_name(state)).write_text(browse(data,state,public=True),encoding='utf-8')
    default=normalized({})
    (DOCS_DIR/'index.html').write_text(browse(data,default,public=True),encoding='utf-8')
    # Stable compact bookmark has content even with JavaScript disabled.
    (DOCS_DIR/'compact.html').write_text(browse(data,normalized({'compact':'1'}),public=True),encoding='utf-8')
    print(f'Published {sum(len(v) for v in data.values())} records in six approved datasets.')
    return 0

def main():
    global DOCS_DIR
    target=DOCS_DIR
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=Path(tempfile.mkdtemp(prefix='.diary-export-',dir=target.parent))
    backup=temporary.with_name(temporary.name+'-previous')
    try:
        DOCS_DIR=temporary
        generate()
        if target.exists():os.replace(target,backup)
        try:os.replace(temporary,target)
        except OSError:
            if backup.exists():os.replace(backup,target)
            raise
        if backup.exists():shutil.rmtree(backup)
        return 0
    finally:
        DOCS_DIR=target
        if temporary.exists():shutil.rmtree(temporary)

if __name__=='__main__':raise SystemExit(main())
