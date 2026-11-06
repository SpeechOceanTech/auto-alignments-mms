// Run with node tests/test_audio_duration.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('alignment_web/static/app.js', 'utf8');
const start = source.indexOf('function readAudioDuration('), end = source.indexOf('function reviewPrecheckWarnings(', start);
assert(start >= 0 && end > start);
let value = 1515.6, fail = false, revoked = [];
class Audio {
  set src(url) { this.url = url; queueMicrotask(() => fail ? this.onerror() : this.onloadedmetadata()); }
  get duration() { return value; }
  removeAttribute(name) { assert.equal(name, 'src'); }
}
const context = {Audio, URL:{createObjectURL:() => 'blob:test', revokeObjectURL:url => revoked.push(url)}, setTimeout, clearTimeout};
vm.runInNewContext(source.slice(start, end), context);
(async () => {
  assert.equal(await context.readAudioDuration({}), 1515.6);
  value = Infinity; assert.equal(await context.readAudioDuration({}), null);
  fail = true; assert.equal(await context.readAudioDuration({}), null);
  assert.deepEqual(revoked, ['blob:test', 'blob:test', 'blob:test']);
  console.log('audio metadata tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
