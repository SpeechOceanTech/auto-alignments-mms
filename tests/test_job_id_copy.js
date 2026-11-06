// Run with node tests/test_job_id_copy.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag, text = '', cls = '') { this.tag = tag; this.textContent = text; this.className = cls; this.children = []; this.attributes = {}; this.style = {}; }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.focused = true; }
  select() { this.selected = true; }
  remove() { this.removed = true; }
}
const previous = new Element('button'), message = new Element('p');
let copied, temporary, result = true;
const document = {activeElement:previous, createElement:tag => new Element(tag), body:{append:el => { temporary = el; }}, execCommand:command => { assert.equal(command, 'copy'); copied = temporary.value; return result; }};
const source = fs.readFileSync('alignment_web/static/app.js', 'utf8');
const start = source.indexOf('async function copyText('), end = source.indexOf('async function refresh()', start);
assert(start >= 0 && end > start);
const context = {document, window:{isSecureContext:false}, navigator:{}, $:() => message, state:{user:{is_admin:false},selected:new Map()}, node:(...args) => new Element(...args), action:(text, callback, cls = '') => { const el = new Element('button', text, `text-button ${cls}`); el.type = 'button'; el.onclick = callback; return el; }, formatDate:value => value, statusNames:{completed:'完成'}, updateSelection(){}, showReview(){}, retry(){}, removeJobs(){}};
vm.runInNewContext(source.slice(start,end), context);
(async () => {
  const id = 'abcdef12-3456-7890-abcd-ef1234567890';
  const row = context.renderJob({id, audio_name:'test.wav', language:'zh_cn', created_at:'today', status:'completed'});
  const cell = row.children[5], button = cell.children[0];
  assert.equal(button.tag, 'button'); assert.equal(button.type, 'button'); assert.equal(button.textContent, 'abcdef12');
  assert.match(button.attributes['aria-label'], new RegExp(id));
  await button.onclick();
  assert.equal(copied, id, 'HTTP fallback copies the complete ID');
  assert.equal(temporary.removed, true); assert.equal(previous.focused, true);
  assert.match(message.textContent, /已复制完整任务 ID/);
  result = false; await button.onclick();
  assert.match(message.textContent, /复制失败/); assert.match(message.textContent, new RegExp(id));
  context.window.isSecureContext = true; context.navigator.clipboard = {writeText:async value => { copied = value; }};
  copied = null; await button.onclick(); assert.equal(copied, id, 'secure context uses Clipboard API');
  context.navigator.clipboard.writeText = async () => { throw new Error('denied'); };
  result = true; copied = null; await button.onclick(); assert.equal(copied, id, 'permission denial falls back to document copy');
  console.log('job ID copy tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
