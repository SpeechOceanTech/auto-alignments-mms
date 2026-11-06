// Run with node tests/test_batch_upload.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('alignment_web/static/index.html', 'utf8');
assert.match(html, /id="language" name="language" required/);
assert.doesNotMatch(html, /id="language"[^>]*value="zh_cn"/);
assert.match(html, /id="batch-files"[^>]*multiple[^>]*required[^>]*accept="[^"]*\.wav[^"]*\.txt/);
assert.doesNotMatch(html, /id="(?:mode-single|mode-batch|text|text-file|batch-audio|batch-text)"/);
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
let responses = [], prechecks = [], calls = [], dialogs = [], uploaded = [], refreshes = 0, lengthDialogs = [];
class FakeFormData { constructor() { this.data = {}; } append(k,v) { this.data[k] = v; } delete(k) { delete this.data[k]; } }
const context = {$, state:{user:{id:'u'}, selected:new Map(), offset:0}, FormData:FakeFormData, TextDecoder, URLSearchParams, setTimeout,
  request:async (url, options) => { calls.push({url, body:JSON.parse(options.body)}); if (url === '/v1/alignment-precheck') return prechecks.shift() || {status:'ok'}; assert(responses.length, `unexpected ${url}`); return responses.shift(); },
  json:body => ({body:JSON.stringify(body)}), refresh:async () => { refreshes++; }, selectedDownloadFormats:() => ['csv'], CSV_EXPORT_VERSION:'audition-v2',
  formatDate:value => value, Option:function(text,value) {this.textContent=text;this.value=value;},
  document:{createElement() {return {click() {}};}}, fetch:async () => ({}), URL:{}, XMLHttpRequest:function(){}, showAccount() {}};
vm.runInNewContext(source.slice(start, stop), context);
context.fakeDialog = async (title, message, details) => { dialogs.push({title, message, details}); return context.confirm; };
context.fakeSend = async body => { uploaded.push(body.data); return {job_id:'test'}; };
context.fakeLoad = async id => { $('#filter-batch').value = id; };
context.fakeDuration = async () => 60;
context.fakeReview = async warnings => { lengthDialogs.push(warnings); return context.skipped; };
vm.runInNewContext('uploadDialog = fakeDialog; sendJob = fakeSend; loadBatches = fakeLoad; readAudioDuration = fakeDuration; reviewPrecheckWarnings = fakeReview;', context);
function file(name, text) { return {name, arrayBuffer:async () => new TextEncoder().encode(text).buffer}; }
const form = {reset() { this.resetCount = (this.resetCount || 0) + 1; }};
const submit = () => $('#submit-form').submit({preventDefault(){}, currentTarget:form});
(async () => {
  $('#language').value = 'zh_cn';
  $('#batch-files').files = [file('yes.wav',''), file('lonely.wav',''), file('yes.txt','你好'), file('ignore.pdf','')];
  $('#batch-files').onchange(); assert.match($('#batch-files-count').textContent, /2 个音频、1 个文本，1 个其他/);
  const pairing = {pairs:[{audio:'yes.wav',text:'yes.txt'}], unmatched_audio:['lonely.wav'], unmatched_text:[], duplicates:[]};
  responses.push(pairing); context.confirm = false; await submit();
  assert.equal(calls.length, 1); assert.equal(calls[0].url, '/v1/batches/check'); assert.equal(uploaded.length, 0);
  assert.match(dialogs[0].details, /lonely\.wav/); assert.match(dialogs[0].details, /ignore\.pdf/); assert.match(dialogs[0].message, /不会上传/);
  assert.deepEqual(calls[0].body, {audio_names:['yes.wav','lonely.wav'], text_names:['yes.txt']});
  calls = []; dialogs = []; context.confirm = true;
  responses.push(pairing, {status:'mismatch', message:'检测到英语'}, {batch_id:'batch123'});
  await submit();
  assert.deepEqual(calls.map(c => c.url), ['/v1/batches/check','/v1/language-check','/v1/alignment-precheck','/v1/batches']);
  assert.equal(calls[1].body.language, 'zh_cn'); assert.equal(calls[1].body.text, '你好');
  assert.equal(calls[2].body.duration_seconds, 60);
  assert.equal(uploaded.length, 1); assert.equal(uploaded[0].audio.name, 'yes.wav'); assert.equal(uploaded[0].text_file.name, 'yes.txt'); assert.equal(uploaded[0].batch_id, 'batch123');
  assert.equal($('#filter-batch').value, 'batch123'); assert.equal(refreshes, 1); assert.equal(dialogs.length, 2);
  assert.match(dialogs[1].details, /yes\.txt：检测到英语/);
  uploaded = []; calls = []; dialogs = [];
  responses.push({pairs:[],unmatched_audio:['lonely.wav'],unmatched_text:[],duplicates:[]}); await submit();
  assert.equal(calls.length, 1); assert.equal(uploaded.length, 0); assert.match($('#submit-message').textContent, /没有可配对/);
  uploaded = []; calls = []; dialogs = [];
  $('#batch-files').files = [file('yes.wav',''), file('bad.wav',''), file('yes.txt','你好'), file('bad.txt','')];
  responses.push({pairs:[{audio:'yes.wav',text:'yes.txt'},{audio:'bad.wav',text:'bad.txt'}],unmatched_audio:[],unmatched_text:[],duplicates:[]}, {status:'match'}, {batch_id:'batch456'});
  await submit();
  assert.equal(uploaded.length, 1); assert.equal(uploaded[0].audio.name, 'yes.wav');
  assert.match(dialogs[0].details, /bad\.txt/); assert.match(dialogs[0].message, /不会上传/);
  assert.deepEqual(calls.find(call => call.url === '/v1/batches').body.audio_names, ['yes.wav']);
  uploaded = []; calls = []; dialogs = [];
  $('#batch-files').files = [file('retry.WAV',''), file('retry.TXT','你好')];
  let attempts = 0;
  context.fakeSend = async body => { uploaded.push(body.data); if (++attempts === 1) throw new Error('网络中断'); return {job_id:'done'}; };
  vm.runInNewContext('sendJob = fakeSend;', context);
  responses.push({pairs:[{audio:'retry.WAV',text:'retry.TXT'}],unmatched_audio:[],unmatched_text:[],duplicates:[]}, {status:'match'}, {batch_id:'samebatch'});
  await submit(); assert.equal($('#batch-retry-actions').hidden, false);
  const priorCalls = calls.length; await submit(); assert.equal(calls.length, priorCalls);
  await $('#batch-retry').onclick();
  assert.equal(uploaded.length, 2); assert.equal(uploaded[0].batch_id, 'samebatch'); assert.equal(uploaded[1].batch_id, 'samebatch');
  assert.equal($('#batch-retry-actions').hidden, true);
  uploaded = []; calls = []; dialogs = []; context.confirm = false;
  $('#batch-files').files = [file('english.mp3',''), file('english.txt','English text')];
  responses.push({pairs:[{audio:'english.mp3',text:'english.txt'}],unmatched_audio:[],unmatched_text:[],duplicates:[]}, {status:'mismatch',message:'检测到英语'}); await submit();
  assert.equal(calls[1].url, '/v1/language-check'); assert.equal(uploaded.length, 0); assert.match(dialogs[0].details, /检测到英语/);
  uploaded = []; calls = []; dialogs = []; lengthDialogs = []; context.confirm = true; context.skipped = new Set(['bad.wav']);
  $('#batch-files').files = [file('good.wav',''), file('bad.wav',''), file('good.txt','正常文本'), file('bad.txt','很长的文本')];
  responses.push({pairs:[{audio:'good.wav',text:'good.txt'},{audio:'bad.wav',text:'bad.txt'}],unmatched_audio:[],unmatched_text:[],duplicates:[]}, {status:'match'}, {status:'match'}, {batch_id:'selected'});
  prechecks.push({status:'ok'}, {status:'warning',message:'文本可能过长'});
  await submit();
  assert.equal(lengthDialogs.length, 1); assert.equal(lengthDialogs[0][0].pair.audio, 'bad.wav');
  assert.deepEqual(calls.find(call => call.url === '/v1/batches').body.audio_names, ['good.wav']);
  assert.equal(uploaded.length, 1); assert.equal(uploaded[0].audio.name, 'good.wav');
  uploaded = []; calls = []; lengthDialogs = []; context.skipped = null;
  $('#batch-files').files = [file('bad.wav',''), file('bad.txt','很长的文本')];
  responses.push({pairs:[{audio:'bad.wav',text:'bad.txt'}],unmatched_audio:[],unmatched_text:[],duplicates:[]}, {status:'match'});
  prechecks.push({status:'unknown',message:'无法检查'});
  await submit(); assert.equal(uploaded.length, 0); assert(!calls.some(call => call.url === '/v1/batches')); assert.equal(lengthDialogs[0][0].result.status, 'unknown');
  calls = []; $('#language').value = ''; await submit(); assert.equal(calls.length, 0); assert.match($('#submit-message').textContent, /语种/);
  console.log('batch upload UI tests passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
