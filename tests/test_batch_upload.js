// Run with node tests/test_batch_upload.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('alignment_web/static/index.html', 'utf8');
assert.match(html, /id="language" name="language" required/);
assert.doesNotMatch(html, /id="language"[^>]*value="zh_cn"/);
assert.match(html, /id="batch-audio"[^>]*multiple/);
assert.match(html, /id="batch-text"[^>]*multiple/);
const source = fs.readFileSync('alignment_web/static/app.js', 'utf8');
const start = source.indexOf('// The batch is registered'), end = source.indexOf('health(); checkSession();', start);
// The final boot now has additional work; locate it independently.
const stop = end < 0 ? source.indexOf('health(); checkSession().then', start) : end;
assert(start >= 0 && stop > start);
const elements = new Map();
function $(selector) {
  if (!elements.has(selector)) elements.set(selector, {value:'', files:[], textContent:'', hidden:false, disabled:false, style:{}, classList:{toggle() {}}, setAttribute() {}, addEventListener(name, fn) { this[name] = fn; }});
  return elements.get(selector);
}
let responses = [], calls = [], dialogs = [], uploaded = [], refreshes = 0;
class FakeFormData { constructor() { this.data = {}; } append(k,v) { this.data[k] = v; } delete(k) { delete this.data[k]; } }
const context = {$, state:{user:{id:'u'}, selected:new Map(), offset:0}, FormData:FakeFormData, TextDecoder, URLSearchParams, setTimeout,
  request:async (url, options) => { calls.push({url, body:JSON.parse(options.body)}); assert(responses.length, `unexpected ${url}`); return responses.shift(); },
  json:body => ({body:JSON.stringify(body)}), refresh:async () => { refreshes++; }, selectedDownloadFormats:() => ['csv'], CSV_EXPORT_VERSION:'audition-v2',
  formatDate:value => value, Option:function(text,value) {this.textContent=text;this.value=value;},
  document:{createElement() {return {click() {}};}}, fetch:async () => ({}), URL:{}, XMLHttpRequest:function(){}, showAccount() {}};
vm.runInNewContext(source.slice(start, stop), context);
context.fakeDialog = async (title, message, details) => { dialogs.push({title, message, details}); return context.confirm; };
context.fakeSend = async body => { uploaded.push(body.data); return {job_id:'test'}; };
context.fakeLoad = async id => { $('#filter-batch').value = id; };
vm.runInNewContext('uploadDialog = fakeDialog; sendJob = fakeSend; loadBatches = fakeLoad;', context);
function file(name, text) { return {name, arrayBuffer:async () => new TextEncoder().encode(text).buffer}; }
const form = {reset() { this.resetCount = (this.resetCount || 0) + 1; }};
const submit = () => $('#submit-form').submit({preventDefault(){}, currentTarget:form});
(async () => {
  context.setUploadMode('batch');
  $('#language').value = 'zh_cn';
  $('#batch-audio').files = [file('yes.wav',''), file('lonely.wav','')];
  $('#batch-text').files = [file('yes.txt','你好')];
  const pairing = {pairs:[{audio:'yes.wav',text:'yes.txt'}], unmatched_audio:['lonely.wav'], unmatched_text:[], duplicates:[]};
  responses.push(pairing); context.confirm = false; await submit();
  assert.equal(calls.length, 1); assert.equal(calls[0].url, '/v1/batches/check'); assert.equal(uploaded.length, 0);
  assert.match(dialogs[0].details, /lonely\.wav/); assert.match(dialogs[0].message, /不会上传/);
  calls = []; dialogs = []; context.confirm = true;
  responses.push(pairing, {status:'mismatch', message:'检测到英语'}, {batch_id:'batch123'});
  await submit();
  assert.deepEqual(calls.map(c => c.url), ['/v1/batches/check','/v1/language-check','/v1/batches']);
  assert.equal(calls[1].body.language, 'zh_cn'); assert.equal(calls[1].body.text, '你好');
  assert.equal(uploaded.length, 1); assert.equal(uploaded[0].audio.name, 'yes.wav'); assert.equal(uploaded[0].text_file.name, 'yes.txt'); assert.equal(uploaded[0].batch_id, 'batch123');
  assert.equal($('#filter-batch').value, 'batch123'); assert.equal(refreshes, 1); assert.equal(dialogs.length, 2);
  assert.match(dialogs[1].details, /yes\.txt：检测到英语/);
  uploaded = []; calls = []; dialogs = [];
  responses.push({pairs:[],unmatched_audio:['lonely.wav'],unmatched_text:[],duplicates:[]}); await submit();
  assert.equal(calls.length, 1); assert.equal(uploaded.length, 0); assert.match($('#submit-message').textContent, /没有可配对/);
  uploaded = []; calls = []; dialogs = [];
  $('#batch-audio').files = [file('yes.wav',''), file('bad.wav','')];
  $('#batch-text').files = [file('yes.txt','你好'), file('bad.txt','')];
  responses.push({pairs:[{audio:'yes.wav',text:'yes.txt'},{audio:'bad.wav',text:'bad.txt'}],unmatched_audio:[],unmatched_text:[],duplicates:[]}, {status:'match'}, {batch_id:'batch456'});
  await submit();
  assert.equal(uploaded.length, 1); assert.equal(uploaded[0].audio.name, 'yes.wav');
  assert.match(dialogs[0].details, /bad\.txt/); assert.match(dialogs[0].message, /不会上传/);
  assert.deepEqual(calls[2].body.audio_names, ['yes.wav']);
  uploaded = []; calls = []; dialogs = [];
  $('#batch-audio').files = [file('retry.wav','')]; $('#batch-text').files = [file('retry.txt','你好')];
  let attempts = 0;
  context.fakeSend = async body => { uploaded.push(body.data); if (++attempts === 1) throw new Error('网络中断'); return {job_id:'done'}; };
  vm.runInNewContext('sendJob = fakeSend;', context);
  responses.push({pairs:[{audio:'retry.wav',text:'retry.txt'}],unmatched_audio:[],unmatched_text:[],duplicates:[]}, {status:'match'}, {batch_id:'samebatch'});
  await submit(); assert.equal($('#batch-retry-actions').hidden, false);
  const priorCalls = calls.length; await submit(); assert.equal(calls.length, priorCalls);
  await $('#batch-retry').onclick();
  assert.equal(uploaded.length, 2); assert.equal(uploaded[0].batch_id, 'samebatch'); assert.equal(uploaded[1].batch_id, 'samebatch');
  assert.equal($('#batch-retry-actions').hidden, true);
  uploaded = []; calls = []; dialogs = []; context.confirm = false;
  context.setUploadMode('single'); $('#language').value = 'zh_cn'; $('#text').value = 'English text'; $('#text-file').files = [];
  responses.push({status:'mismatch',message:'检测到英语'}); await submit();
  assert.equal(calls[0].url, '/v1/language-check'); assert.equal(uploaded.length, 0); assert.match(dialogs[0].details, /检测到英语/);
  calls = []; $('#language').value = ''; await submit(); assert.equal(calls.length, 0); assert.match($('#submit-message').textContent, /语种/);
  console.log('batch upload UI tests passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
