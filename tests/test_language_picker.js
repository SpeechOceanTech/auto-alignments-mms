// Run with node tests/test_language_picker.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(text, cls) { this.listeners = {}; this.children = []; this.attributes = {}; this.hidden = true; this.value = ''; this.textContent = text; this.className = cls; }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  dispatchEvent(event) { this.listeners[event.type]?.(event); }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  querySelectorAll(selector) { return selector === '[role=option]' ? this.children.filter(child => child.attributes.role === 'option') : []; }
  scrollIntoView() {}
  select() { this.selected = true; }
}

const input = new Element(), options = new Element();
input.value = 'zh_cn';
const languageChoices = [
  {code:'zh_cn', name:'普通话', iso:'cmn', english:'Mandarin Chinese', aliases:['中文']},
  {code:'zh_tw', name:'台湾普通话', iso:'cmn', english:'Taiwanese Mandarin', aliases:['中文']},
  {code:'ar_eg', name:'埃及阿拉伯语', iso:'arz', english:'Egyptian Arabic', aliases:['阿拉伯语']},
  {code:'ar_msa', name:'标准阿拉伯语', iso:'arb', english:'Standard Arabic', aliases:['阿拉伯语']},
  {code:'en_us', name:'美式英语', iso:'eng', english:'American English'},
  {code:'ceb_ph', name:'宿务语', iso:'ceb', english:'Cebuano'},
];
const source = fs.readFileSync('alignment_web/static/app.js', 'utf8');
const start = source.indexOf('function setupLanguagePicker(');
const end = source.indexOf("setupLanguagePicker('#language'", start);
assert(start >= 0 && end > start);
const context = {languageChoices, $: id => id === '#language' ? input : options,
  node: (_tag, text, cls) => new Element(text, cls), Event: class { constructor(type) { this.type = type; } }};
vm.runInNewContext(source.slice(start, end) + "\nsetupLanguagePicker('#language', '#options');", context);
const choices = () => options.querySelectorAll('[role=option]');

input.dispatchEvent({type:'focus'});
assert.equal(choices().length, 6, 'focus displays every language even with a default value');
assert.equal(options.children.length, choices().length, 'languages are shown directly without region groups');
assert.equal(choices()[0].children[0].textContent, 'zh_cn');
assert.equal(choices()[0].children[1].textContent, '普通话');
assert.equal(choices()[2].children[0].textContent, 'ar_eg');
assert.equal(choices()[2].children[1].textContent, '埃及阿拉伯语');
assert.equal(input.value, 'zh_cn');
assert.equal(input.selected, true);
input.value = 'en-US';
input.dispatchEvent({type:'input'});
assert.equal(choices().length, 1, 'a locale with hyphen matches the underscore code');
choices()[0].onclick();
assert.equal(input.value, 'en_us');
assert.equal(options.hidden, true);
input.value = '中文';
input.dispatchEvent({type:'input'});
assert.equal(choices().length, 2, 'search matches Chinese language aliases');
input.dispatchEvent({type:'keydown', key:'ArrowDown', preventDefault() {}});
assert.equal(choices()[0].attributes['aria-selected'], 'true', 'keyboard navigation highlights the first match');
input.dispatchEvent({type:'keydown', key:'ArrowDown', preventDefault() {}});
input.dispatchEvent({type:'keydown', key:'Enter', preventDefault() {}});
assert.equal(input.value, 'zh_tw');
input.value = '阿拉伯';
input.dispatchEvent({type:'input'});
assert.deepEqual(choices().map(choice => choice.children[1].textContent), ['埃及阿拉伯语', '标准阿拉伯语']);
input.value = 'Egyptian';
input.dispatchEvent({type:'input'});
assert.equal(choices().length, 1, 'English names remain searchable');
assert.equal(choices()[0].children[1].textContent, '埃及阿拉伯语');
input.value = '宿务';
input.dispatchEvent({type:'input'});
assert.equal(choices().length, 1);
choices()[0].onclick();
assert.equal(input.value, 'ceb_ph');
console.log('language picker tests passed');
