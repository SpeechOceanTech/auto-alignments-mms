// Run with node tests/test_user_filter.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Option {
  constructor(text, value) { this.textContent = text; this.value = value; }
}
class Select {
  constructor() { this.options = []; this.value = ''; }
  replaceChildren(...options) { this.options = options; this.value = options[0]?.value || ''; }
  get selectedOptions() { return this.options.filter(option => option.value === this.value); }
}
const select = new Select(), elements = new Map();
function $(selector) {
  if (selector === '#filter-owner') return select;
  if (!elements.has(selector)) elements.set(selector, {classList:{toggle() {}}, value:'', textContent:''});
  return elements.get(selector);
}
let pending = [], refreshes = 0;
const state = {user:null, csrf:'', selected:new Map()};
const context = {$, state, Option, request:() => new Promise(resolve => pending.push(resolve)), closeReview(){}, hideNewKey(){}, switchTab(){}, refresh:async () => { refreshes++; }};
const source = fs.readFileSync('alignment_web/static/app.js', 'utf8');
const start = source.indexOf('function showAccount('), end = source.indexOf('async function checkSession()', start);
assert(start >= 0 && end > start);
vm.runInNewContext('let userFilterLoadVersion = 0;\n' + source.slice(start, end), context);
const refreshStart = source.indexOf("$('#refresh').onclick = ");
const refreshEnd = source.indexOf(" $('#prev-page').onclick", refreshStart);
assert(refreshStart >= 0 && refreshEnd > refreshStart);
vm.runInNewContext(source.slice(refreshStart, refreshEnd), context);
async function settle() { await new Promise(resolve => setImmediate(resolve)); }
(async () => {
  context.showAccount({id:'admin', is_admin:true});
  pending.shift()({users:[{id:'alice', username:'Alice'}]}); await settle();
  select.value = 'alice';
  const clicked = $('#refresh').onclick(); await settle();
  assert.equal(refreshes, 1);
  pending.shift()({users:[{id:'alice', username:'Alice'}, {id:'bob', username:'Bob'}]});
  await clicked;
  assert.equal(select.value, 'alice'); assert(select.options.some(option => option.value === 'bob'));
  const stale = context.loadFilterUsers('admin');
  context.showAccount(null);
  assert.deepEqual(select.options.map(option => option.value), ['', '__legacy__']);
  context.showAccount({id:'admin', is_admin:true});
  pending.shift()({users:[{id:'stale', username:'Stale'}]}); await stale;
  assert(!select.options.some(option => option.value === 'stale'));
  pending.shift()({users:[{id:'fresh', username:'Fresh'}]}); await settle();
  assert(select.options.some(option => option.value === 'fresh'));
  console.log('user filter refresh tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
