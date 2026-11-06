// Run with node tests/test_precheck_dialog.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag, text, cls) { this.tag = tag; this.textContent = text; this.className = cls; this.children = []; this.listeners = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  showModal() { this.open = true; }
  close(value) { this.returnValue = value; this.listeners.close(); }
}
const dialog = new Element('dialog'), list = new Element('div');
const source = fs.readFileSync('alignment_web/static/app.js', 'utf8');
const start = source.indexOf('function reviewPrecheckWarnings('), end = source.indexOf('function sendJob(', start);
assert(start >= 0 && end > start);
const context = {$: selector => selector === '#precheck-dialog' ? dialog : list, node: (...args) => new Element(...args), Set};
vm.runInNewContext(source.slice(start, end), context);
(async () => {
  const first = context.reviewPrecheckWarnings([
    {pair:{audio:'多文本.wav'}, result:{status:'warning',message:'文本可能过长'}},
    {pair:{audio:'无法检查.wav'}, result:{status:'unknown',message:'无法检查'}},
  ]);
  assert.equal(dialog.open, true);
  assert.equal(list.children.length, 2);
  assert.equal(list.children[0].children[0].checked, true);
  assert.equal(list.children[0].children[1].children[0].textContent, '多文本.wav');
  list.children[0].children[0].checked = false;
  dialog.close('continue');
  assert.deepEqual([...await first], ['多文本.wav']);
  const second = context.reviewPrecheckWarnings([{pair:{audio:'x.wav'}, result:{status:'warning',message:'检查'}}]);
  dialog.close('cancel');
  assert.equal(await second, null);
  console.log('precheck dialog tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
