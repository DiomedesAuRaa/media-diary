'use strict';
const assert = require('node:assert/strict');
const createSportsData = require('../assets/sports-data.js');

const STAMP = '2026-10-11T16:00:00.000Z';
const TODAY = '2026-10-11';
const CONFIG = {
  priority_teams:['Detroit','Lions'],
  favorite_team_ids:{NFL:['8'],NBA:['8'],NCAAFB:['130'],NCAAB:['130']},
  leagues:[
    {name:'NFL',enabled:true,espn_path:'football/nfl',standings:true,standings_type:'division'},
    {name:'NCAAFB',enabled:true,espn_path:'football/college-football',standings:true,standings_type:'rankings'},
    {name:'NCAAB',enabled:true,espn_path:'basketball/mens-college-basketball',standings:true,standings_type:'rankings'},
    {name:'F1',enabled:true,espn_path:'racing/f1',scores_type:'racing',standings:false},
    {name:'MLS',enabled:true,espn_path:'soccer/usa.1',standings:true,standings_type:'soccer'}
  ]
};

function storage(seed) {
  const map = new Map(Object.entries(seed || {}));
  return {getItem:key=>map.has(key)?map.get(key):null, setItem:(key,value)=>map.set(key,String(value)), removeItem:key=>map.delete(key), map};
}
function response(payload, ok=true) { return {ok,status:ok?200:503,json:async()=>payload}; }
function emptySnapshot() { return {version:1,lastAttemptAt:STAMP,entries:{}}; }
function makeApi(options={}) {
  const win = options.window || {location:{origin:'https://example.test',href:'https://example.test/tools/'},setTimeout,clearTimeout,AbortController};
  return createSportsData({window:win,config:options.config||CONFIG,snapshot:options.snapshot===undefined?emptySnapshot():options.snapshot,
    storage:options.storage||storage(),now:options.now||(()=>new Date(STAMP)),fetch:options.fetch,favoriteTeam:options.favoriteTeam,timers:options.timers});
}
function gameEvent(id,date,extras={}) {
  const comp={id:'comp-'+id,date,name:'Fixture '+id,status:{displayClock:'Final',period:4,type:{name:'STATUS_FINAL',shortDetail:'Final',state:'post'}},
    competitors:[
      {id:'participant-away',homeAway:'away',score:'3',winner:false,team:{id:'9',abbreviation:'AWY',shortDisplayName:'Away',displayName:'Away Team'}},
      {id:'participant-home',homeAway:'home',score:'8',winner:true,team:{id:'8',abbreviation:'DET',shortDisplayName:'Detroit',displayName:'Detroit Lions'}}
    ],links:[{href:'https://www.espn.com/gamecast/1',text:'Gamecast'},{href:'javascript:alert(1)',text:'bad'}],broadcasts:[{market:'national',names:['ESPN']}],vendorBlob:'drop',...extras};
  return {id:'event-'+id,date,name:'Event '+id,links:[{href:'https://www.espn.com/gamecast/event-'+id,text:'Event Gamecast'}],competitions:[comp]};
}
function delay(ms) { return new Promise(resolve=>setTimeout(resolve,ms)); }

async function testKeysAndLeagueQueries() {
  const api=makeApi(); await api.config();
  assert.equal(api.key('NFL','scores'),'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard');
  assert.equal(api.key('NFL','schedule'),api.key('NFL','scores'));
  assert.equal(api.key('NCAAFB','standings'),'https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings');
  assert.equal(api.key('MLS','standings'),'https://site.api.espn.com/apis/v2/sports/soccer/usa.1/standings');
  assert.throws(()=>api.key('F1','standings'),/Unsupported/);
  const seen=[];
  const queries=makeApi({fetch:async url=>{seen.push(url);return response({events:[]});}});
  await queries.load('NCAAFB','scores',{date:TODAY,force:true});
  await queries.load('NCAAB','scores',{date:TODAY,force:true});
  assert.match(seen[0],/dates=20261011&groups=80&limit=100/);
  assert.match(seen[1],/dates=20261011&groups=50&limit=365/);
}
async function testProjectionCompetitionDedupAndFavoriteIDs() {
  const payload={events:[gameEvent('a',STAMP,{competitions:[undefined]})]};
  payload.events[0].competitions=[gameEvent('a',STAMP).competitions[0],{...gameEvent('b',STAMP).competitions[0],id:'comp-b'}];
  const api=makeApi({fetch:async()=>response(payload)});
  const entry=await api.load('NFL','scores',{date:TODAY,force:true});
  assert.equal(entry.status,'ok');
  assert.equal(entry.payload.events[0].competitions.length,2);
  assert.equal(entry.payload.events[0].vendorBlob,undefined);
  const rows=api.events('NFL',entry);
  assert.equal(rows.length,2);
  assert.equal(rows[0].participants.length,2);
  assert.equal(rows[0].favorite,true);
  assert.equal(rows[0].url,'https://www.espn.com/gamecast/1');
  const eventOnly={events:[{id:'event-only',date:STAMP,name:'Event only',links:[{href:'https://www.espn.com/gamecast/event-only'}],competitions:[{id:'event-only-comp',date:STAMP,competitors:[]}]}]};
  const eventOnlyApi=makeApi({fetch:async()=>response(eventOnly)});
  const eventOnlyEntry=await eventOnlyApi.load('F1','scores',{date:TODAY,force:true});
  assert.equal(eventOnlyApi.events('F1',eventOnlyEntry)[0].url,'https://www.espn.com/gamecast/event-only');
  assert.ok(rows.every(row=>!row.url.startsWith('javascript:')));
  const duplicate={events:[gameEvent('a',STAMP),gameEvent('a',STAMP)]};
  const duplicateApi=makeApi({fetch:async()=>response(duplicate)});
  const duplicateEntry=await duplicateApi.load('NFL','scores',{date:TODAY,force:true});
  assert.equal(duplicateApi.events('NFL',duplicateEntry).length,1);
}
async function testF1EmptyCompetitorsAndMalformedPartial() {
  const f1=makeApi({fetch:async()=>response({events:[{id:'race',name:'Race',date:STAMP,competitions:[{id:'session',name:'Race Session',date:STAMP,competitors:[]}]}]})});
  const race=await f1.load('F1','scores',{date:TODAY,force:true});
  assert.equal(race.status,'ok');
  assert.equal(f1.events('F1',race).length,1);
  assert.deepEqual(f1.events('F1',race)[0].participants,[]);
  const expected=['FP1','FP2','FP3','Qual','Race'];
  const weekend={events:[{id:'mexico-gp',name:'Mexico City Grand Prix',date:STAMP,competitions:expected.map((label,index)=>({
    id:'mexico-session-'+index,name:'Mexico City Grand Prix',date:STAMP,shortName:'Mexico City GP',type:{abbreviation:label},competitors:[]
  }))}]};
  const liveF1=makeApi({fetch:async()=>response(weekend)});
  const liveEntry=await liveF1.load('F1','scores',{date:TODAY,force:true});
  assert.deepEqual(liveF1.events('F1',liveEntry).map(row=>row.session),expected);
  const f1Key='https://site.api.espn.com/apis/site/v2/sports/racing/f1/scoreboard';
  const savedF1=makeApi({snapshot:{version:1,lastAttemptAt:STAMP,entries:{[f1Key]:{payload:weekend,status:'ok',generatedAt:STAMP,lastAttemptAt:STAMP}}}});
  const savedEntry=await savedF1.saved('F1','scores',{date:TODAY});
  assert.deepEqual(savedF1.events('F1',savedEntry).map(row=>row.session),expected);
  assert.deepEqual(savedEntry.payload.events[0].competitions.map(comp=>comp.type.abbreviation),expected);
  const valid=gameEvent('valid',STAMP);
  const partial=makeApi({fetch:async()=>response({events:[valid,null,{id:'bad',competitions:[null]}]})});
  const result=await partial.load('NFL','scores',{date:TODAY,force:true});
  assert.equal(result.status,'stale');
  assert.equal(result.partial,true);
  assert.equal(partial.events('NFL',result).length,1);
}
async function testDateFilteringUsesLocalCompetitionDate() {
  const snapshot={version:1,lastAttemptAt:STAMP,entries:{}};
  snapshot.entries['https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard']={
    payload:{events:[{id:'mixed',date:'2026-10-12T01:00:00Z',name:'Mixed event',competitions:[
      {...gameEvent('local',STAMP).competitions[0],id:'local-comp',date:'2026-10-12T01:00:00Z'},
      {...gameEvent('next',STAMP).competitions[0],id:'next-comp',date:'2026-10-12T17:00:00Z'}
    ]}]},generatedAt:STAMP,lastAttemptAt:STAMP,status:'ok'
  };
  const api=makeApi({snapshot,fetch:async()=>response({events:[]})});
  const saved=await api.saved('NFL','scores',{date:TODAY});
  assert.equal(saved.source,'snapshot');
  assert.equal(saved.payload.events[0].competitions.length,1);
  assert.equal(api.events('NFL',saved).length,1);
}
async function testScheduleDateFetchConcurrencyAndDedup() {
  let active=0,maxActive=0; const dates=[];
  const api=makeApi({fetch:async url=>{
    if(!url.startsWith('https://site.web.api.espn.com/')) return response(emptySnapshot());
    const date=(new URL(url)).searchParams.get('dates'); dates.push(date);
    active++; maxActive=Math.max(maxActive,active); await delay(5); active--;
    const day=date.slice(0,4)+'-'+date.slice(4,6)+'-'+date.slice(6,8);
    const repeated={...gameEvent('same',day+'T16:00:00Z').competitions[0],id:'repeated-id',date:day+'T16:00:00Z'};
    const unique={...gameEvent('day-'+date,day+'T17:00:00Z').competitions[0],id:'comp-'+date,date:day+'T17:00:00Z'};
    return response({events:[{id:'shared-event',date:day+'T16:00:00Z',name:'Shared',competitions:[repeated,unique]}]});
  }});
  const entry=await api.load('NFL','schedule',{date:TODAY,force:true});
  assert.equal(dates.length,8);
  assert.equal(new Set(dates).size,8);
  assert.ok(maxActive<=3,maxActive);
  assert.equal(entry.coverage.complete,true);
  assert.equal(api.events('NFL',entry).length,9);
}
async function testInflightDedupeAndCancellationDoesNotCaptureNewLoad() {
  let calls=0, oldContinue=true;
  const api=makeApi({fetch:async url=>{
    if(url.startsWith('https://site.web.api.espn.com/')) {calls++; await delay(3);}
    return response({events:[gameEvent('one',STAMP)]});
  }});
  const a=api.load('NFL','scores',{date:TODAY,force:true});
  const b=api.load('NFL','scores',{date:TODAY,force:true});
  await Promise.all([a,b]);
  assert.equal(calls,1);
  calls=0;
  const old=api.load('NFL','schedule',{date:TODAY,force:true,shouldContinue:()=>oldContinue});
  await delay(1);
  oldContinue=false;
  const newest=api.load('NFL','schedule',{date:TODAY,force:true});
  const [oldResult,newResult]=await Promise.all([old,newest]);
  assert.ok(oldResult);
  assert.equal(newResult.status,'ok');
  assert.equal(newResult.coverage.complete,true);
  assert.equal(new Set(api.events('NFL',newResult).map(x=>x.id)).size,1);
}
async function testSnapshotCoverageAndFailureFallback() {
  const dates=Array.from({length:9},(_,i)=>{
    const d=new Date('2026-10-10T12:00:00Z'); d.setDate(d.getDate()+i); return d.toISOString().slice(0,10);
  });
  const url='https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard';
  const snapshot={version:1,lastAttemptAt:STAMP,entries:{[url]:{
    payload:{events:dates.map((date,i)=>gameEvent('d'+i,date+'T18:00:00Z'))},generatedAt:STAMP,lastAttemptAt:STAMP,status:'ok',
    coverage:{start:dates[0],end:dates[8],dates,complete:true}
  }}};
  const api=makeApi({snapshot,fetch:async()=>response({},false)});
  const saved=await api.saved('NFL','schedule',{date:TODAY});
  assert.equal(saved.coverage.complete,true);
  assert.equal(saved.coverage.dates.length,8);
  assert.equal(api.events('NFL',saved).length,8);
  const live=await api.load('NFL','schedule',{date:TODAY,force:true});
  assert.equal(live.status,'stale');
  assert.equal(live.generatedAt,STAMP);
  assert.equal(live.lastAttemptAt,STAMP);
  assert.equal(live.source,'snapshot');
}
async function testCacheValidationAndFreshness() {
  const key='sports_data_v2';
  const id='scores|football/nfl|'+TODAY;
  const seed=storage({[key]:JSON.stringify({version:2,entries:{[id]:{
    payload:{events:[gameEvent('cached',STAMP),{id:'bad',competitions:[null]}]},status:'ok',generatedAt:STAMP,lastAttemptAt:STAMP,source:'evil',
    injected:'not kept'
  }}})});
  let requests=0;
  const api=makeApi({storage:seed,fetch:async()=>{requests++;return response({events:[]});}});
  const cache=await api.saved('NFL','scores',{date:TODAY});
  assert.equal(cache.source,'cache');
  assert.equal(cache.status,'stale');
  assert.equal(cache.partial,true);
  assert.equal(cache.injected,undefined);
  assert.equal(cache.payload.events.length,1);
  const futureApi=makeApi({now:()=>new Date('2026-10-11T16:02:00.000Z'),storage:seed,fetch:async()=>{requests++;return response({events:[]});}});
  const futureCache=await futureApi.saved('NFL','scores',{date:TODAY});
  assert.equal(futureCache && futureCache.source,'cache');
  assert.equal(futureCache.status,'stale');
  const olderStorage=storage({[key]:JSON.stringify({version:2,entries:{[id]:{payload:{events:[gameEvent('cached',STAMP)]},status:'stale',generatedAt:'2026-10-11T15:40:00.000Z',lastAttemptAt:'2026-10-11T15:40:00.000Z'}}})});
  const published={version:1,lastAttemptAt:'2026-10-11T15:55:00.000Z',entries:{
    'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard':{payload:{events:[gameEvent('published',STAMP)]},status:'ok',generatedAt:'2026-10-11T15:55:00.000Z',lastAttemptAt:'2026-10-11T15:55:00.000Z'}
  }};
  const newest=makeApi({storage:olderStorage,snapshot:published,now:()=>new Date(STAMP)});
  assert.equal((await newest.saved('NFL','scores',{date:TODAY})).source,'snapshot');
}
async function testFavoriteAliasesOnlyWhenNoIDMap() {
  const config={priority_teams:['Lions'],leagues:[{name:'NFL',enabled:true,espn_path:'football/nfl'}]};
  let aliasCalls=0;
  const api=makeApi({config,favoriteTeam:(team,aliases)=>{aliasCalls++;return team.displayName==='Detroit Lions'&&aliases.includes('Lions');},fetch:async()=>response({events:[gameEvent('alias',STAMP)]})});
  const entry=await api.load('NFL','scores',{date:TODAY,force:true});
  assert.equal(api.events('NFL',entry)[0].favorite,true);
  assert.ok(aliasCalls>0);
}
async function testBrowserStyleFactoryPrefersBoundToolUIFetch() {
  let calls=0;
  const browser={location:{origin:'https://example.test',href:'https://example.test/tools/'},setTimeout,clearTimeout,AbortController,
    ToolUI:{fetch:async()=>{calls++;return response(CONFIG);}},fetch:async()=>{throw new Error('unbound native fetch used');}};
  const api=createSportsData({window:browser});
  const config=await api.config();
  assert.equal(config.leagues[0].name,'NFL');
  assert.equal(calls,1);
}
async function testDateValidationOnUTCPlus14() {
  const prior=process.env.TZ; process.env.TZ='Pacific/Kiritimati';
  try {
    const urls=[];
    const api=makeApi({fetch:async url=>{urls.push(url);return response({events:[]});}});
    await api.load('NFL','scores',{date:'2026-10-11',force:true});
    assert.ok(urls.some(url=>url.includes('dates=20261011')));
  } finally { if (prior === undefined) delete process.env.TZ; else process.env.TZ=prior; }
}
async function testColdLiveLoadsDoNotWaitForSlowPublishedSnapshot() {
  const urls=[];
  const api=makeApi({snapshot:null,timers:{setTimeout:()=>1,clearTimeout:()=>{}},fetch:async url=>{
    urls.push(url);
    if(url.endsWith('sports-snapshot.json')) return new Promise(()=>{});
    if(url.includes('/standings?')) return response({name:'NFL',children:[{name:'Division',standings:{entries:[]}}]});
    return response({events:[]});
  }});
  const started=Date.now();
  const scores=await Promise.race([api.load('NFL','scores',{date:TODAY,force:true}),delay(300).then(()=>{throw new Error('scores waited on the published snapshot');})]);
  const standings=await Promise.race([api.load('NFL','standings',{force:true}),delay(300).then(()=>{throw new Error('standings waited on the published snapshot');})]);
  assert.equal(scores.status,'ok');
  assert.equal(standings.status,'ok');
  assert.ok(Date.now()-started<300);
  assert.ok(urls.some(url=>url.startsWith('https://site.web.api.espn.com/')));
  assert.ok(urls.some(url=>url.endsWith('sports-snapshot.json')));
}

(async()=>{
  const tests=[testKeysAndLeagueQueries,testProjectionCompetitionDedupAndFavoriteIDs,testF1EmptyCompetitorsAndMalformedPartial,
    testDateFilteringUsesLocalCompetitionDate,testScheduleDateFetchConcurrencyAndDedup,testInflightDedupeAndCancellationDoesNotCaptureNewLoad,
    testSnapshotCoverageAndFailureFallback,testCacheValidationAndFreshness,testFavoriteAliasesOnlyWhenNoIDMap,
    testBrowserStyleFactoryPrefersBoundToolUIFetch,testDateValidationOnUTCPlus14,testColdLiveLoadsDoNotWaitForSlowPublishedSnapshot];
  for(const test of tests){ await test(); console.log('ok - '+test.name); }
  console.log('sports-data fixture tests passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
