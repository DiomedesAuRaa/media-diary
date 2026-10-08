/* Progressive enhancement only: LAN links and forms work without JavaScript. */
(function(){
  'use strict';
  function localToday(){var d=new Date();return d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2)+'-'+('0'+d.getDate()).slice(-2);}
  var form=document.querySelector('form[data-draft]');
  try {
    var saved=new URLSearchParams(location.search).get('notice');
    if(saved && saved.indexOf('Saved.')===0){var pending=sessionStorage.getItem('diary-pending');if(pending)sessionStorage.removeItem(pending);sessionStorage.removeItem('diary-pending');}
  } catch(e){}
  if(form){
    var key='diary-draft-'+form.getAttribute('data-draft');
    var fields=form.querySelectorAll('input:not([type=hidden]),select');
    var serverError=document.querySelector('[role=alert]');
    try{var draft=JSON.parse(sessionStorage.getItem(key)||'null');if(draft&&!serverError){for(var i=0;i<fields.length;i++){var field=fields[i];if(Object.prototype.hasOwnProperty.call(draft,field.name)&&(!new URLSearchParams(location.search).has('external_id')||field.name==='rating'||field.name==='date'||field.name==='remove_later')){if(field.type==='checkbox')field.checked=draft[field.name];else field.value=draft[field.name];}}}}catch(e){}
    var date=form.querySelector('[data-today="1"]');if(date&&!date.value)date.value=localToday();
    function storeDraft(){var draft={};for(var i=0;i<fields.length;i++){var field=fields[i];draft[field.name]=field.type==='checkbox'?field.checked:field.value;}try{sessionStorage.setItem(key,JSON.stringify(draft));}catch(e){}}
    form.addEventListener('input',storeDraft);form.addEventListener('change',storeDraft);
    form.addEventListener('submit',function(event){if(form.getAttribute('data-pending')){event.preventDefault();return;}form.setAttribute('data-pending','1');storeDraft();try{sessionStorage.setItem('diary-pending',key);}catch(e){}var button=form.querySelector('[data-save]');if(button){button.disabled=true;button.textContent='Saving…';}var status=form.querySelector('[data-form-status]');if(status)status.textContent='Saving your entry…';});
    var cancel=form.querySelector('[data-cancel]');if(cancel)cancel.addEventListener('click',function(){try{sessionStorage.removeItem(key);}catch(e){}});
    window.addEventListener('pageshow',function(){form.removeAttribute('data-pending');var button=form.querySelector('[data-save]');if(button){button.disabled=false;button.textContent='Save';}});
  }
  var stateNode=document.getElementById('diary-state');if(!stateNode)return;
  var state=JSON.parse(stateNode.textContent), main=document.querySelector('[data-public]'), query=new URLSearchParams(location.search);
  ['type','mode','q','sort','page','compact'].forEach(function(k){if(query.has(k))state[k]=query.get(k);});state.compact=state.compact===true||state.compact==='1';state.page=Math.max(1,Math.min(100000,parseInt(state.page,10)||1));if(['all','movies','books','tv'].indexOf(state.type)<0)state.type='movies';state.mode=state.mode==='later'?'later':'diary';if(['recent','rating','title'].indexOf(state.sort)<0)state.sort='recent';state.q=String(state.q||'').slice(0,300);
  var cache=null;
  function filename(s){return s.type+'-'+s.mode+'-'+s.sort+'-'+s.page+'-'+(s.compact?'compact':'full')+'.html';}
  function href(s){var params=new URLSearchParams();Object.keys(s).forEach(function(k){params.set(k,k==='compact'?(s[k]?'1':'0'):s[k]);});return filename(s)+'?'+params.toString();}
  function node(tag,text,cls){var el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
  function dateKey(value){var m=/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/.exec(value||'');if(!m)return value||'';var y=m[3].length===2?(parseInt(m[3],10)<69?'20':'19')+m[3]:m[3];return y+'-'+('0'+m[1]).slice(-2)+'-'+('0'+m[2]).slice(-2);}
  function render(){
    document.body.classList.toggle('compact',state.compact);
    Array.prototype.forEach.call(main.querySelectorAll('.categories a,.modes a,.view-switch'),function(a){
      var match=/^(all|movies|books|tv)-(diary|later)-(recent|rating|title)-(\d+)-(compact|full)\.html/.exec(a.getAttribute('href')||'');if(!match)return;
      var next=Object.assign({},state,{page:1});
      if(a.parentNode.classList.contains('categories')){next.type=match[1];if(next.type===state.type)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
      else if(a.parentNode.classList.contains('modes')){next.mode=match[2];if(next.mode===state.mode)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
      else{next.compact=!state.compact;a.textContent=state.compact?'Full view':'Compact view';}
      a.href=href(next);
    });

    var rows=[];['movies','books','tv'].forEach(function(type){if(state.type!=='all'&&state.type!==type)return;var title={movies:'Movie',books:'Book',tv:'Show'}[type],creator={movies:'Director',books:'Author',tv:'Creator'}[type],date=type==='books'?'Date Read/Rated':'Date Watched/Rated';(cache[type+(state.mode==='later'?'_watchlist':'')].entries||[]).forEach(function(row){if(state.q&&Object.keys(row).map(function(k){return row[k];}).join(' ').toLowerCase().indexOf(state.q.toLowerCase())<0)return;rows.push({type:type,title:row[title]||'',creator:row[creator]||'',date:row[date]||'',rating:row.Rating||''});});});
    rows.sort(function(a,b){if(state.sort==='title')return a.title.localeCompare(b.title);if(state.sort==='rating')return Number(b.rating)-Number(a.rating)||a.title.localeCompare(b.title);return dateKey(b.date).localeCompare(dateKey(a.date))||b.title.localeCompare(a.title);});
    var size=state.compact?8:20,pages=Math.max(1,Math.ceil(rows.length/size));state.page=Math.min(Math.max(1,state.page),pages);var list=main.querySelector('.entries');list.textContent='';
    rows.slice((state.page-1)*size,state.page*size).forEach(function(row){var li=node('li',undefined,'entry'),title=node('div',undefined,'entry-title');title.appendChild(node('span',row.title));if(state.mode==='diary')title.appendChild(node('span',row.rating+'/10','rating'));li.appendChild(title);var meta=state.mode==='later'?(row.type==='books'?'To read':'To watch'):(row.type==='books'?'Read ':'Watched ')+row.date;if(row.creator)meta+=' · '+row.creator;li.appendChild(node('p',meta,'meta'));list.appendChild(li);});if(!rows.length)list.appendChild(node('li',state.q?'No titles match this search.':'No entries yet.','empty'));
    main.querySelector('.count').textContent=rows.length+' items';var pager=main.querySelector('.pagination');pager.textContent='';[['Previous',state.page-1],['Next',state.page+1]].forEach(function(pair,i){if(i===1)pager.appendChild(node('span',state.page+' / '+pages));if(pair[1]<1||pair[1]>pages){pager.appendChild(node('span',pair[0]));return;}var a=node('a',pair[0]);a.href=href(Object.assign({},state,{page:pair[1]}));pager.appendChild(a);});
    var q=main.querySelector('[name=q]');if(q)q.value=state.q||'';var sort=main.querySelector('[name=sort]');if(sort)sort.value=state.sort;
  }
  function load(){if(cache){render();return Promise.resolve();}return Promise.all(['movies','books','tv','movies_watchlist','books_watchlist','tv_watchlist'].map(function(name){return fetch(name+'.json').then(function(r){if(!r.ok)throw new Error('load');return r.json();}).then(function(data){return [name,data];});})).then(function(all){cache={};all.forEach(function(pair){cache[pair[0]]=pair[1];});render();}).catch(function(){main.querySelector('.count').textContent='Search unavailable. Reload or use the category links.';});}
  main.querySelector('.find').addEventListener('submit',function(e){e.preventDefault();state.q=main.querySelector('[name=q]').value;state.sort=main.querySelector('[name=sort]').value;state.page=1;history.pushState(state,'',href(state));load();});
  // Static page links retain search and remain real links, so native Back is reliable.
  main.addEventListener('click',function(e){var target=e.target.closest('a');if(!target||!state.q||target.classList.contains('brand'))return;var match=/^(all|movies|books|tv)-(diary|later)-(recent|rating|title)-(\d+)-(compact|full)\.html/.exec(target.getAttribute('href')||'');if(match){var next={type:match[1],mode:match[2],sort:match[3],page:Number(match[4]),compact:match[5]==='compact',q:state.q};target.href=href(next);}});
  window.addEventListener('popstate',function(e){if(e.state){state=e.state;load();}else location.reload();});
  if(state.q||['type','mode','sort','page','compact'].some(function(k){return query.has(k);}))load();
}());
