(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var dateEl = $('today-date');
  dateEl.textContent = new Intl.DateTimeFormat(undefined, {weekday:'long', month:'long', day:'numeric'}).format(new Date());
  var fmtTime = function (value) {
    var date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat(undefined, {dateStyle:'medium', timeStyle:'short'}).format(date);
  };
  var fmtStamp = function (value) { var stamp = fmtTime(value); return stamp || 'time unavailable'; };
  var safeTime = function (value) {
    if (typeof value !== 'string' || !value.trim()) return null;
    var d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  };
  function json(url) { return ToolUI.fetch(url).then(function (r) { if (!r.ok) throw new Error('unavailable'); return r.json(); }); }
  function errorState(id, message, retryId) { $(id).textContent = message; $(id).classList.add('error-line'); $(retryId).hidden = false; }
  function loading(id, text, retryId) { $(id).textContent = text; $(id).classList.remove('error-line'); $(retryId).hidden = true; }

  var defaultLocation = {lat:33.749, lon:-84.388, name:'Atlanta, Georgia'};
  var location = defaultLocation;
  try {
    var remembered = JSON.parse(ToolUI.storageGet('portfolio_weather_location'));
    if (remembered && Number.isFinite(remembered.lat) && Number.isFinite(remembered.lon) && Math.abs(remembered.lat) <= 90 && Math.abs(remembered.lon) <= 180 && typeof remembered.name === 'string') location = remembered;
  } catch (_) {}
  $('weather-location').textContent = location.name;
  var weatherRun = 0;
  function loadWeather() {
    var run = ++weatherRun;
    loading('weather-status', 'Loading current conditions…', 'weather-retry'); $('weather-meta').textContent = 'Open-Meteo · current snapshot';
    var url = 'https://api.open-meteo.com/v1/forecast?latitude=' + encodeURIComponent(location.lat) + '&longitude=' + encodeURIComponent(location.lon) + '&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto&forecast_days=1';
    json(url).then(function (data) {
      if (run !== weatherRun) return;
      var current = data.current, daily = data.daily;
      if (!current || typeof current.temperature_2m !== 'number' || !Number.isFinite(current.temperature_2m)) throw new Error('invalid');
      var codes = {0:'Clear',1:'Mostly clear',2:'Partly cloudy',3:'Overcast',45:'Fog',48:'Fog',51:'Drizzle',53:'Drizzle',55:'Drizzle',61:'Rain',63:'Rain',65:'Heavy rain',71:'Snow',73:'Snow',75:'Heavy snow',80:'Showers',81:'Showers',82:'Heavy showers',95:'Thunderstorms',96:'Thunderstorms',99:'Thunderstorms'};
      $('weather-now').textContent = Math.round(current.temperature_2m) + '°F';
      $('weather-condition').textContent = codes[current.weather_code] || 'Conditions available';
      $('weather-wind').textContent = typeof current.wind_speed_10m === 'number' && Number.isFinite(current.wind_speed_10m) ? Math.round(current.wind_speed_10m) + ' mph' : '—';
      var low = daily && Array.isArray(daily.temperature_2m_min) && typeof daily.temperature_2m_min[0] === 'number' ? daily.temperature_2m_min[0] : NaN;
      var high = daily && Array.isArray(daily.temperature_2m_max) && typeof daily.temperature_2m_max[0] === 'number' ? daily.temperature_2m_max[0] : NaN;
      $('weather-range').textContent = Number.isFinite(low) && Number.isFinite(high) ? Math.round(low) + '° / ' + Math.round(high) + '°' : '—';
      var observed = typeof current.time === 'string' ? current.time.replace('T', ' ') : '';
      $('weather-status').textContent = 'Updated ' + (observed || 'just now') + (data.timezone ? ' · ' + data.timezone + ' local time' : '');
    }).catch(function () { if (run === weatherRun) errorState('weather-status', 'Weather is unavailable right now.', 'weather-retry'); });
  }
  $('weather-retry').addEventListener('click', loadWeather); loadWeather();

  var newsRun = 0;
  function loadNews() {
    var run = ++newsRun; loading('news-status','Loading headlines…','news-retry'); $('news-list').replaceChildren();
    json('news-digest.json').then(function (data) {
      if (run !== newsRun) return;
      if (!data || !Array.isArray(data.feeds)) throw new Error('invalid');
      var entries = data.feeds.filter(function (feed) { return feed && feed.category === 'top' && (feed.status === 'ok' || feed.status === 'stale') && Array.isArray(feed.items); });
      var partial = data.feeds.some(function (feed) { return feed && feed.category === 'top' && feed.status === 'unavailable'; });
      var generated = safeTime(data.generatedAt);
      var stale = !generated || Date.now() - generated.getTime() > 2 * 60 * 60 * 1000 || data.feeds.some(function (feed) { return feed && feed.category === 'top' && feed.status === 'stale'; });
      var queues = entries.map(function (feed) {
        return feed.items.filter(function (item) { return item && typeof item.title === 'string' && ToolUI.httpURL(item.url); })
          .map(function (item) { return {title:item.title, url:ToolUI.httpURL(item.url), source:feed.name || 'News', date:item.date}; });
      });
      var stories = [], seen = Object.create(null), offset = 0;
      while (stories.length < 6 && queues.some(function (queue) { return queue.length > offset; })) {
        queues.forEach(function (queue) {
          if (stories.length >= 6) return;
          var story = queue[offset];
          if (!story) return;
          var key = story.url.toLowerCase();
          if (!seen[key]) { seen[key] = true; stories.push(story); }
        });
        offset++;
      }
      stories.forEach(function (story) {
        var li = document.createElement('li'), a = document.createElement('a'), meta = document.createElement('span');
        a.href = story.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = story.title;
        meta.className = 'story-meta'; meta.textContent = story.source + (story.date ? ' · ' + story.date : ''); li.append(a, meta); $('news-list').appendChild(li);
      });
      $('news-meta').textContent = (stale ? 'Saved snapshot may be stale · ' : 'Snapshot · ') + fmtStamp(data.generatedAt);
      var message = stories.length ? stories.length + ' headlines from the published top feed snapshot.' : 'No top headlines are available in this snapshot.';
      $('news-status').textContent = (partial ? 'Some top news feeds are unavailable; ' : '') + message;
    }).catch(function () { if (run === newsRun) errorState('news-status','Headlines are unavailable right now.','news-retry'); });
  }
  $('news-retry').addEventListener('click', loadNews); loadNews();

  var sportsRun = 0;
  function loadSports() {
    var run = ++sportsRun; loading('sports-status','Loading games…','sports-retry'); $('live-games').replaceChildren(); $('recent-games').replaceChildren(); $('upcoming-games').replaceChildren();
    Promise.all([json('sports-snapshot.json'), json('sports-config.json')]).then(function (result) {
      if (run !== sportsRun) return;
      var snapshot = result[0], config = result[1];
      if (!snapshot || snapshot.version !== 1 || !snapshot.entries || typeof snapshot.entries !== 'object' || !Array.isArray(config.priority_teams) || !Array.isArray(config.leagues)) throw new Error('invalid');
      var favoriteTokens = config.priority_teams.map(function (v) { return String(v).toLowerCase(); });
      var scoreBase = 'https://site.api.espn.com/apis/site/v2/sports/';
      var scoreUrls = config.leagues.filter(function (league) { return league && league.enabled === true && typeof league.espn_path === 'string'; })
        .map(function (league) { return scoreBase + league.espn_path + '/scoreboard'; });
      var now = Date.now(), live = [], recent = [], upcoming = [], stale = false, incomplete = scoreUrls.length === 0, stamp = null;
      scoreUrls.forEach(function (url) {
        var expected = snapshot.entries[url];
        if (!expected || !expected.payload || !Array.isArray(expected.payload.events)) incomplete = true;
      });
      Object.keys(snapshot.entries).forEach(function (key) {
        if (scoreUrls.indexOf(key) === -1) return;
        var entry = snapshot.entries[key];
        if (!entry || !entry.payload || !Array.isArray(entry.payload.events)) { incomplete = true; return; }
        var generated = safeTime(entry.generatedAt); if (generated && (!stamp || generated > stamp)) stamp = generated;
        var entryAge = safeTime(entry.generatedAt);
        if (entry.status !== 'ok' || !entryAge || now - entryAge.getTime() > 30 * 60 * 1000) stale = true;
        entry.payload.events.forEach(function (event) {
          var competition = event && event.competitions && event.competitions[0];
          if (!competition || !Array.isArray(competition.competitors) || !competition.status || !competition.status.type) return;
          var teams = competition.competitors;
          if (!teams.some(function (competitor) { return competitor && ToolUI.favoriteTeam(competitor.team, favoriteTokens); })) return;
          var date = safeTime(competition.date || event.date); if (!date) return;
          var state = competition.status.type.state;
          var type = competition.status.type;
          var typeName = String(type.name || '').toUpperCase();
          var statusText = [type.shortDetail, type.detail, type.description, competition.status.displayClock].filter(Boolean).join(' ');
          if (/CANCEL|POSTPON|DELAY/.test(typeName) || /\b(cancelled|canceled|postponed|delayed)\b/i.test(statusText)) return;
          var done = state === 'post' || type.completed === true || typeName === 'STATUS_FINAL';
          var isLive = state === 'in' || typeName === 'STATUS_IN_PROGRESS';
          var game = {date:date, teams:teams, competition:competition, status:competition.status.type.shortDetail || competition.status.type.detail || '', done:done, live:isLive};
          if (done && date.getTime() <= now && now - date.getTime() < 10 * 86400000) recent.push(game);
          else if (isLive) live.push(game);
          else if (!done && date.getTime() >= now && date.getTime() < now + 14 * 86400000) upcoming.push(game);
        });
      });
      function order(a,b) { return a.date - b.date; }
      recent.sort(function (a,b) { return b.date-a.date; }); live.sort(order); upcoming.sort(order);
      function render(list, id, kind) {
        var target = $(id);
        list.slice(0,3).forEach(function (game) {
          var li = document.createElement('li'), line = document.createElement('div'), meta = document.createElement('span');
          var names = game.teams.map(function (t) { var name = t && t.team && (t.team.shortDisplayName || t.team.displayName || t.team.abbreviation); return String(name || 'Team'); });
          line.className = 'game-score';
          if (game.done || game.live) {
            var scores = game.teams.map(function (t) { return t && t.score != null ? String(t.score) : '—'; }); line.textContent = names.join(' ') + ' · ' + scores.join('–');
          } else line.textContent = names.join(' · ');
          meta.className = 'game-label'; meta.textContent = (game.live ? 'LIVE · ' : '') + fmtTime(game.date) + (game.status ? ' · ' + game.status : '');
          li.append(line,meta); target.appendChild(li);
        });
        if (!list.length) { var li = document.createElement('li'); li.className = 'muted'; li.textContent = 'No ' + kind + ' favorite team games in this snapshot window.'; target.appendChild(li); }
      }
      render(live,'live-games','live'); render(recent,'recent-games','recent'); render(upcoming,'upcoming-games','upcoming');
      $('sports-meta').textContent = (stale ? 'Saved snapshot may be stale' : 'Snapshot') + (stamp ? ' · checked ' + fmtStamp(stamp.toISOString()) : '');
      $('sports-status').textContent = (incomplete ? 'Some schedule entries are unavailable; saved games are shown where available. ' : '') + 'Favorite team games from the published schedule snapshot.';
    }).catch(function () { if (run === sportsRun) errorState('sports-status','Games are unavailable right now.','sports-retry'); });
  }
  $('sports-retry').addEventListener('click', loadSports); loadSports();
})();
