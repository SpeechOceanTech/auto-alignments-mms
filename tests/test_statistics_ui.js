// Run with node tests/test_statistics_ui.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag, text = '', cls = '') { this.tag = tag; this.textContent = text; this.className = cls; this.children = []; this.style = {}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
}
const elements = new Map();
function $(name) { if (!elements.has(name)) elements.set(name, new Element('div')); return elements.get(name); }
const state = {user:{id:'admin', is_admin:true}};
let calls = 0;
const payload = {totals:{completed:3, language_count:2, audio_seconds:5400, audio_duration_sample_count:2, sentence_count:45, sentence_sample_count:1},current:{queued:1,running:0,completed:2,failed:1},languages:[{language:'zh_cn',jobs:2,audio_seconds:5400,audio_duration_sample_count:2,sentence_count:45,sentence_sample_count:1},{language:'es_mx',jobs:1,audio_seconds:0,audio_duration_sample_count:0,sentence_count:0,sentence_sample_count:0}],users:[]};
const context = {$, state, languageChoices:[{code:'zh_cn', name:'中文'}], node:(...args) => new Element(...args), document:{createTextNode:text => new Element('#text',text)}, request:async url => { calls++; assert.equal(url,'/api/admin/usage'); return payload; }};
const source = fs.readFileSync('alignment_web/static/app.js','utf8');
const start = source.indexOf('const statsNumber ='), end = source.indexOf("$('#refresh-statistics').onclick",start);
assert(start >= 0 && end > start); vm.runInNewContext(source.slice(start,end),context);
(async () => {
  await context.loadStatistics();
  const cards = $('#stats-summary').children;
  assert.equal(cards.length,4); assert.equal(cards[1].children[1].children[0].textContent,'1.50');
  assert.match($('#stats-coverage').textContent,/1 个任务缺少音频时长，2 个任务缺少句数/);
  const rows = $('#stats-languages').children[0].children[1].children;
  assert.equal(rows[0].children[0].textContent,'中文');
  assert.equal(rows[0].children[3].textContent,'45 *');
  assert.equal(rows[0].children[4].children[1].textContent,'66.7%');
  assert.equal(rows[1].children[2].textContent,'—');
  assert.equal($('#stats-users').children[0].textContent,'暂无已完成任务');
  state.user = {id:'ordinary',is_admin:false}; await context.loadStatistics(); assert.equal(calls,1);
  console.log('statistics UI tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
