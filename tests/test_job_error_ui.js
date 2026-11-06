// Run with node tests/test_job_error_ui.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag, text = '', cls = '') { this.tag = tag; this.children = []; this.textContent = text; this.className = cls; this.attributes = {}; }
  set textContent(text) { this._textContent = text; this.children = []; }
  get textContent() { return this.children.length ? this.children.map(child => child.textContent).join('') : this._textContent; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._textContent = ''; this.children = children; }
  setAttribute(name, value) { this.attributes[name] = value; }
  showModal() { this.open = true; }
}
const elements = {'#job-error-dialog':new Element('dialog'), '#job-error-file':new Element('p'), '#job-error-details':new Element('pre')};
const source = fs.readFileSync('alignment_web/static/app.js', 'utf8');
const start = source.indexOf('function showJobError('), end = source.indexOf('async function refresh()', start);
assert(start >= 0 && end > start);
const context = {$:selector => elements[selector], state:{user:{is_admin:false},selected:new Map()}, node:(...args) => new Element(...args), action:(text, callback, cls = '') => { const el = new Element('button', text, `text-button ${cls}`); el.onclick = callback; return el; }, formatDate:value => value, statusNames:{completed:'完成',failed:'失败'}, updateSelection(){}, showReview(){}, copyJobId(){}, retry(){}, removeJobs(){}};
vm.runInNewContext(source.slice(start, end), context);
const job = {id:'abcdefgh1234', audio_name:'音频.wav', language:'zh_cn', created_at:'today', status:'failed', error:'Traceback\nValueError: <not HTML>', error_code:'empty_sentence', error_display:'第 157 句没有可用于对齐的文字。\n原文：<img src=x onerror=alert(1)>\n请检查文本。'};
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
assert.equal(elements['#job-error-details'].children[0].tag, 'strong');
assert.equal(elements['#job-error-details'].children[0].className, 'job-error-conclusion');
assert.equal(elements['#job-error-details'].children[0].textContent, '第 157 句没有可用于对齐的文字。');
assert.equal(elements['#job-error-details'].children[1].tag, 'span');
assert.equal(elements['#job-error-details'].children[1].textContent, '\n原文：<img src=x onerror=alert(1)>\n请检查文本。', 'detail stays text, not HTML');
const longMessage = '文本相对于音频过长，无法完成对齐。请检查对应文本和音频。';
context.showJobError({...job, error_code:'transcript_too_long', error_display:longMessage});
assert.equal(elements['#job-error-details'].children[0].textContent, '文本相对于音频过长，无法完成对齐。');
assert.equal(elements['#job-error-details'].children[1].textContent, '请检查对应文本和音频。');
context.showJobError({...job, error_code:'unknown', error_display:job.error});
assert.equal(elements['#job-error-details'].textContent, job.error, 'unknown errors retain the full raw error');
assert.equal(elements['#job-error-details'].children.length, 0, 'unknown errors are not styled');
context.showJobError({...job, error_code:'future_known_error', error_display:'未来归类的原因。建议检查输入。'});
assert.equal(elements['#job-error-details'].children[0].textContent, '未来归类的原因。', 'future classified errors also highlight their conclusion');
context.showJobError({...job, error_code:'unknown', error_display:null, error:null});
assert.equal(elements['#job-error-details'].textContent, '暂无错误信息。');
const completed = context.renderJob({...job, status:'completed'});
assert(!completed.children[6].children[0].children.some(button => button.textContent === '错误原因'));
const html = fs.readFileSync('alignment_web/static/index.html', 'utf8');
assert.match(html, /<dialog id="job-error-dialog"[^>]*aria-labelledby="job-error-title"/);
assert.match(html, /<form method="dialog">\s*<h2 id="job-error-title">/);
const css = fs.readFileSync('alignment_web/static/style.css', 'utf8');
assert.match(css, /\.job-error-conclusion\s*\{[^}]*color:\s*var\(--danger\)[^}]*font-weight:\s*700/);
console.log('job error UI tests passed');
