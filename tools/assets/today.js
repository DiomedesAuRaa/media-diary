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
      while (stories.length < 3 && queues.some(function (queue) { return queue.length > offset; })) {
        queues.forEach(function (queue) {
          if (stories.length >= 3) return;
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

  var sportsRun = 0, sportsConfig = null, sportsEntries = [];
  function favoriteLeagues(config) {
    var map = config.favorite_team_ids || {};
    var names = Object.keys(map).filter(function (name) { return Array.isArray(map[name]) && map[name].length; });
    if (!names.length) names = ['NFL','NBA','MLB','NHL','NCAAFB','NCAAB'];
    return (config.leagues || []).filter(function (league) { return league.enabled !== false && names.indexOf(league.name) >= 0; });
  }
  function eventData() {
    var byId = Object.create(null);
    sportsEntries.forEach(function (row) {
      if (!row.entry || !row.entry.payload) return;
      try {
        SportsData.events(row.league, row.entry).forEach(function (event) {
          if (!event.favorite) return;
          var candidate = Object.assign({leagueName:row.league.name, entry:row.entry, context:row.context}, event);
          var previous = byId[event.id];
          if (!previous || (candidate.context === 'today' && previous.context !== 'today') || (previous.entry.source !== 'live' && candidate.entry.source === 'live')) byId[event.id] = candidate;
        });
      } catch (_) {}
    });
    return Object.keys(byId).map(function (id) { return byId[id]; });
  }
  function renderSports() {
    var now = Date.now(), events = eventData().filter(function (event) {
      var date = safeTime(event.date); return date && !/cancel|postpon|delay/i.test(event.status || '');
    });
    var live = events.filter(function (event) { return event.state === 'in' || event.state === 'live'; });
    var upcoming = events.filter(function (event) { var date = new Date(event.date).getTime(); return (event.state === 'pre' || event.state === 'scheduled' || !event.state) && date >= now; });
    var recent = events.filter(function (event) { var date = new Date(event.date).getTime(); return (event.state === 'post' || event.state === 'final' || event.state === 'completed') && date <= now && now - date < 10 * 86400000; });
    live.sort(function (a,b) { return new Date(a.date)-new Date(b.date); });
    upcoming.sort(function (a,b) { return new Date(a.date)-new Date(b.date); });
    recent.sort(function (a,b) { return new Date(b.date)-new Date(a.date); });
    function render(list, id, kind) {
      var target = $(id); target.replaceChildren();
      list.slice(0, kind === 'upcoming' ? 1 : 2).forEach(function (event) {
        var li = document.createElement('li'), line = document.createElement('div'), meta = document.createElement('span');
        var participants = event.participants || [];
        var names = participants.map(function (p) { return p.name || p.abbr || 'Team'; });
        line.className = 'game-score';
        if (event.state === 'in' || event.state === 'live' || event.state === 'post' || event.state === 'final' || event.state === 'completed') {
          var status = {status:{type:{name:event.state === 'post' || event.state === 'final' || event.state === 'completed' ? 'STATUS_FINAL' : 'STATUS_IN_PROGRESS', state:event.state}}};
          line.textContent = names.join(' ') + ' · ' + participants.map(function (p) { return SportsScoreDisplay.score(p.score, status); }).join('–');
        } else line.textContent = names.join(' · ') || event.name;
        meta.className = 'game-label';
        var provenance = event.context === 'today' && event.entry && event.entry.source === 'live' ? 'Retrieved ' + fmtStamp(event.entry.retrievedAt || event.entry.generatedAt) : (event.context === 'schedule' ? 'Saved schedule' : 'Saved score') + ' · ' + fmtStamp(event.entry && event.entry.generatedAt);
        meta.textContent = (event.state === 'in' || event.state === 'live' ? 'LIVE · ' : '') + fmtTime(event.date) + (event.status ? ' · ' + event.status : '') + ' · ' + provenance;
        li.append(line, meta); target.appendChild(li);
      });
      if (!list.length) { var empty = document.createElement('li'); empty.className = 'muted'; empty.textContent = 'No ' + kind + ' favorite-team games are listed.'; target.appendChild(empty); }
    }
    render(live.concat(upcoming).sort(function (a,b) { return new Date(a.date)-new Date(b.date); }), 'upcoming-games', 'upcoming');
    render(recent, 'recent-games', 'recent');
    var available = sportsEntries.filter(function (row) { return row.entry && row.entry.payload; });
    var stale = available.some(function (row) { return row.entry.status === 'stale' || row.entry.source === 'snapshot' || row.entry.source === 'cache'; });
    $('sports-meta').textContent = 'Local game times · saved schedule and today’s scores';
    var todayRows = sportsEntries.filter(function (row) { return row.context === 'today' && row.entry && row.entry.payload; });
    var todayLatest = todayRows.map(function (row) { return row.entry.retrievedAt || row.entry.generatedAt; }).filter(Boolean).sort().pop();
    var liveToday = todayRows.some(function (row) { return row.entry.source === 'live'; });
    $('sports-status').textContent = todayRows.length ? (liveToday ? 'Today’s scores retrieved ' : 'Today’s saved scores · last retrieved ') + fmtStamp(todayLatest) + (stale ? ' · future and recent games may use saved data' : '') : available.length ? 'Saved favorite-team schedule data.' : 'Favorite-team game feeds are unavailable.';
    $('sports-retry').hidden = available.length > 0;
  }
  async function loadSports() {
    var run = ++sportsRun;
    loading('sports-status','Loading favorite-team games…','sports-retry');
    try {
      sportsConfig = sportsConfig || await SportsData.config();
      if (run !== sportsRun) return;
      var leagues = favoriteLeagues(sportsConfig);
      if (!leagues.length) throw new Error('No favorite leagues are configured');
      sportsEntries = [];
      var now = new Date(), today = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
      var yesterdayDate = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
      var yesterday = yesterdayDate.getFullYear() + '-' + String(yesterdayDate.getMonth()+1).padStart(2,'0') + '-' + String(yesterdayDate.getDate()).padStart(2,'0');
      await Promise.all(leagues.map(async function (league) {
        async function addSaved(kind, date) {
          try {
            var entry = await SportsData.saved(league, kind, {date:date});
            if (run !== sportsRun) return;
            if (entry && entry.payload) { sportsEntries.push({league:league,entry:entry,context:kind === 'schedule' ? 'schedule' : 'recent'}); renderSports(); }
          } catch (_) {}
        }
        var savedTask = Promise.all([addSaved('schedule', today), addSaved('scores', yesterday)]);
        var liveTask = SportsData.load(league, 'scores', {date:today, shouldContinue:function () { return run === sportsRun; }}).then(function(entry) {
          if (run !== sportsRun) return;
          var index = sportsEntries.findIndex(function (row) { return row.league.name === league.name && row.context === 'today'; });
          if (index >= 0) sportsEntries[index].entry = entry; else sportsEntries.push({league:league,entry:entry,context:'today'});
          renderSports();
        }).catch(function() {
          if (run !== sportsRun) return;
          if (!sportsEntries.some(function (row) { return row.league.name === league.name; })) sportsEntries.push({league:league,entry:{status:'unavailable'}});
          renderSports();
        });
        await Promise.all([savedTask, liveTask]);
      }));
    } catch (_) {
      if (run === sportsRun) errorState('sports-status','Favorite-team games are unavailable right now.','sports-retry');
    }
  }
  $('sports-retry').addEventListener('click', loadSports); loadSports();
})();
