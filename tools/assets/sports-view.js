(function () {
  'use strict';
  var body = document.body;
  var mode = body.dataset.sportsMode === 'schedule' ? 'schedule' : 'scores';
  var content = document.getElementById('sports-content');
  var selector = document.getElementById('sports-league');
  var dateInput = document.getElementById('sports-date');
  var pageLabel = document.getElementById('sports-page-label');
  var config = null, leagues = [], state = null, run = 0, entries = [], page = 0;
  var pageSize = 10, pollBusy = false;
  var today = localDate(new Date());

  function localDate(date) {
    var offset = date.getTimezoneOffset();
    return new Date(date.getTime() - offset * 60000).toISOString().slice(0, 10);
  }
  function text(tag, value, cls) { return ToolUI.text(tag, value == null ? '' : value, cls); }
  function safeDate(value) {
    if (typeof value !== 'string' || !value) return null;
    var date = new Date(value);
    return Number.isFinite(date.getTime()) ? date : null;
  }
  function displayDate(value, opts) {
    var date = safeDate(value);
    return date ? date.toLocaleString([], opts || {weekday:'short', month:'short', day:'numeric', hour:'numeric', minute:'2-digit', timeZoneName:'short'}) : 'Time unavailable';
  }
  function generatedLabel(entry) {
    var at = entry && (entry.retrievedAt || entry.generatedAt || entry.lastAttemptAt);
    if (!at) return 'time unavailable';
    var date = safeDate(at);
    return date ? date.toLocaleString([], {month:'short', day:'numeric', hour:'numeric', minute:'2-digit'}) : 'time unavailable';
  }
  function stateHash() {
    var params = new URLSearchParams();
    params.set('league', state.league);
    params.set('date', state.date);
    params.set('page', String(page + 1));
    return '#' + params.toString();
  }
  function routePage() {
    try { return Math.max(0, Math.min(100000, parseInt(new URLSearchParams(location.hash.slice(1)).get('page'), 10) - 1 || 0)); }
    catch (_) { return 0; }
  }
  function focusPager(direction) {
    var preferred = content.querySelector('[data-page-control="' + direction + '"]:not(:disabled)');
    var fallback = content.querySelector('[data-page-control]:not(:disabled)') || content.querySelector('[data-event-id]');
    if (preferred || fallback) (preferred || fallback).focus();
  }
  function updateModeLinks() {
    if (!state) return;
    var destinations = {scores:'sports-scores.html', schedule:'schedule.html', standings:'standings.html'};
    document.querySelectorAll('[data-sports-link]').forEach(function (link) {
      var destination = destinations[link.dataset.sportsLink];
      if (!destination) return;
      var selectedLeague = leagues.find(function(league) { return league.name === state.league; });
      if (link.dataset.sportsLink === 'standings' && selectedLeague && selectedLeague.standings === false) {
        link.removeAttribute('href'); link.setAttribute('aria-disabled', 'true');
        link.setAttribute('aria-label', 'Tables unavailable for ' + selectedLeague.name); return;
      }
      link.removeAttribute('aria-disabled'); link.removeAttribute('aria-label');
      var params = new URLSearchParams();
      params.set('league', state.league); params.set('date', state.date);
      link.href = destination + '#' + params.toString();
    });
  }
  function pushState() {
    updateModeLinks();
    var hash = stateHash();
    if (location.hash !== hash) history.pushState(null, '', hash);
  }
  function routeState() {
    var hash = location.hash.slice(1);
    if (hash === 'section-FAVORITES') return {league:'favorites', date:today};
    if (hash === 'all') return {league:'all', date:today};
    var legacy = /^section-(.+)$/.exec(hash);
    if (legacy) {
      var slug = legacy[1];
      var match = leagues.find(function (league) { return slug === String(league.name || '').replace(/[^a-z0-9]/gi, '_'); });
      if (match) return {league:match.name, date:today};
    }
    try {
      var params = new URLSearchParams(hash);
      var league = params.get('league');
      var date = params.get('date');
      if (league && (league === 'favorites' || league === 'all' || leagues.some(function (row) { return row.name === league; }))) {
        return {league:league, date:validLocalDate(date) ? date : today};
      }
    } catch (_) {}
    return {league:'favorites', date:today};
  }
  function validLocalDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    var parts = value.split('-').map(Number), date = new Date(parts[0], parts[1] - 1, parts[2]);
    return date.getFullYear() === parts[0] && date.getMonth() === parts[1] - 1 && date.getDate() === parts[2];
  }
  function favoriteLeagueNames() {
    var map = config.favorite_team_ids;
    if (map && typeof map === 'object' && !Array.isArray(map)) {
      var mapped = Object.keys(map).filter(function (name) { return Array.isArray(map[name]) && map[name].length; });
      if (mapped.length) return mapped;
    }
    var preferred = ['NFL','NBA','MLB','NHL','NCAAFB','NCAAB'];
    return preferred.filter(function (name) { return leagues.some(function (league) { return league.name === name; }); });
  }
  function targets() {
    if (state.league === 'all') return leagues.slice();
    if (state.league === 'favorites') {
      var names = favoriteLeagueNames();
      return leagues.filter(function (league) { return names.indexOf(league.name) >= 0; });
    }
    return leagues.filter(function (league) { return league.name === state.league; });
  }
  function buildSelector() {
    selector.replaceChildren(new Option('Favorite teams', 'favorites'), new Option('All leagues', 'all'));
    leagues.forEach(function (league) { selector.append(new Option(league.name, league.name)); });
    selector.value = state.league;
    if (dateInput) { dateInput.hidden = mode !== 'scores'; dateInput.value = state.date; }
    pageLabel.textContent = mode === 'schedule' ? 'Upcoming' : 'Scores';
    updateModeLinks();
  }
  function entryEvents(league, entry) {
    if (!entry || !entry.payload || !SportsData || typeof SportsData.events !== 'function') return [];
    try { return SportsData.events(league, entry, mode === 'scores' ? {date:state.date} : {}) || []; }
    catch (_) { return []; }
  }
  function selectedEvents() {
    var out = [];
    entries.forEach(function (row) {
      entryEvents(row.league, row.entry).forEach(function (event) {
        if (state.league === 'favorites' && !event.favorite) return;
        var date = safeDate(event.date);
        var endDate = new Date(state.date + 'T12:00:00'); endDate.setDate(endDate.getDate() + 8);
        if (mode === 'schedule' && (!date || date.getTime() < Date.now() || date.getTime() >= endDate.getTime())) return;
        out.push(Object.assign({leagueName:row.league.name, leagueColor:row.league.color, entry:row.entry}, event));
      });
    });
    out.sort(function (a, b) {
      var at = safeDate(a.date), bt = safeDate(b.date);
      return (at ? at.getTime() : 0) - (bt ? bt.getTime() : 0);
    });
    return out;
  }
  function scoreStatus(event) {
    var stateValue = String(event.state || '').toLowerCase();
    if (stateValue === 'scheduled') stateValue = 'pre';
    if (stateValue === 'live') stateValue = 'in';
    if (stateValue === 'final' || stateValue === 'completed') stateValue = 'post';
    var name = stateValue === 'pre' ? 'STATUS_SCHEDULED' : stateValue === 'post' ? 'STATUS_FINAL' : stateValue === 'in' ? 'STATUS_IN_PROGRESS' : '';
    return {status:{type:{name:name, state:stateValue, shortDetail:event.status || ''}}};
  }
  function renderEvent(event) {
    var card = text('article', '', 'sports-event' + (event.favorite ? ' favorite' : ''));
    card.tabIndex = -1;
    card.style.borderLeftColor = /^#[0-9a-f]{3,8}$/i.test(event.leagueColor || '') ? event.leagueColor : '';
    card.dataset.eventId = String(event.id || event.date + '-' + event.name + '-' + event.leagueName);
    var header = text('div', '', 'sports-event-head');
    header.append(text('span', event.leagueName + (event.session ? ' · ' + event.session : '')));
    var time = text('time', displayDate(event.date));
    if (event.date) time.dateTime = event.date;
    header.append(time);
    var participants = Array.isArray(event.participants) ? event.participants : [];
    var title = text('h2', event.name || participants.map(function (p) { return p.name; }).filter(Boolean).join(' vs. ') || event.leagueName);
    if (participants.length && !event.session) title.className = 'sports-event-title-sr';
    card.append(header, title);
    if (participants.length) {
      var list = text('div', '', 'sports-participants'), normalized = scoreStatus(event);
      participants.forEach(function (participant) {
        var row = text('div', '', 'sports-participant');
        row.append(text('span', participant.name || participant.abbr || 'Participant'));
        if (mode === 'scores') {
          var score = SportsScoreDisplay && SportsScoreDisplay.score ? SportsScoreDisplay.score(participant.score, normalized) : (participant.score == null ? '—' : String(participant.score));
          if (event.session) score = (participant.position ? 'P' + participant.position : '—') + (participant.displayClock ? ' · ' + participant.displayClock : '');
          row.append(text('span', score, 'sports-score'));
        }
        list.append(row);
      });
      card.append(list);
    }
    var statusText = event.status || (event.state === 'in' ? 'Live' : event.state === 'post' ? 'Final' : event.state === 'pre' ? 'Scheduled' : 'Status unavailable');
    card.append(text('div', statusText, event.state === 'in' ? 'sports-live' : 'sports-meta'));
    if (event.url) {
      var url = ToolUI.httpURL(event.url);
      if (url) { var link = text('a', 'Game details', 'sports-link'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link); }
    }
    return card;
  }
  function summaryText(targetsList) {
    var ok = entries.filter(function (row) { return row.entry && row.entry.status !== 'unavailable'; });
    var unavailable = targetsList.filter(function (league) { return !entries.some(function (row) { return row.league.name === league.name && row.entry && row.entry.status !== 'unavailable'; }); });
    var stale = ok.filter(function (row) { return row.entry.status === 'stale' || row.entry.source === 'snapshot' || row.entry.source === 'cache'; });
    var sources = Array.from(new Set(ok.map(function (row) { return row.entry.source; }).filter(Boolean)));
    var newest = ok.slice().sort(function (a,b) {
      return Date.parse(b.entry.retrievedAt || b.entry.generatedAt || b.entry.lastAttemptAt || 0) - Date.parse(a.entry.retrievedAt || a.entry.generatedAt || a.entry.lastAttemptAt || 0);
    })[0];
    var liveCount = ok.filter(function (row) { return row.entry.source === 'live'; }).length;
    var textValue = liveCount ? 'Live data · retrieved ' : stale.length ? 'Saved data · updated ' : 'Updated ';
    textValue += newest ? generatedLabel(newest.entry) : 'time unavailable';
    if (liveCount && stale.length) textValue += ' · some leagues use saved data';
    if (unavailable.length) textValue += ' · ' + unavailable.length + (unavailable.length === 1 ? ' league unavailable' : ' leagues unavailable');
    var coverages = ok.map(function (row) { return row.entry.coverage; }).filter(Boolean);
    if (coverages.length && coverages.some(function (coverage) { return coverage.complete === false; })) textValue += ' · partial date coverage';
    return textValue;
  }
  function preserveFocus(callback) {
    var active = document.activeElement;
    var wasContent = active && content.contains(active);
    var eventId = wasContent && active.closest && active.closest('[data-event-id]') ? active.closest('[data-event-id]').dataset.eventId : null;
    var pageDirection = wasContent && active.dataset ? active.dataset.pageControl : null;
    callback();
    if (eventId) {
      var match = Array.from(content.querySelectorAll('[data-event-id]')).find(function (el) { return el.dataset.eventId === eventId; });
      if (match) match.focus();
    } else if (pageDirection) {
      focusPager(pageDirection);
    }
  }
  function render(targetsList, statusOverride) {
    content.setAttribute('aria-busy', 'false');
    var all = selectedEvents(), emptyText, hasFeatured = false;
    if (mode === 'schedule') {
      var nextFavorite = all.find(function (event) { return event.favorite && (event.state === 'pre' || event.state === 'scheduled' || !event.state); });
      if (nextFavorite) {
        hasFeatured = true;
        var featured = text('section', '', 'sports-notice');
        featured.append(text('h2', 'Next favorite game'), renderEvent(nextFavorite));
        content.replaceChildren(featured);
        all = all.filter(function (event) { return event !== nextFavorite; });
      } else content.replaceChildren();
    } else content.replaceChildren();
    var status = text('p', statusOverride || summaryText(targetsList), 'sports-meta');
    content.append(status);
    if (!entries.some(function (row) { return row.entry && row.entry.payload; })) {
      var error = text('p', 'No sports data is available for this selection. Retry the selected view.', 'sports-error');
      var retry = text('button', 'Retry'); retry.type = 'button'; retry.addEventListener('click', function () { loadView(true); });
      error.append(' ', retry); content.append(error); return;
    }
    if (!all.length && !hasFeatured && mode === 'scores') emptyText = 'No games in this league on ' + new Date(state.date + 'T12:00:00').toLocaleDateString() + '.';
    else if (!all.length && !hasFeatured) emptyText = state.league === 'favorites' ? 'No favorite-team events appear in the returned eight-day scoreboards.' : 'No upcoming events appear in the returned scoreboards for these dates.';
    if (emptyText) { content.append(text('p', emptyText, 'sports-empty')); return; }
    var list = text('section', '', 'sports-list'); list.setAttribute('aria-label', mode === 'schedule' ? 'Upcoming games' : 'Scores');
    page = Math.max(0, Math.min(page, Math.ceil(all.length / pageSize) - 1));
    var visible = all.slice(page * pageSize, (page + 1) * pageSize);
    visible.forEach(function (event) { list.append(renderEvent(event)); });
    content.append(list);
    if (all.length > pageSize) {
      var nav = text('nav', '', 'sports-pager'); nav.setAttribute('aria-label', 'Pages');
      var prev = text('button', 'Previous'), next = text('button', 'Next');
      prev.type = next.type = 'button'; prev.disabled = page === 0; next.disabled = (page + 1) * pageSize >= all.length;
      prev.dataset.pageControl = 'previous'; next.dataset.pageControl = 'next';
      prev.addEventListener('click', function () { page--; pushState(); render(targetsList); focusPager('previous'); });
      next.addEventListener('click', function () { page++; pushState(); render(targetsList); focusPager('next'); });
      nav.append(prev, text('span', 'Page ' + (page + 1) + ' of ' + Math.ceil(all.length / pageSize)), next); content.append(nav);
    }
  }
  function loadView(force, silent) {
    if (!window.SportsData) {
      content.replaceChildren(text('p', 'Sports data is unavailable. Please retry.', 'sports-error'));
      return Promise.resolve();
    }
    var current = ++run, targetLeagues = targets(), kind = mode === 'schedule' ? 'schedule' : 'scores';
    if (!silent) content.replaceChildren(text('p', 'Loading selected sports data…', 'sports-meta'));
    if (!silent) content.setAttribute('aria-busy', 'true');
    if (!targetLeagues.length) { content.setAttribute('aria-busy', 'false'); content.replaceChildren(text('p', 'No enabled leagues are configured.', 'sports-empty')); return Promise.resolve(); }
    if (!silent) entries = [];
    var options = mode === 'scores' ? {date:state.date} : {date:state.date};
    function applyEntry(league, entry, isFinal) {
      if (current !== run) return;
      var index = entries.findIndex(function (row) { return row.league.name === league.name; });
      if (index >= 0 && entries[index].final && !isFinal) return;
      if (index >= 0) {
        entries[index].entry = entry;
        entries[index].final = !!isFinal || entries[index].final;
      } else entries.push({league:league, entry:entry, final:!!isFinal});
      preserveFocus(function () { render(targetLeagues); });
    }
    var tasks = targetLeagues.map(function (league) {
      if (mode === 'schedule') {
        return (async function () {
          try {
            var saved = await SportsData.saved(league, kind, options);
            if (current !== run) return;
            if (saved) applyEntry(league, saved, false);
          } catch (_) {}
          if (current !== run) return;
          try {
            var scheduleEntry = await SportsData.load(league, kind, Object.assign({}, options, {force:!!force, shouldContinue:function () { return current === run; }}));
            if (scheduleEntry && scheduleEntry.payload) applyEntry(league, scheduleEntry, true);
            else if (!entries.some(function (row) { return row.league.name === league.name; })) applyEntry(league, {status:'unavailable'}, true);
          } catch (_) {
            if (current === run && !entries.some(function (row) { return row.league.name === league.name; })) applyEntry(league, {status:'unavailable'}, true);
          }
        }());
      }
      var savedPromise = SportsData.saved(league, kind, options).then(function (saved) {
        if (saved) applyEntry(league, saved, false);
      }).catch(function () {});
      var livePromise = SportsData.load(league, kind, Object.assign({}, options, {force:!!force, shouldContinue:function () { return current === run; }}));
      return Promise.resolve(livePromise).then(function (finalEntry) {
        if (finalEntry && finalEntry.payload) applyEntry(league, finalEntry, true);
        else if (!entries.some(function (row) { return row.league.name === league.name; })) applyEntry(league, {status:'unavailable'}, false);
      }, function () {
        if (current === run && !entries.some(function (row) { return row.league.name === league.name; })) applyEntry(league, {status:'unavailable'}, false);
      }).then(function () { return savedPromise; });
    });
    return Promise.all(tasks);
  }
  async function initialize() {
    try {
      config = await SportsData.config();
      leagues = (config.leagues || []).filter(function (league) { return league && league.enabled !== false && Array.isArray(config.leagues); });
      state = routeState(); page = routePage(); buildSelector();
      selector.addEventListener('change', function () { state.league = this.value; page = 0; pushState(); loadView(false); });
      if (mode === 'scores') {
        dateInput.addEventListener('change', function () { if (!/^\d{4}-\d{2}-\d{2}$/.test(this.value)) return; state.date = this.value; page = 0; pushState(); loadView(false); });
        document.getElementById('sports-prev-day').addEventListener('click', function () { moveDate(-1); });
        document.getElementById('sports-next-day').addEventListener('click', function () { moveDate(1); });
        document.getElementById('sports-today').addEventListener('click', function () { state.date = today; dateInput.value = today; page = 0; pushState(); loadView(false); });
      }
      document.getElementById('sports-refresh').addEventListener('click', function () { loadView(true); });
      window.addEventListener('hashchange', restoreState);
      document.addEventListener('visibilitychange', function () {
        if (document.visibilityState !== 'visible') { run++; return; }
        if (mode === 'scores' && !pollBusy) { pollBusy = true; loadView(false, true).finally(function () { pollBusy = false; }); }
      });
      await loadView(false);
      if (mode === 'scores') window.setInterval(function () {
        if (document.visibilityState !== 'visible' || pollBusy) return;
        pollBusy = true; loadView(false, true).finally(function () { pollBusy = false; });
      }, 60000);
    } catch (_) {
      content.replaceChildren(text('p', 'Sports configuration is unavailable. Use Retry to load it again.', 'sports-error'));
      var retry = text('button', 'Retry'); retry.type = 'button'; retry.addEventListener('click', initialize); content.lastChild.append(' ', retry);
    }
  }
  function moveDate(amount) {
    var date = safeDate(state.date + 'T12:00:00'); if (!date) date = new Date();
    date.setDate(date.getDate() + amount); state.date = localDate(date); dateInput.value = state.date; page = 0; pushState(); loadView(false);
  }
  function restoreState() {
    if (!config) return;
    state = routeState(); page = routePage(); buildSelector(); loadView(false);
  }
  initialize();
}());
