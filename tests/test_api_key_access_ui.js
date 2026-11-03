// Run with node tests/test_api_key_access_ui.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.hidden = true; this.value = ''; this.textContent = ''; this.disabled = false; this.children = []; this.classList = {toggle() {}}; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
}
const elements = new Map();
function $(selector) { if (!elements.has(selector)) elements.set(selector, new Element()); return elements.get(selector); }
class Option { constructor(text, value) { this.textContent = text; this.value = value; } }
const state = {user:null, csrf:'', selected:new Map()};
const pending = [];
const context = {$, state, Option, request:(url, options) => new Promise(resolve => pending.push({url, options, resolve})), json:body => ({method:'POST', body:JSON.stringify(body)}), closeReview(){}, loadFilterUsers(){}, loadUsers(){}, loadStatistics(){}, node:() => new Element(), action:() => new Element(), formatDate:value => value, confirm:() => true, navigator:{}, window:{}};
const source = fs.readFileSync('alignment_web/static/app.js', 'utf8');
function section(start, end) { const from = source.indexOf(start), to = source.indexOf(end, from); assert(from >= 0 && to > from); return source.slice(from, to); }
vm.runInNewContext('let userFilterLoadVersion = 0; let apiKeyViewVersion = 0;\n' +
  section('function showAccount(', 'async function loadFilterUsers(') +
  section('function switchTab(', "$('#tab-details').onclick") +
  section('function hideNewKey()', 'async function loadLanguages()'), context);
(async () => {
  context.showAccount({id:'admin', is_admin:true});
  assert.equal($('#tab-api-keys').hidden, false);
  context.switchTab('keys');
  assert.equal($('#api-keys-panel').hidden, false);
  pending.shift().resolve({keys:[]}); await new Promise(resolve => setImmediate(resolve));
  $('#api-key-name').value = 'test';
  const creation = $('#api-key-form').onsubmit({preventDefault(){}});
  assert.equal(pending.length, 1);
  context.showAccount({id:'normal', is_admin:false});
  assert.equal($('#tab-api-keys').hidden, true);
  assert.equal($('#api-keys-panel').hidden, true);
  context.switchTab('keys');
  assert.equal($('#api-keys-panel').hidden, true);
  assert.equal($('#task-detail-panel').hidden, false);
  await $('#api-key-form').onsubmit({preventDefault(){}});
  assert.equal(pending.length, 1);
  pending.shift().resolve({token:'secret-from-old-account'}); await creation;
  assert.equal($('#api-key-secret').value, '');
  assert.equal($('#new-api-key').hidden, true);
  context.showAccount({id:'admin', is_admin:true}); context.switchTab('keys');
  const staleList = pending.shift();
  context.showAccount(null);
  staleList.resolve({keys:[]}); await new Promise(resolve => setImmediate(resolve));
  assert.equal($('#api-key-list').textContent, '');
  assert.equal($('#api-keys-panel').hidden, true);
  console.log('API key access UI tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
