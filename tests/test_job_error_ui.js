// Run with node tests/test_job_error_ui.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag, text = '', cls = '') { this.tag = tag; this.textContent = text; this.className = cls; this.children = []; this.attributes = {}; }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { this.attributes[name] = value; }
  showModal() { this.open = true; }
}
const elements = {'#job-error-dialog':new Element('dialog'), '#job-error-file':new Element('p'), '#job-error-details':new Element('pre')};
const source = fs.readFileSync('alignment_web/static/app.js', 'utf8');
const start = source.indexOf('function showJobError('), end = source.indexOf('async function refresh()', start);
assert(start >= 0 && end > start);
const context = {$:selector => elements[selector], state:{user:{is_admin:false},selected:new Map()}, node:(...args) => new Element(...args), action:(text, callback, cls = '') => { const el = new Element('button', text, `text-button ${cls}`); el.onclick = callback; return el; }, formatDate:value => value, statusNames:{completed:'完成',failed:'失败'}, updateSelection(){}, showReview(){}, copyJobId(){}, retry(){}, removeJobs(){}};
vm.runInNewContext(source.slice(start, end), context);
const job = {id:'abcdefgh1234', audio_name:'音频.wav', language:'zh_cn', created_at:'today', status:'failed', error:'Traceback\nValueError: <not HTML>', error_display:'第 157 句没有可以对齐的文字，请检查文本。'};
const row = context.renderJob(job);
assert.equal(row.children[1].textContent, job.audio_name);
assert.equal(row.children[1].children.length, 0, 'failure stack must not expand the row');
const buttons = row.children[6].children[0].children;
const errorButton = buttons.find(button => button.textContent === '错误原因');
assert(errorButton);
assert.equal(errorButton.attributes['aria-haspopup'], 'dialog');
errorButton.onclick();
assert.equal(elements['#job-error-dialog'].open, true);
assert.equal(elements['#job-error-file'].textContent, job.audio_name);
assert.equal(elements['#job-error-details'].textContent, job.error_display, 'known errors use human-readable message');
context.showJobError({...job, error_display:null});
assert.equal(elements['#job-error-details'].textContent, job.error, 'unknown errors retain the full raw error');
context.showJobError({...job, error_display:null, error:null});
assert.equal(elements['#job-error-details'].textContent, '暂无错误信息。');
const completed = context.renderJob({...job, status:'completed'});
assert(!completed.children[6].children[0].children.some(button => button.textContent === '错误原因'));
const html = fs.readFileSync('alignment_web/static/index.html', 'utf8');
assert.match(html, /<dialog id="job-error-dialog"[^>]*aria-labelledby="job-error-title"/);
assert.match(html, /<form method="dialog">\s*<h2 id="job-error-title">/);
console.log('job error UI tests passed');
