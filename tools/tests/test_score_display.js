'use strict';

const assert = require('node:assert/strict');
const {score} = require('../assets/score-display.js');

const scheduled = {status:{type:{name:'STATUS_SCHEDULED', state:'pre'}}};
const live = {status:{type:{name:'STATUS_IN_PROGRESS', state:'in'}}};
const final = {status:{type:{name:'STATUS_FINAL', state:'post'}}};
const postponed = {status:{type:{name:'STATUS_POSTPONED', shortDetail:'Postponed'}}};
const delayedLive = {status:{type:{name:'STATUS_IN_PROGRESS', state:'in', shortDetail:'Delayed'}}};
const delayedFinal = {status:{type:{name:'STATUS_FINAL', state:'post', detail:'Delayed'}}};

assert.equal(score('0', scheduled), '—', 'scheduled zero is not a played score');
assert.equal(score('12', {status:{type:{name:'STATUS_UNKNOWN', state:'pre'}}}), '—', 'pre-game scores stay hidden');
assert.equal(score('0', live), '0', 'live zero remains a real score');
assert.equal(score('0', final), '0', 'final zero remains a real score');
assert.equal(score(null, live), '—', 'missing live score uses an em dash');
assert.equal(score('', final), '—', 'missing final score uses an em dash');
assert.equal(score('0', postponed), '—', 'postponed zero is not a played score');
assert.equal(score('4', delayedLive), '4', 'in-game delay retains live score');
assert.equal(score('7', delayedFinal), '7', 'post-game delay retains final score');

process.stdout.write('Score display fixtures passed.\n');
