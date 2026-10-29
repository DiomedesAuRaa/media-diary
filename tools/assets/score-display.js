(function (root, factory) {
    'use strict';
    var display = factory();
    if (typeof module === 'object' && module.exports) module.exports = display;
    else root.SportsScoreDisplay = display;
}(typeof window !== 'undefined' ? window : globalThis, function () {
    'use strict';

    function suppressScore(comp) {
        var type = comp && comp.status && comp.status.type || {};
        var name = String(type.name || '').toUpperCase();
        var detail = String(type.shortDetail || type.detail || type.description || '').toUpperCase();
        var state = String(type.state || '').toLowerCase();
        if (state === 'in' || state === 'post') return false;
        return state === 'pre' || name === 'STATUS_SCHEDULED'
            || /CANCELLED|CANCELED|POSTPONED|DELAYED/.test(name + ' ' + detail);
    }

    function score(value, comp) {
        if (suppressScore(comp) || value === null || value === undefined || value === '') return '—';
        return String(value);
    }

    return {score: score};
}));
