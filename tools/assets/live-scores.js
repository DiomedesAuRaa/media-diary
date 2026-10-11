/* Public live score client. Published snapshots remain the fallback. */
(function () {
    'use strict';

    var staticSnapshotLoader = window.loadSportsSnapshot;
    var liveEntries = {};
    var staticEntries = {};
    var staticSnapshotLoaded = false;
    var staticFallbackPromise = null;
    var lastRetrieved = {};
    var pendingLeagues = null;
    var pollSeconds = 60;
    var pageStarted = false;
    var selectedHash = '';
    var requestGeneration = 0;
    var snapshotQueue = Promise.resolve();
    var inFlightByLeague = {};
    var liveErrors = {};
    var activeLiveRequests = 0;
    var liveRequestWaiters = [];
    window.LIVE_SCORE_ERRORS = [];

    var SPORTS_CONFIG_ROOT = null;
    var originalLoadConfig = window.loadConfig;
    window.loadConfig = async function () {
        await originalLoadConfig();
        SPORTS_CONFIG_ROOT = window.SPORTS_CONFIG_ROOT;
    };

    function enabledNames() { return Object.keys(SPORTS_CONFIG); }
    function nameForHash() {
        var hash;
        try { hash = decodeURIComponent(location.hash.slice(1)); }
        catch (_) { return ''; }
        if (!hash) return '';
        if (hash === 'section-FAVORITES') return '';
        var found = enabledNames().find(function (name) {
            return 'section-' + name.replace(/[^a-z0-9]/gi, '_') === hash;
        });
        return found || '';
    }
    function uniqueNames(names) {
        return names.filter(function (name, index) { return name && enabledNames().indexOf(name) >= 0 && names.indexOf(name) === index; });
    }
    function limitedMap(items, limit, fn) {
        var next = 0;
        var workers = Array.from({length: Math.min(limit, items.length)}, async function () {
            while (next < items.length) {
                var index = next++;
                await fn(items[index]);
            }
        });
        return Promise.all(workers);
    }
    function acquireLiveRequest() {
        if (activeLiveRequests < 3) {
            activeLiveRequests++;
            return Promise.resolve();
        }
        return new Promise(function (resolve) { liveRequestWaiters.push(resolve); });
    }
    function releaseLiveRequest() {
        var next = liveRequestWaiters.shift();
        if (next) next();
        else activeLiveRequests--;
    }
    function directScoreURL(name) {
        var league = (SPORTS_CONFIG_ROOT.leagues || []).find(function (item) { return item.name === name && item.enabled !== false; });
        var path = league && league.espn_path;
        if (typeof path !== 'string' || !/^[a-z0-9.-]+(?:\/[a-z0-9.-]+)*$/i.test(path)) throw new Error('Invalid league path');
        var encodedPath = path.split('/').map(encodeURIComponent).join('/');
        return 'https://site.web.api.espn.com/apis/site/v2/sports/' + encodedPath + '/scoreboard?region=us&lang=en&contentorigin=espn';
    }
    function validateReply(reply, name) {
        if (!reply || typeof reply !== 'object' || !Array.isArray(reply.events) || reply.events.length > 2000) return false;
        var racing = SPORTS_CONFIG[name] && SPORTS_CONFIG[name].scoresType === 'racing';
        return reply.events.every(function (event) {
            var comp = event && Array.isArray(event.competitions) ? event.competitions[0] : null;
            if (!comp || !comp.status || !comp.status.type || typeof comp.status.type.name !== 'string' || !Array.isArray(comp.competitors)) return false;
            if (racing) return comp.competitors.length > 0 && comp.competitors.every(function (competitor) {
                return !!(competitor && (competitor.athlete || (competitor.team && (competitor.team.abbreviation || competitor.team.shortDisplayName))));
            });
            var home = comp.competitors.some(function (competitor) { return competitor && competitor.homeAway === 'home' && competitor.team; });
            var away = comp.competitors.some(function (competitor) { return competitor && competitor.homeAway === 'away' && competitor.team; });
            return home && away;
        });
    }
    function entryFromReply(reply, retrievedAt) {
        return {status:'ok', generatedAt:retrievedAt, lastAttemptAt:retrievedAt, retrievedAt:retrievedAt, payload:reply};
    }
    function entryMap() {
        var map = {};
        enabledNames().forEach(function (name) {
            var key = SPORTS_CONFIG[name].url;
            var live = liveEntries[name], saved = staticEntries[key];
            if (live && saved) {
                var liveTime = Date.parse(live.generatedAt), savedTime = Date.parse(saved.generatedAt);
                map[key] = Number.isFinite(savedTime) && (!Number.isFinite(liveTime) || savedTime > liveTime) ? saved : live;
            } else if (live || saved) map[key] = live || saved;
            if (map[key] && liveErrors[name]) map[key] = Object.assign({}, map[key], {status:'stale'});
        });
        return map;
    }
    async function loadStaticFallback() {
        if (staticSnapshotLoaded) return;
        if (!staticFallbackPromise) staticFallbackPromise = (async function () {
            try {
                var snapshot = await staticSnapshotLoader();
                if (snapshot && snapshot.entries && typeof snapshot.entries === 'object') {
                    staticEntries = snapshot.entries;
                    staticSnapshotLoaded = true;
                }
            } catch (_) {}
        }());
        await staticFallbackPromise;
        if (!staticSnapshotLoaded) staticFallbackPromise = null;
    }

    window.loadSportsSnapshot = function () {
        var names = pendingLeagues === null ? enabledNames() : uniqueNames(pendingLeagues);
        pendingLeagues = null;
        var generation = ++requestGeneration;
        var operation = snapshotQueue.then(async function () {
        await limitedMap(names, 3, async function (name) {
            if (inFlightByLeague[name]) {
                if (await inFlightByLeague[name]) delete liveErrors[name];
                else liveErrors[name] = true;
                return;
            }
            var pending = (async function () {
                await acquireLiveRequest();
                try {
                    var response = await ToolUI.fetch(directScoreURL(name), {cache:'no-cache'});
                    if (!response.ok) throw new Error('HTTP ' + response.status);
                    var reply = await response.json();
                    if (!validateReply(reply, name)) throw new Error('Invalid scoreboard response');
                    var retrievedAt = new Date().toISOString();
                    liveEntries[name] = entryFromReply(reply, retrievedAt);
                    lastRetrieved[name] = Date.now();
                    return true;
                } catch (_) { return false; }
                finally { releaseLiveRequest(); }
            }());
            inFlightByLeague[name] = pending;
            var succeeded = await pending;
            delete inFlightByLeague[name];
            if (succeeded) delete liveErrors[name];
            else liveErrors[name] = true;
        });
        if (Object.keys(liveErrors).length) await loadStaticFallback();
        var entries = entryMap();
        var lastAttempts = Object.keys(entries).map(function (key) { return Date.parse(entries[key].lastAttemptAt); }).filter(Number.isFinite);
        if (generation === requestGeneration) window.LIVE_SCORE_ERRORS = Object.keys(liveErrors);
        var retrievedTimes = Object.keys(entries).map(function (key) { return Date.parse(entries[key].retrievedAt); }).filter(Number.isFinite);
        var result = {version:1, entries:entries, lastAttemptAt:lastAttempts.length ? new Date(Math.max.apply(null, lastAttempts)).toISOString() : null, retrievedAt:retrievedTimes.length ? new Date(Math.max.apply(null, retrievedTimes)).toISOString() : null};
        if (generation === requestGeneration) SPORTS_SNAPSHOT = result;
        return result;
        });
        snapshotQueue = operation.then(function () {}, function () {});
        return operation;
    };

    function liveFavoriteLeagues() {
        var set = {};
        (scoreResults || []).forEach(function (result) {
            if ((result.priorityGames || []).some(function (comp) {
                var type = comp.status && comp.status.type && comp.status.type.name;
                if (type === 'STATUS_IN_PROGRESS' || (comp.status && comp.status.type && comp.status.type.state === 'in')) return true;
                var start = Date.parse(comp.date);
                return type === 'STATUS_SCHEDULED' && Number.isFinite(start) && Math.abs(start - Date.now()) <= 15 * 60 * 1000;
            })) set[result.sportName] = true;
        });
        return Object.keys(set);
    }
    function leaguesToPoll() {
        var names = liveFavoriteLeagues();
        var selected = nameForHash();
        if (selected) names.push(selected);
        return uniqueNames(names);
    }
    function refreshNames(names) {
        if (!names || !names.length) return;
        pendingLeagues = names;
        loadScores(true, true);
    }
    function requestIfStale(names) {
        var staleAfter = Math.max(60, pollSeconds) * 1000;
        var due = names.filter(function (name) { return !lastRetrieved[name] || Date.now() - lastRetrieved[name] >= staleAfter; });
        refreshNames(due);
    }
    function selectedChanged() {
        var current = location.hash;
        if (current === selectedHash) return;
        selectedHash = current;
        var name = nameForHash();
        if (name) requestIfStale([name]);
    }
    window.updateTimestamp = function (failedCount, snapshot, staleCount) {
        var now = new Date();
        document.getElementById('currentDate').textContent = now.toLocaleDateString('en-US', {weekday:'short', month:'short', day:'numeric', year:'numeric'});
        var cachedTime = Number.isFinite(snapshot) ? new Date(snapshot).toLocaleTimeString() : null;
        var retrieved = snapshot && snapshot.retrievedAt ? new Date(snapshot.retrievedAt).toLocaleTimeString() : null;
        var text = cachedTime ? 'Showing saved scores from ' + cachedTime : (retrieved ? 'Live scores retrieved ' + retrieved : 'Published snapshot checked ' + (snapshot && snapshot.lastAttemptAt ? formatSnapshotTime(snapshot.lastAttemptAt) : 'time unavailable'));
        if (failedCount) text += ' · ' + failedCount + ' unavailable';
        if (staleCount) text += ' · ' + staleCount + ' stale';
        document.getElementById('lastUpdate').textContent = text;
    };

    document.getElementById('refresh-scores').addEventListener('click', function () {
        var name = nameForHash();
        refreshNames(name ? [name] : enabledNames());
    });
    window.addEventListener('hashchange', selectedChanged);
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') requestIfStale(leaguesToPoll());
    });
    window.addEventListener('pageshow', function () {
        if (document.visibilityState === 'visible') requestIfStale(leaguesToPoll());
    });

    async function start() {
        try {
            await loadConfig();
        } catch (err) {
            ToolUI.setHTML(document.getElementById('content'), '<div class="config-error">Could not load sports-config.json: ' + ToolUI.escape(err.message) + '. <button type="button" id="retry-config">Retry</button></div>');
            document.getElementById('retry-config').addEventListener('click', start);
            return;
        }
        if (pageStarted) return;
        pageStarted = true;
        selectedHash = location.hash;
        loadScores();
        window.setInterval(function () {
            if (document.visibilityState !== 'visible') return;
            requestIfStale(leaguesToPoll());
        }, pollSeconds * 1000);
    }

    start();
}());
