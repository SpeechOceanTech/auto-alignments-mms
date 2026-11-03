// Run with node tests/test_language_picker.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor() { this.listeners = {}; this.children = []; this.attributes = {}; this.hidden = true; this.value = ''; }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  dispatchEvent(event) { this.listeners[event.type]?.(event); }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  querySelectorAll() { return this.children; }
  scrollIntoView() {}
  select() { this.selected = true; }
}

const input = new Element(), options = new Element();
input.value = 'zh_cn';
const languageChoices = [
  {code:'zh_cn', name:'中文（中国大陆）', iso:'cmn', english:'Mandarin Chinese'},
  {code:'en_us', name:'英语（美国）', iso:'eng', english:'English'},
  {code:'ceb_ph', name:'宿务语（菲律宾）', iso:'ceb', english:'Cebuano'},
];
const source = fs.readFileSync('alignment_web/static/app.js', 'utf8');
const start = source.indexOf('function setupLanguagePicker(');
const end = source.indexOf("setupLanguagePicker('#language'", start);
assert(start >= 0 && end > start);
const context = {languageChoices, $: id => id === '#language' ? input : options,
  node: () => new Element(), Event: class { constructor(type) { this.type = type; } }};
vm.runInNewContext(source.slice(start, end) + "\nsetupLanguagePicker('#language', '#options');", context);

input.dispatchEvent({type:'focus'});
assert.equal(options.children.length, 3, 'focus displays all choices even with the default value');
assert.equal(input.value, 'zh_cn');
assert.equal(input.selected, true);
input.value = 'en-US';
input.dispatchEvent({type:'input'});
assert.equal(options.children.length, 1, 'a locale with hyphen matches the underscore code');
options.children[0].onclick();
assert.equal(input.value, 'en_us');
assert.equal(options.hidden, true);
input.value = '宿务';
input.dispatchEvent({type:'input'});
assert.equal(options.children.length, 1, 'search matches a Chinese language name');
options.children[0].onclick();
assert.equal(input.value, 'ceb_ph');
console.log('language picker tests passed');
