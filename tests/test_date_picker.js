// Run with node tests/test_date_picker.js.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
process.env.TZ = 'America/Los_Angeles';

class Element {
  constructor(id) { this.id = id; this.value = ''; this.hidden = id === 'date-picker'; this.style = {}; this.attrs = {}; this.handlers = {}; this.innerHTML = ''; this.textContent = ''; }
  addEventListener(name, fn) { (this.handlers[name] ||= []).push(fn); }
  dispatchEvent(event) { for (const fn of this.handlers[event.type] || []) fn(event); }
  fire(type, event = {}) { if (type === 'click' && this.onclick) this.onclick(event); this.dispatchEvent({type, ...event}); }
  setAttribute(name, value) { this.attrs[name] = value; }
  getBoundingClientRect() { return this.id === 'date-picker' ? {width:300, height:300} : {left:180, top:300, bottom:330}; }
  querySelector(selector) { return {focus() { Element.focused = selector; }}; }
  focus() { Element.focused = this.id; }
}
const nodes = {};
const document = {getElementById(id) { return nodes[id] ||= new Element(id); }, addEventListener(name, fn) { this[name] = fn; }};
const window = {innerWidth:400, innerHeight:500, addEventListener() {}};
const state = {limit:20, offset:40, selected:new Map([['old', true]]), user:{is_admin:true}};
let refreshes = 0;
const context = {document, window, state, URLSearchParams, Event: class {constructor(type) {this.type = type;}},
  $: selector => document.getElementById(selector.slice(1)), refresh() { refreshes++; },
  setTimeout(fn) { fn(); return 1; }, clearTimeout() {}};
const app = fs.readFileSync('alignment_web/static/app.js', 'utf8');
const filtersStart = app.indexOf('function filters()');
const filtersEnd = app.indexOf('function updateSelection()', filtersStart);
const eventsStart = app.indexOf('let filterTimer;');
const eventsEnd = app.indexOf('const reviewAudio', eventsStart);
assert(filtersStart >= 0 && filtersEnd > filtersStart && eventsStart >= 0 && eventsEnd > eventsStart);
vm.runInNewContext(app.slice(filtersStart, filtersEnd) + app.slice(eventsStart, eventsEnd), context);
vm.runInNewContext(fs.readFileSync('alignment_web/static/date-picker.js', 'utf8'), context);

const picker = nodes['date-picker'], days = nodes['date-picker-days'];
nodes['filter-from'].value = '2024-02-29';
nodes['date-from-trigger'].fire('click');
assert.equal(picker.hidden, false);
assert.equal(nodes['date-picker-year'].value, '2024');
assert.equal(nodes['date-picker-month'].value, '1');
assert.match(days.innerHTML, /data-date="2024-02-29"/);
assert.equal(picker.style.left, '88px');
assert.equal(picker.style.top, '12px');
nodes['date-picker-prev'].fire('click');
assert.match(days.innerHTML, /data-date="2024-01-31"/);
nodes['date-picker-prev'].fire('click');
assert.equal(nodes['date-picker-year'].value, '2023');
days.fire('keydown', {key:'ArrowRight', preventDefault(){}, target:{closest(){return {dataset:{date:'2023-12-31'}};}}});
assert.equal(nodes['date-picker-year'].value, '2024');
assert.equal(nodes['date-picker-month'].value, '0');
assert.equal(Element.focused, '[data-date="2024-01-01"]');
nodes['date-picker-year'].fire('change', {target:{value:'2020'}});
nodes['date-picker-month'].fire('change', {target:{value:'1'}});
assert.match(days.innerHTML, /data-date="2020-02-29"/);
days.fire('click', {target:{closest(){return {dataset:{date:'2020-02-29'}};}}});
assert.equal(nodes['filter-from'].value, '2020-02-29');
assert.equal(nodes['date-from-trigger'].textContent, '2020-02-29');
assert.equal(state.offset, 0);
assert.equal(state.selected.size, 0);
assert.equal(refreshes, 1);
assert.equal(context.filters().get('created_from'), '2020-02-29');
nodes['date-from-trigger'].fire('click');
nodes['date-picker-clear'].fire('click');
assert.equal(nodes['filter-from'].value, '');
assert.equal(nodes['date-from-trigger'].textContent, '开始日期');
assert.equal(context.filters().has('created_from'), false);
nodes['date-to-trigger'].fire('click');
days.fire('click', {target:{closest(){return {dataset:{date:'2020-02-29'}};}}});
assert.equal(context.filters().get('created_to'), '2020-02-29');
nodes['clear-filters'].fire('click');
assert.equal(nodes['filter-from'].value, '');
assert.equal(nodes['filter-to'].value, '');
assert.equal(nodes['date-from-trigger'].textContent, '开始日期');
assert.equal(nodes['date-to-trigger'].textContent, '结束日期');
assert.equal(context.filters().has('created_from'), false);
nodes['date-from-trigger'].fire('click');
nodes['date-to-trigger'].fire('click');
assert.equal(nodes['date-from-trigger'].attrs['aria-expanded'], 'false');
assert.equal(nodes['date-to-trigger'].attrs['aria-expanded'], 'true');
document.keydown({key:'Escape', preventDefault(){}});
assert.equal(picker.hidden, true);
assert.equal(Element.focused, 'date-to-trigger');
nodes['date-to-trigger'].fire('click');
document.pointerdown({target:{closest(){return null;}}});
assert.equal(picker.hidden, true);
console.log('date picker and job filters tests passed');
