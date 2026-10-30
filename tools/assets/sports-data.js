/* Shared, bounded ESPN client for scores, schedule and standings. */
(function (root, createFactory) {
  'use strict';
  var createSportsData = createFactory();
  if (typeof module === 'object' && module.exports) module.exports = createSportsData;
  else root.SportsData = createSportsData(root);
}(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  var CONFIG_URL = 'sports-config.json';
  var SNAPSHOT_URL = 'sports-snapshot.json';
  var CACHE_KEY = 'sports_data_v2';
  var MAX_CACHE_ENTRIES = 64;
  var MAX_CACHE_CHARS = 3000000;
  var MAX_COMPETITIONS = 4000;
  var REQUEST_TIMEOUT = 12000;
  var SCHEDULE_BUDGET = 36000;
  var MAX_ACTIVE = 3;
  var ALLOWED_TYPES = {division:1, rankings:1, soccer:1, f1:1};

  function createSportsData(environment) {
    var env = environment || {};
    var global = env.window || (typeof window !== 'undefined' ? window : {});
    var localStorage = env.storage || null;
    if (!localStorage) { try { localStorage = global.localStorage || null; } catch (_) { localStorage = null; } }
    var toolFetch = (env.ToolUI || global.ToolUI) && (env.ToolUI || global.ToolUI).fetch;
    var fetchImpl = env.fetchJSON || (toolFetch ? toolFetch.bind(env.ToolUI || global.ToolUI) : (env.fetch || global.fetch) && (env.fetch || global.fetch).bind(env.fetch ? env : global));
    var now = env.now || function () { return new Date(); };
    var timers = env.timers || global;
    var currentConfig = null;
    var configPromise = null;
    var snapshotData = env.snapshot || null;
    var snapshotPromise = null;
    var memoryCache = Object.create(null);
    var inFlight = Object.create(null);
    var activeRequests = 0;
    var waiters = [];

    function isoNow() { return now().toISOString(); }
    function safeGet(key) { try { return localStorage ? localStorage.getItem(key) : null; } catch (_) { return null; } }
    function safeSet(key, value) { try { if (localStorage) localStorage.setItem(key, value); } catch (_) {} }
    function validDate(value) {
      if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
      var parts = value.split('-').map(Number), parsed = new Date(parts[0], parts[1] - 1, parts[2]);
      return Number.isFinite(parsed.getTime()) && parsed.getFullYear() === parts[0] && parsed.getMonth() === parts[1] - 1 && parsed.getDate() === parts[2];
    }
    function localDate(date) {
      return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
    }
    function eventLocalDay(value) {
      if (typeof value !== 'string') return '';
      if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return validDate(value) ? value : '';
      var parsed = new Date(value);
      return Number.isFinite(parsed.getTime()) ? localDate(parsed) : '';
    }
    function clockMs() { return now().getTime(); }
    function addDays(dateString, amount) {
      var d = new Date(dateString + 'T12:00:00');
      d.setDate(d.getDate() + amount);
      return localDate(d);
    }
    function dateParam(dateString) { return dateString.replace(/-/g, ''); }
    function cleanText(value, max) {
      if (typeof value !== 'string') return undefined;
      var text = value.replace(/[\u0000-\u001f\u007f]/g, '').trim();
      return text ? text.slice(0, max || 200) : undefined;
    }
    function safeURL(value) {
      if (typeof value !== 'string' || value.length > 2048) return '';
      try {
        var u = new URL(value);
        if ((u.protocol !== 'https:' && u.protocol !== 'http:') || u.username || u.password) return '';
        return u.href;
      } catch (_) { return ''; }
    }
    function validPath(value) {
      return typeof value === 'string' && value.length <= 200 && /^[a-z0-9]+(?:[.-][a-z0-9]+)*(?:\/[a-z0-9]+(?:[.-][a-z0-9]+)*)*$/i.test(value);
    }
    function sanitizeConfig(raw) {
      if (!raw || !Array.isArray(raw.leagues) || raw.leagues.length > 30) throw new Error('Invalid sports configuration');
      var seen = Object.create(null);
      var leagues = raw.leagues.map(function (item) {
        if (!item || typeof item.name !== 'string' || !item.name.trim() || !validPath(item.espn_path)) throw new Error('Invalid league configuration');
        var path = item.espn_path.toLowerCase();
        if (seen[item.name] || Object.keys(seen).some(function (name) { return seen[name] === path; })) throw new Error('Duplicate league configuration');
        seen[item.name] = path;
        var standingsType = item.standings_type || 'division';
        var scoresType = item.scores_type || 'default';
        if (!ALLOWED_TYPES[standingsType] || ['default', 'racing'].indexOf(scoresType) < 0) throw new Error('Invalid sports type');
        return {name:item.name.slice(0, 80), enabled:item.enabled !== false, espn_path:path,
          standings_type:standingsType, scores_type:scoresType, standings:item.standings !== false,
          color:typeof item.color === 'string' && /^#[0-9a-f]{3,8}$/i.test(item.color) ? item.color : ''};
      });
      var aliases = Array.isArray(raw.priority_teams) ? raw.priority_teams.filter(function (x) { return typeof x === 'string'; }).slice(0, 100) : [];
      var inputIds = raw.favorite_team_ids && typeof raw.favorite_team_ids === 'object' && !Array.isArray(raw.favorite_team_ids) ? raw.favorite_team_ids : {};
      var favoriteIds = {};
      leagues.forEach(function (item) {
        var value = Object.prototype.hasOwnProperty.call(inputIds, item.name) ? inputIds[item.name] : inputIds[item.espn_path];
        if (Array.isArray(value)) favoriteIds[item.name] = value.slice(0, 100).filter(function (id) { return typeof id === 'string' && /^\d{1,20}$/.test(id); });
      });
      return {priority_teams:aliases, favorite_team_ids:favoriteIds, leagues:leagues};
    }
    function clone(value) { return JSON.parse(JSON.stringify(value)); }
    function config() {
      if (currentConfig) return Promise.resolve(clone(currentConfig));
      if (configPromise) return configPromise.then(clone);
      configPromise = jsonRequest(CONFIG_URL).then(sanitizeConfig).then(function (value) {
        currentConfig = value;
        return value;
      }).catch(function (error) { configPromise = null; throw error; });
      return configPromise.then(clone);
    }
    function resolveLeague(league) {
      if (!currentConfig) throw new Error('Call SportsData.config() before SportsData.key()');
      var name = typeof league === 'string' ? league : league && league.name;
      var result = currentConfig.leagues.find(function (item) { return item.name === name && item.enabled; });
      if (!result) throw new Error('League is not enabled');
      return result;
    }
    function key(league, kind) {
      var item = resolveLeague(league);
      if (kind === 'scores' || kind === 'schedule') return 'https://site.api.espn.com/apis/site/v2/sports/' + item.espn_path + '/scoreboard';
      if (kind !== 'standings' || !item.standings) throw new Error('Unsupported sports data kind');
      if (item.standings_type === 'rankings') return 'https://site.api.espn.com/apis/site/v2/sports/' + item.espn_path + '/rankings';
      if (item.standings_type === 'f1') return 'https://site.api.espn.com/apis/v2/sports/racing/f1/standings';
      return 'https://site.api.espn.com/apis/v2/sports/' + item.espn_path + '/standings';
    }
    function requestURL(url, timeoutMs) {
      var parsed;
      try { parsed = new URL(url, global.location && global.location.href ? global.location.href : 'https://local.invalid/'); }
      catch (_) { return Promise.reject(new Error('Invalid request URL')); }
      var isLocal = parsed.origin === (global.location && global.location.origin);
      var isEspn = parsed.protocol === 'https:' && parsed.hostname === 'site.web.api.espn.com' && !parsed.username && !parsed.password && (!parsed.port || parsed.port === '443');
      if (!isLocal && !isEspn) return Promise.reject(new Error('Sports URL is outside the allowlist'));
      if (!fetchImpl) return Promise.reject(new Error('Fetch is unavailable'));
      var controller = typeof global.AbortController === 'function' ? new global.AbortController() : null;
      var options = controller ? {signal:controller.signal, cache:'no-cache'} : {cache:'no-cache'};
      var settled = false, timer;
      var deadline = new Promise(function (_, reject) {
        timer = timers.setTimeout(function () {
          if (controller) try { controller.abort(); } catch (_) {}
          settled = true;
          reject(new Error('Sports request timed out'));
        }, timeoutMs || REQUEST_TIMEOUT);
      });
      var request;
      try { request = fetchImpl(url, options); } catch (error) { timers.clearTimeout(timer); return Promise.reject(error); }
      return Promise.race([Promise.resolve(request).then(function (response) {
        if (!response || response.ok === false) throw new Error('Sports request failed' + (response && response.status ? ' (' + response.status + ')' : ''));
        return Promise.resolve(response.json()).then(function (payload) { return payload; });
      }), deadline]).then(function (payload) {
        if (!settled) { settled = true; timers.clearTimeout(timer); }
        return payload;
      }, function (error) {
        if (!settled) { settled = true; timers.clearTimeout(timer); }
        throw error;
      });
    }
    function jsonRequest(url) { return requestURL(url, REQUEST_TIMEOUT); }
    function cacheStore() {
      try {
        var value = JSON.parse(safeGet(CACHE_KEY) || 'null');
        if (!value || value.version !== 2 || !value.entries || typeof value.entries !== 'object' || !currentConfig) return {};
        var cleaned = Object.create(null);
        Object.keys(value.entries).forEach(function (id) {
          var parts = id.split('|'), kind = parts[0], path = parts[1];
          if (!/^(scores|schedule|standings)$/.test(kind) || !path) return;
          var league = currentConfig.leagues.find(function (item) { return item.enabled && item.espn_path === path; });
          if (!league || (kind === 'standings' && !league.standings)) return;
          if (kind === 'scores' && (parts.length !== 3 || !validDate(parts[2]))) return;
          if (kind === 'schedule') {
            var window = parts[2] && parts[2].split('..');
            if (parts.length !== 3 || !window || window.length !== 2 || !validDate(window[0]) || !validDate(window[1])) return;
          }
          if (kind === 'standings' && parts.length !== 2) return;
          var entry = sourceEntry(value.entries[id], 'cache');
          if (entry && entry.status !== 'unavailable') cleaned[id] = entry;
        });
        var ids = Object.keys(cleaned).sort(function (a, b) { return Date.parse(cleaned[b].lastAttemptAt) - Date.parse(cleaned[a].lastAttemptAt); });
        ids.slice(MAX_CACHE_ENTRIES).forEach(function (id) { delete cleaned[id]; });
        return cleaned;
      } catch (_) { return {}; }
    }
    function writeCache(id, entry) {
      var entries = cacheStore();
      entries[id] = entry;
      var keys = Object.keys(entries).sort(function (a, b) { return Date.parse(entries[a].lastAttemptAt || entries[a].generatedAt || 0) - Date.parse(entries[b].lastAttemptAt || entries[b].generatedAt || 0); });
      while (keys.length > MAX_CACHE_ENTRIES) delete entries[keys.shift()];
      var serialized = JSON.stringify({version:2, entries:entries});
      while (serialized.length > MAX_CACHE_CHARS && keys.length) {
        delete entries[keys.shift()];
        serialized = JSON.stringify({version:2, entries:entries});
      }
      safeSet(CACHE_KEY, serialized);
      memoryCache = entries;
    }
    function cacheId(league, kind, date) { return kind + '|' + league.espn_path + (date ? '|' + date : ''); }
    function coversWindow(coverage, start, end) {
      if (!coverage || !coverage.complete || !validDate(coverage.start) || !validDate(coverage.end) || coverage.start > start || coverage.end < end || !Array.isArray(coverage.dates)) return false;
      for (var day = start; day <= end; day = addDays(day, 1)) if (coverage.dates.indexOf(day) < 0) return false;
      return true;
    }
    function parseStatus(status) {
      if (!status || typeof status !== 'object') return undefined;
      var out = {};
      ['period','displayClock','displayPeriod','periodPrefix'].forEach(function (k) { if (status[k] != null && ['string','number'].indexOf(typeof status[k]) >= 0) out[k] = status[k]; });
      var type = status.type;
      if (type && typeof type === 'object') {
        var t = {};
        ['name','shortDetail','detail','description','state'].forEach(function (k) { var v = cleanText(type[k], 100); if (v) t[k] = v; });
        if (typeof type.completed === 'boolean') t.completed = type.completed;
        if (Object.keys(t).length) out.type = t;
      }
      return Object.keys(out).length ? out : undefined;
    }
    function projectTeam(team) {
      if (!team || typeof team !== 'object') return undefined;
      var out = {};
      if (team.id != null && /^[A-Za-z0-9._-]{1,80}$/.test(String(team.id))) out.id = String(team.id);
      ['abbreviation','shortDisplayName','displayName','shortName','name'].forEach(function (k) { var v = cleanText(team[k], 100); if (v) out[k] = v; });
      return Object.keys(out).length ? out : undefined;
    }
    function projectCompetitor(item) {
      if (!item || typeof item !== 'object') return null;
      var out = {};
      if (item.id != null && /^[A-Za-z0-9._-]{1,80}$/.test(String(item.id))) out.id = String(item.id);
      if (['home','away'].indexOf(item.homeAway) >= 0) out.homeAway = item.homeAway;
      if (typeof item.winner === 'boolean') out.winner = item.winner;
      ['score','displayClock','order'].forEach(function (k) { if (item[k] != null && ['string','number'].indexOf(typeof item[k]) >= 0) out[k] = typeof item[k] === 'string' ? cleanText(item[k], 60) : item[k]; });
      var team = projectTeam(item.team), athlete = projectTeam(item.athlete);
      if (team) out.team = team;
      if (athlete) out.athlete = athlete;
      return Object.keys(out).length ? out : null;
    }
    function projectCompetition(comp, event) {
      if (!comp || typeof comp !== 'object') return null;
      var out = {};
      if (comp.id != null && /^[A-Za-z0-9._-]{1,80}$/.test(String(comp.id))) out.id = String(comp.id);
      ['date','name','shortName','session'].forEach(function (k) { var v = cleanText(comp[k], 200); if (v) out[k] = v; });
      if (comp.type && typeof comp.type === 'object') {
        var competitionType = {};
        ['abbreviation','name','shortName'].forEach(function (k) { var v = cleanText(comp.type[k], 80); if (v) competitionType[k] = v; });
        if (Object.keys(competitionType).length) out.type = competitionType;
      }
      if (!out.date) { var date = cleanText(event && event.date, 40); if (date) out.date = date; }
      if (!out.name) { var name = cleanText(event && event.name, 200); if (name) out.name = name; }
      var status = parseStatus(comp.status || (event && event.status));
      if (status) out.status = status;
      var competitors = [];
      if (Array.isArray(comp.competitors)) comp.competitors.slice(0, 200).forEach(function (person) { var projected = projectCompetitor(person); if (projected) competitors.push(projected); });
      out.competitors = competitors;
      if (Array.isArray(comp.links)) out.links = comp.links.slice(0, 20).map(function (link) { return {href:safeURL(link && link.href), text:cleanText(link && link.text, 80)}; }).filter(function (link) { return !!link.href; });
      if (Array.isArray(comp.broadcasts)) out.broadcasts = comp.broadcasts.slice(0, 20).map(function (row) {
        return {market:cleanText(row && row.market, 60), names:Array.isArray(row && row.names) ? row.names.slice(0, 12).map(function (x) { return cleanText(x, 80); }).filter(Boolean) : []};
      }).filter(function (row) { return !!row.market && row.names.length; });
      return out;
    }
    function projectScoreboard(payload) {
      if (!payload || typeof payload !== 'object' || !Array.isArray(payload.events) || payload.events.length > 2000) throw new Error('Invalid scoreboard payload');
      var partial = false, output = [], count = 0;
      payload.events.forEach(function (event) {
        if (!event || typeof event !== 'object' || !Array.isArray(event.competitions)) { partial = true; return; }
        var comps = [];
        event.competitions.slice(0, 200).forEach(function (comp) {
          var projected = projectCompetition(comp, event);
          if (!projected) partial = true;
          else { comps.push(projected); count++; }
        });
        if (event.competitions.length > 200) partial = true;
        if (!comps.length) { partial = true; return; }
        var row = {competitions:comps};
        if (event.id != null && /^[A-Za-z0-9._-]{1,80}$/.test(String(event.id))) row.id = String(event.id);
        ['date','name','shortName','session'].forEach(function (k) { var v = cleanText(event[k], 200); if (v) row[k] = v; });
        var status = parseStatus(event.status); if (status) row.status = status;
        if (Array.isArray(event.links)) row.links = event.links.slice(0, 20).map(function (link) { return {href:safeURL(link && link.href),text:cleanText(link && link.text, 80)}; }).filter(function (link) { return !!link.href; });
        output.push(row);
      });
      if (count > MAX_COMPETITIONS) throw new Error('Scoreboard exceeds the competition limit');
      if (payload.events.length && !output.length) throw new Error('Scoreboard has no valid competitions');
      return {payload:{events:output}, partial:partial};
    }
    function stableCompetitionId(event, competition, index) {
      if (competition && competition.id) return String(competition.id);
      var eventKey = event && event.id ? String(event.id) : [event && event.date || competition && competition.date || '', event && event.name || competition && competition.name || ''].join('|');
      return eventKey + ':competition:' + (competition && (competition.name || competition.shortName) || index) + ':' + index;
    }
    function dedupeScoreboards(scoreboards) {
      var seen = Object.create(null), groups = Object.create(null), result = [];
      (scoreboards || []).forEach(function (payload) {
        (payload && payload.events || []).forEach(function (event) {
          var eventKey = event.id || [event.date || '', event.name || event.shortName || ''].filter(Boolean).join('|');
          if (!eventKey) eventKey = 'event-' + result.length;
          var group = groups[eventKey];
          if (!group) {
            group = {id:event.id, date:event.date, name:event.name, shortName:event.shortName, session:event.session, status:event.status, links:event.links || [], competitions:[]};
            groups[eventKey] = group; result.push(group);
          } else if (Array.isArray(event.links)) {
            group.links = (group.links || []).concat(event.links);
          }
          (event.competitions || []).forEach(function (comp, index) {
            var id = stableCompetitionId(event, comp, index);
            if (seen[id]) return;
            seen[id] = true; group.competitions.push(comp);
          });
        });
      });
      return {events:result.filter(function (event) { return event.competitions.length > 0; })};
    }
    function validateStandings(kind, payload) {
      if (!payload || typeof payload !== 'object') return false;
      if (kind !== 'standings') return Array.isArray(payload.events);
      return Array.isArray(payload.rankings) || Array.isArray(payload.children) || !!(payload.standings && Array.isArray(payload.standings.entries));
    }
    function projectPayload(kind, payload) {
      if (kind === 'scores' || kind === 'schedule') return projectScoreboard(payload);
      if (!validateStandings(kind, payload)) throw new Error('Invalid standings payload');
      var partial = false;
      function projectTeamRow(team) {
        if (!team || typeof team !== 'object') return {};
        var row = {};
        if (team.id != null && /^\d{1,20}$/.test(String(team.id))) row.id = String(team.id);
        ['location','name','abbreviation','nickname','shortDisplayName','displayName'].forEach(function (field) { var value = cleanText(team[field], 100); if (value) row[field] = value; });
        return row;
      }
      function projectStats(stats) {
        if (!Array.isArray(stats)) { partial = true; return []; }
        return stats.slice(0, 100).filter(function (stat) { if (!stat || typeof stat !== 'object') { partial = true; return false; } return true; }).map(function (stat) {
          var out = {};
          ['name','abbreviation','displayValue'].forEach(function (field) { var value = cleanText(stat[field], 80); if (value) out[field] = value; });
          if (typeof stat.value === 'number' && Number.isFinite(stat.value)) out.value = stat.value;
          return out;
        });
      }
      function projectGroup(group, depth) {
        if (!group || typeof group !== 'object' || depth > 6) { partial = true; return null; }
        var out = {}, name = cleanText(group.name, 120), abbreviation = cleanText(group.abbreviation, 40);
        if (name) out.name = name; if (abbreviation) out.abbreviation = abbreviation;
        if (Array.isArray(group.children)) out.children = group.children.slice(0, 100).map(function (child) { return projectGroup(child, depth + 1); }).filter(Boolean);
        if (group.standings && typeof group.standings === 'object') {
          var entries = group.standings.entries;
          if (Array.isArray(entries)) out.standings = {entries:entries.slice(0, 500).filter(function (entry) { if (!entry || typeof entry !== 'object') { partial = true; return false; } return true; }).map(function (entry) {
            return {team:projectTeamRow(entry.team), stats:projectStats(entry.stats)};
          })};
          else partial = true;
        }
        return out;
      }
      if (Array.isArray(payload.rankings)) {
        var rankings = payload.rankings.slice(0, 100).filter(function (row) { if (!row || typeof row !== 'object') { partial = true; return false; } return true; }).map(function (row) {
          var out = {}, name = cleanText(row.name, 120), shortName = cleanText(row.shortName, 80), type = cleanText(row.type, 40);
          if (name) out.name = name; if (shortName) out.shortName = shortName; if (type) out.type = type;
          if (Array.isArray(row.ranks)) out.ranks = row.ranks.slice(0, 500).filter(function (rank) { if (!rank || typeof rank !== 'object') { partial = true; return false; } return true; }).map(function (rank) {
            var outRank = {};
            ['current','previous'].forEach(function (key) { if (typeof rank[key] === 'number' && Number.isFinite(rank[key])) outRank[key] = rank[key]; });
            var record = cleanText(rank.recordSummary, 80); if (record) outRank.recordSummary = record;
            outRank.team = projectTeamRow(rank.team);
            return outRank;
          });
          return out;
        });
        return {payload:{rankings:rankings}, partial:partial};
      }
      var projected = {};
      var topName = cleanText(payload.name, 120), topAbbr = cleanText(payload.abbreviation, 40);
      if (topName) projected.name = topName; if (topAbbr) projected.abbreviation = topAbbr;
      if (Array.isArray(payload.children)) projected.children = payload.children.slice(0, 100).map(function (group) { return projectGroup(group, 0); }).filter(Boolean);
      if (payload.standings && typeof payload.standings === 'object') {
        var flat = projectGroup({standings:payload.standings}, 0);
        if (flat && flat.standings) projected.standings = flat.standings;
      }
      return {payload:projected, partial:partial};
    }
    function sourceEntry(row, source) {
      if (!row || !validateStandings('scores', row.payload) && !validateStandings('standings', row.payload)) return null;
      var kind = validateStandings('scores', row.payload) ? 'scores' : 'standings';
      var projected;
      try { projected = projectPayload(kind, row.payload); } catch (_) { return null; }
      if (!Number.isFinite(Date.parse(row.generatedAt || '')) || !Number.isFinite(Date.parse(row.lastAttemptAt || ''))) return null;
      var result = {payload:projected.payload, status:['ok','stale','unavailable'].indexOf(row.status) >= 0 ? row.status : 'ok',
        generatedAt:row.generatedAt, lastAttemptAt:row.lastAttemptAt, source:source,
        partial:!!row.partial || projected.partial};
      if (row.retrievedAt && Number.isFinite(Date.parse(row.retrievedAt))) result.retrievedAt = row.retrievedAt;
      if (row.coverage && typeof row.coverage === 'object') {
        var start = validDate(row.coverage.start) ? row.coverage.start : null;
        var end = validDate(row.coverage.end) ? row.coverage.end : null;
        if (start && end) result.coverage = {start:start,end:end,dates:Array.isArray(row.coverage.dates) ? row.coverage.dates.filter(validDate).slice(0, 32) : [],complete:row.coverage.complete === true};
      }
      if (result.partial && result.status === 'ok') result.status = 'stale';
      return result;
    }
    function publishedSnapshot() {
      if (snapshotData) return Promise.resolve(snapshotData);
      if (snapshotPromise) return snapshotPromise;
      snapshotPromise = jsonRequest(SNAPSHOT_URL).then(function (snapshot) {
        if (!snapshot || !snapshot.entries || typeof snapshot.entries !== 'object') throw new Error('Invalid published sports snapshot');
        snapshotData = snapshot;
        return snapshotData;
      }).catch(function () { snapshotPromise = null; return null; });
      return snapshotPromise;
    }
    function cacheCandidate(id, kind) {
      var entries = memoryCache;
      var row = entries[id];
      if (!row) {
        entries = cacheStore();
        memoryCache = entries;
        row = entries[id];
      }
      if (!row || !validateStandings(kind, row.payload)) return null;
      var stamp = Date.parse(row.generatedAt || ''), age = clockMs() - stamp;
      if (!Number.isFinite(stamp) || age < 0 || age > 7 * 24 * 60 * 60 * 1000) { delete entries[id]; delete memoryCache[id]; return null; }
      var candidate = sourceEntry(row, 'cache');
      if (!candidate) { delete entries[id]; delete memoryCache[id]; return null; }
      var ttl = kind === 'scores' ? 60000 : kind === 'standings' ? 300000 : 900000;
      if (age >= ttl && candidate.status === 'ok') candidate.status = 'stale';
      return candidate;
    }
    function snapshotCandidate(league, kind, date, window) {
      var snapshotRow = snapshotData && snapshotData.entries && snapshotData.entries[key(league, kind)];
      if (!snapshotRow || !validateStandings(kind, snapshotRow.payload)) return null;
      if (!Number.isFinite(Date.parse(snapshotRow.generatedAt || '')) || !Number.isFinite(Date.parse(snapshotRow.lastAttemptAt || ''))) return null;
      var row = {payload:snapshotRow.payload, status:['ok','stale','unavailable'].indexOf(snapshotRow.status) >= 0 ? snapshotRow.status : 'stale',
        generatedAt:snapshotRow.generatedAt, lastAttemptAt:snapshotRow.lastAttemptAt, source:'snapshot'};
      if (snapshotRow.retrievedAt && Number.isFinite(Date.parse(snapshotRow.retrievedAt))) row.retrievedAt = snapshotRow.retrievedAt;
      if (snapshotRow.coverage && typeof snapshotRow.coverage === 'object' && validDate(snapshotRow.coverage.start) && validDate(snapshotRow.coverage.end)) {
        row.coverage = {start:snapshotRow.coverage.start,end:snapshotRow.coverage.end,
          dates:Array.isArray(snapshotRow.coverage.dates) ? snapshotRow.coverage.dates.filter(validDate).slice(0, 32) : [],complete:snapshotRow.coverage.complete === true};
      }
      if (kind === 'scores') {
        var projected = projectScoreboard(row.payload);
        var filtered = [], foundDate = false;
        projected.payload.events.forEach(function (event) {
          var matching = Object.assign({}, event, {competitions:[]});
          event.competitions.forEach(function (comp) {
            if (eventLocalDay(comp.date || event.date) === date) { matching.competitions.push(comp); foundDate = true; }
          });
          if (matching.competitions.length) filtered.push(matching);
        });
        var publishedCoverage = row.coverage || null;
        var listedDate = !!(publishedCoverage && Array.isArray(publishedCoverage.dates) && publishedCoverage.dates.indexOf(date) >= 0);
        if (!foundDate && !listedDate) return null;
        row.payload = {events:filtered};
        row.partial = projected.partial;
        var inPublishedRange = !!(publishedCoverage && validDate(publishedCoverage.start) && validDate(publishedCoverage.end) && publishedCoverage.start <= date && publishedCoverage.end >= date);
        row.coverage = {start:date, end:date, dates:[date], complete:!!(publishedCoverage && publishedCoverage.complete && listedDate && inPublishedRange), partial:!publishedCoverage || !publishedCoverage.complete || !listedDate || !inPublishedRange};
        if (row.coverage.partial) row.partial = true;
      } else if (kind === 'schedule') {
        var normalized = projectScoreboard(row.payload);
        var start = window.start, end = window.end;
        var eventsWithin = [], datesWithEvents = Object.create(null);
        normalized.payload.events.forEach(function (event) {
          var matching = Object.assign({}, event, {competitions:[]});
          event.competitions.forEach(function (comp) {
            var day = eventLocalDay(comp.date || event.date);
            if (validDate(day) && day >= start && day <= end) { matching.competitions.push(comp); datesWithEvents[day] = true; }
          });
          if (matching.competitions.length) eventsWithin.push(matching);
        });
        row.payload = {events:eventsWithin};
        var publishedCoverage = row.coverage || null;
        var coveredDates = publishedCoverage && Array.isArray(publishedCoverage.dates) ? publishedCoverage.dates.filter(validDate) : [];
        var expectedDates = Array.from({length:8}, function (_, i) { return addDays(start, i); });
        var complete = coversWindow(publishedCoverage, start, end) && expectedDates.every(function (day) { return coveredDates.indexOf(day) >= 0; });
        row.partial = normalized.partial || !complete;
        row.coverage = {start:start, end:end, dates:complete ? expectedDates : Object.keys(datesWithEvents).sort(), complete:complete, partial:!complete};
      } else {
        var standings = projectPayload('standings', row.payload);
        row.payload = standings.payload;
        row.partial = standings.partial;
      }
      var ttl = kind === 'standings' ? 300000 : kind === 'schedule' ? 900000 : 60000;
      var age = clockMs() - Date.parse(row.generatedAt || '');
      if (row.partial && row.status === 'ok') row.status = 'stale';
      if (!Number.isFinite(age) || age < 0 || age >= ttl) row.status = 'stale';
      return row;
    }
    async function saved(leagueInput, kind, options) {
      var cfg = currentConfig || await config();
      var league = resolveLeague(leagueInput);
      if (['scores','schedule','standings'].indexOf(kind) < 0) throw new Error('Unsupported sports data kind');
      var opts = options || {};
      var date = validDate(opts.date) ? opts.date : localDate(now());
      var window = kind === 'schedule' ? {start:opts.date && validDate(opts.date) ? opts.date : localDate(now()), end:addDays(opts.date && validDate(opts.date) ? opts.date : localDate(now()), 7)} : null;
      var id = cacheId(league, kind, kind === 'scores' ? date : kind === 'schedule' ? window.start + '..' + window.end : '');
      var cached = cacheCandidate(id, kind);
      var ttl = kind === 'scores' ? 60000 : kind === 'standings' ? 300000 : 900000;
      if (cached && cached.status === 'ok' && !cached.partial && cached.generatedAt && clockMs() - Date.parse(cached.generatedAt) >= 0 && clockMs() - Date.parse(cached.generatedAt) < ttl && (kind !== 'schedule' || coversWindow(cached.coverage, window.start, window.end))) return cached;
      await publishedSnapshot();
      var published = snapshotCandidate(league, kind, date, window);
      if (!cached) return published;
      if (!published) return cached;
      return Date.parse(published.generatedAt || 0) > Date.parse(cached.generatedAt || 0) ? published : cached;
    }
    function makeLiveURL(league, kind, date) {
      var old = key(league, kind);
      var url = old.replace(/^https:\/\/site\.api\.espn\.com\//, 'https://site.web.api.espn.com/');
      if (url.indexOf('https://site.web.api.espn.com/apis/') !== 0) throw new Error('Invalid ESPN URL');
      if (kind === 'scores' || kind === 'schedule') {
        var query = ['dates=' + dateParam(date)];
        if (league.espn_path === 'football/college-football') query.push('groups=80', 'limit=100');
        else if (league.espn_path === 'basketball/mens-college-basketball') query.push('groups=50', 'limit=365');
        else query.push('limit=100');
        query.push('region=us', 'lang=en', 'contentorigin=espn');
        url += '?' + query.join('&');
      }
      else url += '?region=us&lang=en&contentorigin=espn';
      return url;
    }
    function shouldContinue(options) {
      if (!options) return true;
      if (options.signal && options.signal.aborted) return false;
      if (typeof options.shouldContinue === 'function') {
        try { return options.shouldContinue() !== false; } catch (_) { return false; }
      }
      return true;
    }
    function acquire(deadline, options) {
      if (!shouldContinue(options)) return Promise.reject(new Error('Sports request cancelled'));
      if (activeRequests < MAX_ACTIVE) { activeRequests++; return Promise.resolve(); }
      return new Promise(function (resolve, reject) {
        var waiter = {resolve:resolve, reject:reject, timer:null, options:options};
        var remaining = deadline - Date.now();
        if (remaining <= 0) { reject(new Error('Sports request budget exceeded')); return; }
        waiter.timer = timers.setTimeout(function () {
          var at = waiters.indexOf(waiter); if (at >= 0) waiters.splice(at, 1);
          reject(new Error('Sports request budget exceeded'));
        }, remaining);
        waiters.push(waiter);
      });
    }
    function release() {
      while (waiters.length) {
        var next = waiters.shift();
        if (!next || !next.resolve) continue;
        timers.clearTimeout(next.timer);
        if (!shouldContinue(next.options)) { next.reject(new Error('Sports request cancelled')); continue; }
        next.resolve();
        return;
      }
      activeRequests = Math.max(0, activeRequests - 1);
    }
    async function limitedJSON(url, deadline, options) {
      await acquire(deadline, options);
      try {
        if (!shouldContinue(options)) throw new Error('Sports request cancelled');
        if (Date.now() >= deadline) throw new Error('Sports request budget exceeded');
        return await requestURL(url, Math.min(REQUEST_TIMEOUT, deadline - Date.now()));
      } finally { release(); }
    }
    function freshness(entry, kind) {
      var ttl = kind === 'scores' ? 60000 : kind === 'standings' ? 300000 : 900000;
      var age = entry && entry.generatedAt ? clockMs() - Date.parse(entry.generatedAt) : NaN;
      return !!(entry && entry.status === 'ok' && !entry.partial && Number.isFinite(age) && age >= 0 && age < ttl);
    }
    function createEntry(projected, source, stamp, coverage) {
      return {payload:projected.payload, status:projected.partial ? 'stale' : 'ok', generatedAt:stamp, lastAttemptAt:stamp, retrievedAt:stamp, source:source, partial:!!projected.partial, coverage:coverage};
    }
    function staleFallback(entry, id, attemptAt) {
      if (!entry || !entry.payload) return null;
      entry.status = 'stale';
      entry.lastAttemptAt = attemptAt;
      writeCache(id, entry);
      return entry;
    }
    async function live(league, kind, options, id) {
      var attemptAt = isoNow();
      var nowDate = options && validDate(options.date) ? options.date : localDate(now());
      var stale = null, fallbackPromise = null;
      if (kind === 'schedule') {
        stale = await saved(league, kind, options);
        if (!shouldContinue(options) && stale) return stale;
        if (!options.force && freshness(stale, kind) && coversWindow(stale.coverage, nowDate, addDays(nowDate, 7))) return stale;
      } else {
        stale = cacheCandidate(id, kind);
        if (!options.force && freshness(stale, kind)) return stale;
        fallbackPromise = saved(league, kind, options).catch(function () { return null; });
        if (!shouldContinue(options) && stale) return stale;
      }
      var deadline = Date.now() + (kind === 'schedule' ? SCHEDULE_BUDGET : REQUEST_TIMEOUT);
      var good = [], failed = [], partial = false, retrieved = null;
      if (kind === 'scores' || kind === 'schedule') {
        var days = kind === 'scores' ? [nowDate] : Array.from({length:8}, function (_, i) { return addDays(nowDate, i); });
        await Promise.all(days.map(async function (day) {
          try {
            var raw = await limitedJSON(makeLiveURL(league, kind, day), deadline, options);
            var projected = projectScoreboard(raw);
            good.push({date:day, payload:projected.payload});
            if (projected.partial) partial = true;
            retrieved = isoNow();
          } catch (_) { failed.push(day); }
        }));
        var payload = dedupeScoreboards(good.map(function (item) { return item.payload; }));
        var coverage = {start:days[0], end:days[days.length - 1], dates:good.map(function (x) { return x.date; }).sort(), complete:failed.length === 0, partial:partial || failed.length > 0};
        var projectedCombined = projectScoreboard({events:payload.events});
        partial = partial || projectedCombined.partial || failed.length > 0;
        var entry = createEntry({payload:projectedCombined.payload, partial:partial}, 'live', retrieved || attemptAt, coverage);
        entry.lastAttemptAt = attemptAt;
        if (!retrieved) {
          if (fallbackPromise) stale = await fallbackPromise || stale;
          if (stale) return staleFallback(stale, id, attemptAt);
          return {payload:null,status:'unavailable',generatedAt:null,lastAttemptAt:attemptAt,source:'snapshot',coverage:coverage};
        }
        if (kind === 'scores' && partial && fallbackPromise) stale = await fallbackPromise || stale;
        if (failed.length && stale && stale.payload) {
          return staleFallback(stale, id, attemptAt);
        }
        if (kind === 'scores' && entry.partial && stale && stale.payload) return staleFallback(stale, id, attemptAt);
        if (kind === 'scores') entry.coverage = {start:nowDate,end:nowDate,dates:[nowDate],complete:failed.length === 0,partial:partial};
        writeCache(id, entry);
        return entry;
      }
      try {
        var rawStandings = await limitedJSON(makeLiveURL(league, kind), deadline, options);
        var projectedStandings = projectPayload(kind, rawStandings);
        var entryStandings = createEntry(projectedStandings, 'live', isoNow());
        entryStandings.lastAttemptAt = attemptAt;
        if (entryStandings.partial && fallbackPromise) stale = await fallbackPromise || stale;
        if (entryStandings.partial && stale && stale.payload) return staleFallback(stale, id, attemptAt);
        writeCache(id, entryStandings);
        return entryStandings;
      } catch (_) {
        if (fallbackPromise) stale = await fallbackPromise || stale;
        if (stale) return staleFallback(stale, id, attemptAt);
        return {payload:null,status:'unavailable',generatedAt:null,lastAttemptAt:attemptAt,source:'snapshot'};
      }
    }
    async function load(leagueInput, kind, options) {
      await config();
      var league = resolveLeague(leagueInput);
      if (kind === 'standings' && !league.standings) throw new Error('Standings are unavailable for this league');
      if (['scores','schedule','standings'].indexOf(kind) < 0) throw new Error('Unsupported sports data kind');
      var opts = Object.assign({}, options || {});
      if (opts.date && !validDate(opts.date)) throw new Error('Invalid sports date');
      if (kind !== 'scores' && kind !== 'schedule') delete opts.date;
      if (kind === 'schedule' && !opts.date) opts.date = localDate(now());
      var date = opts.date || localDate(now());
      var id = cacheId(league, kind, kind === 'scores' ? date : kind === 'schedule' ? date + '..' + addDays(date, 7) : '');
      var previous = inFlight[id], cancellable = !!(opts.signal || typeof opts.shouldContinue === 'function');
      if (previous && !cancellable && !previous.cancellable) return previous.promise;
      if (previous && cancellable && previous.cancellable && opts.signal === previous.options.signal && opts.shouldContinue === previous.options.shouldContinue) return previous.promise;
      var record = {cancellable:cancellable, options:opts, promise:null};
      var operation = live(league, kind, opts, id).finally(function () { if (inFlight[id] === record) delete inFlight[id]; });
      record.promise = operation;
      inFlight[id] = record;
      return operation;
    }
    function allCompetitions(payload) {
      var seen = Object.create(null), result = [];
      (payload && payload.events || []).forEach(function (event, eventIndex) {
        (event.competitions || []).forEach(function (comp, compIndex) {
          var id = stableCompetitionId(event, comp, compIndex);
          if (seen[id]) return;
          seen[id] = true;
          result.push({event:event, competition:comp, id:id, eventIndex:eventIndex, compIndex:compIndex});
        });
      });
      return result;
    }
    function teamMatches(league, person, configValue, opts) {
      var idMap = configValue.favorite_team_ids || {};
      var ids = idMap[league.name] || idMap[league.espn_path] || [];
      if (!Array.isArray(ids)) ids = ids == null ? [] : [ids];
      var hasLeagueIds = Object.prototype.hasOwnProperty.call(idMap, league.name) || Object.prototype.hasOwnProperty.call(idMap, league.espn_path);
      if (person.id && ids.some(function (x) { return String(x) === String(person.id); })) return true;
      if (person.team && person.team.id && ids.some(function (x) { return String(x) === String(person.team.id); })) return true;
      if (hasLeagueIds) return false;
      var aliases = opts.favoriteAliases || opts.priorityTeams || configValue.priority_teams;
      if (env.favoriteTeam) return !!env.favoriteTeam(person.team || person.athlete, aliases);
      if (global.ToolUI && global.ToolUI.favoriteTeam) return !!global.ToolUI.favoriteTeam(person.team || person.athlete, aliases);
      return false;
    }
    function events(leagueInput, entry, options) {
      if (!currentConfig) throw new Error('Call SportsData.config() before SportsData.events()');
      var league = resolveLeague(leagueInput), configValue = currentConfig, opts = options || {};
      var payload = entry && entry.payload;
      if (!validateStandings('scores', payload)) return [];
      var startDay = validDate(opts.date) ? opts.date : validDate(opts.start) ? opts.start : entry.coverage && validDate(entry.coverage.start) ? entry.coverage.start : '';
      var endDay = validDate(opts.date) ? opts.date : validDate(opts.end) ? opts.end : entry.coverage && validDate(entry.coverage.end) ? entry.coverage.end : '';
      return allCompetitions(payload).filter(function (row) {
        if (!startDay && !endDay) return true;
        var day = eventLocalDay(row.competition.date || row.event.date);
        return validDate(day) && (!startDay || day >= startDay) && (!endDay || day <= endDay);
      }).map(function (row) {
        var event = row.event, comp = row.competition, status = comp.status || event.status || {}, type = status.type || {};
        var participants = (comp.competitors || []).map(function (person) {
          var team = person.team || person.athlete || {};
          return {id:person.id || team.id || '', name:team.displayName || team.shortDisplayName || team.name || team.shortName || '', abbr:team.abbreviation || '', homeAway:person.homeAway || '', score:person.score == null ? '' : String(person.score), position:person.order == null ? null : person.order, displayClock:person.displayClock || '', winner:person.winner === true};
        });
        var start = comp.date || event.date || '';
        var url = '';
        (comp.links || []).concat(event.links || []).some(function (link) { var candidate = safeURL(link && link.href); if (candidate) { url = candidate; return true; } return false; });
        var favorite = participants.some(function (person, index) { return teamMatches(league, comp.competitors[index] || {}, configValue, opts); });
        return {id:league.espn_path + ':' + row.id, league:league.name,
          name:comp.name || event.name || comp.shortName || event.shortName || league.name,
          date:start, state:type.state || (type.completed ? 'post' : ''),
          status:type.shortDetail || type.detail || type.description || type.name || '',
          clock:status.displayClock || '', period:status.period || '', session:league.scores_type === 'racing' ? (comp.session || comp.type && (comp.type.abbreviation || comp.type.shortName || comp.type.name) || event.session || '') : '',
          url:url, broadcasts:Array.isArray(comp.broadcasts) ? comp.broadcasts.map(function (b) { return {market:b.market || '', names:Array.isArray(b.names) ? b.names.slice() : []}; }) : [],
          participants:participants, favorite:favorite};
      });
    }
    function configure(raw) {
      currentConfig = sanitizeConfig(raw);
      configPromise = Promise.resolve(currentConfig);
      return clone(currentConfig);
    }
    if (env.config) configure(env.config);
    return {config:config, key:key, saved:saved, load:load, events:events, configure:configure,
      _constants:{cacheKey:CACHE_KEY,requestTimeout:REQUEST_TIMEOUT,maxActive:MAX_ACTIVE}};
  }
  return createSportsData;
}));
