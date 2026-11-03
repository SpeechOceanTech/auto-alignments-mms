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
  {code:'zh_cn', name:'中文（普通话）（中国大陆）', iso:'cmn', english:'Mandarin Chinese'},
  {code:'zh_tw', name:'中文（普通话）（中国台湾）', iso:'cmn', english:'Mandarin Chinese'},
  {code:'ct_hk', name:'粤语（中国香港，ct_hk）', iso:'yue', english:'Cantonese'},
  {code:'yue_hk', name:'粤语（中国香港，yue_hk）', iso:'yue', english:'Cantonese'},
  {code:'en_us', name:'英语（美国）', iso:'eng', english:'English'},
  {code:'ceb_ph', name:'宿务语（菲律宾）', iso:'ceb', english:'Cebuano'},
  {code:'ln_cd', name:'林加拉语（刚果（金））', iso:'lin', english:'Lingala', language_name:'林加拉语', region:'刚果（金）'},
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
assert.equal(choices().length, 7, 'focus displays every region even with a default value');
assert.equal(options.children.filter(child => child.className === 'language-group-heading').length, 5, 'regions are grouped by language');
assert.equal(options.children[0].children[0].textContent, '中文（普通话）');
assert.equal(choices()[0].children[0].textContent, '中国大陆');
assert.equal(choices()[2].children[0].textContent, '中国香港');
assert.equal(choices()[2].children[1].textContent, 'ct_hk');
assert.equal(choices()[6].children[0].textContent, '刚果（金）', 'regions with nested parentheses remain intact');
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
assert.equal(choices().length, 2, 'search matches both regions of a Chinese language name');
input.dispatchEvent({type:'keydown', key:'ArrowDown', preventDefault() {}});
assert.equal(choices()[0].attributes['aria-selected'], 'true', 'keyboard navigation skips group headings');
input.dispatchEvent({type:'keydown', key:'ArrowDown', preventDefault() {}});
input.dispatchEvent({type:'keydown', key:'Enter', preventDefault() {}});
assert.equal(input.value, 'zh_tw');
input.value = '宿务';
input.dispatchEvent({type:'input'});
assert.equal(choices().length, 1);
choices()[0].onclick();
assert.equal(input.value, 'ceb_ph');
console.log('language picker tests passed');
