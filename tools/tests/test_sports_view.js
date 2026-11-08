'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag, value='') { this.tag=tag; this.textContent=value; this.children=[]; this.dataset={}; this.style={}; this.attrs={}; this.listeners={}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  setAttribute(key,value) { this.attrs[key]=value; }
  addEventListener(name,handler) { this.listeners[name]=handler; }
  contains() { return false; }
  focus() {}
}
function descendants(element) { return element.children.filter(n=>typeof n==='object').flatMap(n=>[n,...descendants(n)]); }
async function view(mode='scores', hash='') {
  const ids={};
  for(const name of ['sports-content','sports-league','sports-date','sports-page-label','sports-refresh','sports-prev-day','sports-next-day','sports-today']) ids[name]=new Element('div');
  const leagues=[{name:'EPL',enabled:true},{name:'NFL',enabled:true},{name:'NBA',enabled:true}];
  const calls=[];
  const eventDate=new Date(Date.now()+3600000).toISOString();
  const events={EPL:[{id:'soccer',favorite:false}],NFL:Array.from({length:13},(_,i)=>({id:'nfl-'+i,favorite:i===12})),NBA:[{id:'pistons',favorite:true}]};
  const location={hash};
  const context={console,URLSearchParams,Option:class extends Element {constructor(label,value){super('option',label);this.value=value;}},
    location,history:{pushState:(_,__,hash)=>{location.hash=hash;}},
    document:{body:{dataset:{sportsMode:mode}},getElementById:id=>ids[id],querySelectorAll:()=>[],addEventListener:()=>{},activeElement:null},
    ToolUI:{text:(tag,value,cls)=>Object.assign(new Element(tag,value),{className:cls||''}),httpURL:()=>null},
    SportsScoreDisplay:{score:()=>'-'},
    SportsData:{config:async()=>({leagues,favorite_team_ids:{NFL:['8'],NBA:['8']}}),saved:async()=>null,
      load:async league=>{calls.push(league.name);return {payload:{},status:'ok',source:'live',retrievedAt:eventDate};},
      events:league=>events[league.name].map(e=>({...e,date:eventDate,name:e.id,state:'pre',participants:[]}))}}
  context.window={SportsData:context.SportsData,addEventListener:()=>{},setInterval:()=>{}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../assets/sports-view.js'),'utf8'),context);
  for(let i=0;i<5;i++) await new Promise(resolve=>setImmediate(resolve));
  return {ids,calls,location};
}
(async()=>{
  for(const mode of ['scores','schedule']) {
    const {ids,calls}=await view(mode);
    assert.equal(ids['sports-league'].value,'all','unfiltered opening view');
    assert.deepEqual(calls,['NFL','NBA','EPL'],'favorite leagues requested first');
    const nodes=descendants(ids['sports-content']);
    const cards=nodes.filter(n=>n.tag==='article');
    assert.equal(cards.length,15,'all games are scrollable, beyond the old ten-game limit');
    assert.deepEqual(cards.slice(0,2).map(n=>n.dataset.eventId),['nfl-12','pistons']);
    assert.equal(new Set(cards.map(n=>n.dataset.eventId)).size,15,'favorites never repeat below');
    assert.deepEqual(nodes.filter(n=>n.className==='sports-group-title').map(n=>n.textContent),['Favorite teams','EPL','NFL']);
    assert.equal(nodes.filter(n=>n.className==='sports-pager').length,0,'default has no pager');
  }
  const filtered=await view('scores','#section-NFL');
  assert.deepEqual(filtered.calls,['NFL'],'explicit league still loads only its own data');
  assert.equal(filtered.ids['sports-league'].value,'NFL');
  assert.equal(descendants(filtered.ids['sports-content']).filter(n=>n.tag==='article').length,10);
  const favorites=await view('scores','#section-FAVORITES');
  assert.deepEqual(favorites.calls,['NFL','NBA']);
  assert.deepEqual(descendants(favorites.ids['sports-content']).filter(n=>n.tag==='article').map(n=>n.dataset.eventId),['nfl-12','pistons']);
  console.log('Sports opening-view fixtures passed (scores, upcoming, league and favorites filters).');
})().catch(error=>{console.error(error);process.exitCode=1;});
