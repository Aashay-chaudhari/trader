const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../src/agent_trader/runtime/web/app.js'), 'utf8');
const boot = "window.addEventListener('hashchange',render);load();setInterval(load,60000);";
assert.ok(source.includes(boot));
// Exercise the actual view functions without browser startup or any fetch.
const context = vm.createContext({});
vm.runInContext(source.replace(boot, ''), context);

function chart(groups) {
  const rows = groups.flatMap((values, index) => ['intraday', 'swing', 'options'].map((branch, i) => ({
    branch, at: `2026-11-07T12:${String(index).padStart(2, '0')}:00+00:00`, value: values[i],
  })));
  // Pass objects directly: JSON would replace NaN/Infinity before the view sees them.
  context.fixture = {equity: rows.reverse()};
  vm.runInContext('state=fixture', context);
  return vm.runInContext('chart()', context);
}

test('measured zero remains a valid complete three-branch observation', () => {
  const html = chart([[0, 0, 0], [10000, 10000, 10000]]);
  assert.ok(html.includes('<polyline'));
  assert.ok(!html.includes('NaN'));
});

test('missing, nonfinite and overflowed buckets do not become zero or chart coordinates', () => {
  for (const bad of [[null, 10000, 10000], [undefined, 10000, 10000], [NaN, 10000, 10000], [Infinity, 10000, 10000], [1e308, 1e308, 10000]]) {
    const html = chart([[10000, 10000, 10000], bad]);
    assert.ok(!html.includes('<polyline'));
    assert.ok(html.includes('Awaiting complete equity observations'));
  }
});

test('incomplete buckets are omitted while complete observations keep their values', () => {
  const complete = chart([[10000, 10000, 10000], [10010, 10000, 10000]]);
  const missing = chart([[10000, 10000, 10000], [null, 10000, 10000], [10010, 10000, 10000]]);
  assert.equal(missing, complete);
  assert.equal(vm.runInContext('state.equity.filter(row=>row.value===null).length', context), 1);
});

test('an unexpected branch cannot substitute for an absent branch', () => {
  context.fixture = {equity: [
    {at: '2026-11-07T12:00:00Z', branch: 'intraday', value: 10000},
    {at: '2026-11-07T12:00:00Z', branch: 'swing', value: 10000},
    {at: '2026-11-07T12:00:00Z', branch: 'unexpected', value: 10000},
    {at: '2026-11-07T12:01:00Z', branch: 'intraday', value: 10000},
    {at: '2026-11-07T12:01:00Z', branch: 'swing', value: 10000},
    {at: '2026-11-07T12:01:00Z', branch: 'options', value: 10000},
  ]};
  vm.runInContext('state=fixture', context);
  assert.ok(vm.runInContext('chart()', context).includes('Awaiting complete equity observations'));
});

test('unknown monetary values remain distinct from real zero and numeric fee strings', () => {
  assert.equal(vm.runInContext('money(null)', context), 'Unknown');
  assert.equal(vm.runInContext('signed(null)', context), 'Unknown');
  assert.equal(vm.runInContext('pct(null)', context), 'Unknown');
  assert.equal(vm.runInContext('money(0)', context), '$0.00');
  assert.equal(vm.runInContext('signed(0)', context), '+$0.00');
  assert.equal(vm.runInContext("money('-0.03')", context), '-$0.03');
});

test('session panel labels unknown evidence and actual regular close without claiming readiness', () => {
  context.fixture = {operational_session: {state: 'unknown', assessed_at: '2026-11-27T12:49:31-05:00', reason_codes: ['clock_timestamp_stale'], calendar: {day: '2026-11-27', close_at: '2026-11-27T13:00:00-05:00'}, clock: {timestamp: '2026-11-27T12:49:00-05:00'}}};
  vm.runInContext('state=fixture', context);
  const html = vm.runInContext('sessionEvidencePanel()', context);
  assert.ok(html.includes('Unknown / awaiting compatible evidence'));
  assert.ok(html.includes('Regular close'));
  assert.ok(html.toLowerCase().includes('clock timestamp stale'));
  assert.ok(html.includes('Existing protection remains'));
  assert.ok(!html.includes('Regular session confirmed'));
});

test('session panel distinguishes a confirmed non-session from missing evidence', () => {
  context.fixture = {operational_session: {state: 'non_session', reason_codes: [], calendar: {day: '2026-11-07'}}};
  vm.runInContext('state=fixture', context);
  assert.ok(vm.runInContext('sessionEvidencePanel()', context).includes('No regular session today'));
  context.fixture = {};
  vm.runInContext('state=fixture', context);
  const html = vm.runInContext('sessionEvidencePanel()', context);
  assert.ok(html.includes('Unknown / awaiting compatible evidence'));
  assert.ok(!html.includes('No regular session today'));
});
