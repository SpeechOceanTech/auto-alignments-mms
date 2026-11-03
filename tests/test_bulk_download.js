// Run with node tests/test_bulk_download.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('alignment_web/static/index.html', 'utf8');
assert.match(html, /name="bulk-format" value="csv" checked/);
assert.match(html, /name="bulk-format" value="textgrid"/);
assert.match(html, /name="bulk-format" value="txt"/);
const formats = ['csv', 'textgrid', 'txt'].map((value, index) => ({value, checked:index === 0, addEventListener(name, cb) { this.change = cb; }}));
const elements = new Map();
function $(selector) { if (!elements.has(selector)) elements.set(selector, {textContent:'', open:false}); return elements.get(selector); }
let clicks = [], requests = [];
const context = {
  $, state:{selected:new Map()}, URLSearchParams,
  document:{querySelectorAll(selector) { return selector.endsWith(':checked') ? formats.filter(item => item.checked) : formats; }, createElement() { return {click() { clicks.push({href:this.href, download:this.download}); }}; }},
  fetch: async url => { requests.push(url); return {ok:true, blob:async () => 'blob'}; },
  URL:{createObjectURL:() => 'blob:url', revokeObjectURL() {}}, setTimeout() {},
};
const source = fs.readFileSync('alignment_web/static/app.js', 'utf8');
const start = source.indexOf('function selectedDownloadFormats()'), end = source.indexOf("$('#refresh').onclick =", start);
assert(start >= 0 && end > start);
vm.runInNewContext(source.slice(start, end), context);
(async () => {
  context.state.selected.set('abc', 'completed');
  $('#download-selected').onclick();
  assert.deepEqual(clicks.pop(), {href:'/v1/jobs/abc/artifacts/csv', download:undefined});
  assert.equal(requests.length, 0);
  formats[1].checked = true; formats[1].change();
  assert.equal($('#bulk-format-summary').textContent, '下载格式：CSV、TextGrid');
  $('#download-selected').onclick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(new URLSearchParams(requests.pop().split('?')[1]).get('formats'), 'csv,textgrid');
  assert.equal(clicks.pop().download, 'alignment-results.zip');
  formats.forEach(format => { format.checked = false; });
  $('#download-selected').onclick();
  assert.equal($('#jobs-message').textContent, '请选择至少一种下载格式。');
  assert.equal($('#bulk-format-menu').open, true);
  formats[2].checked = true;
  context.state.selected.set('def', 'completed');
  $('#download-selected').onclick();
  await new Promise(resolve => setImmediate(resolve));
  const query = new URLSearchParams(requests.pop().split('?')[1]);
  assert.equal(query.get('formats'), 'txt');
  assert.equal(query.get('job_ids'), 'abc,def');
  console.log('bulk download tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
