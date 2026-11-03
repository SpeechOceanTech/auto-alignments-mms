// Run with node tests/test_waveform.js.
const assert = require('node:assert/strict');
const {WaveformMath, WaveformReview} = require('../alignment_web/static/waveform.js');
assert.equal(WaveformMath.zoomWindow(100, 1, 0, 2, .25), 12.5, 'zoom keeps cursor time fixed');
assert.equal(WaveformMath.zoomWindow(100, 2, 50, 1, .5), 0, 'zoom out stays within the recording');
const segments = [{start:0,end:2}, {start:3,end:6}, {start:8,end:10}];
assert.equal(WaveformMath.activeSegment(segments, 0), 0);
assert.equal(WaveformMath.activeSegment(segments, 2), -1, 'silence does not highlight a sentence');
assert.equal(WaveformMath.activeSegment(segments, 3), 1);
assert.equal(WaveformMath.activeSegment(segments, 10), -1);
class Element {
  constructor() { this.events = {}; this.clientWidth = 500; this.value = 1; this.textContent = ''; }
  addEventListener(name, cb) { this.events[name] = cb; }
  getBoundingClientRect() { return {left:100,width:500,height:120}; }
  getContext() { return {clearRect(){},fillRect(){},beginPath(){},moveTo(){},lineTo(){},stroke(){}}; }
  setPointerCapture() {}
}
global.window = {devicePixelRatio:1,addEventListener(){}};
const canvas = new Element(), audio = {currentTime:0,paused:true};
const wave = new WaveformReview(canvas, audio);
wave.setData({duration:100, peaks:Array.from({length:100}, () => [-.5,.5])});
wave.setSegments(segments);
canvas.events.wheel({preventDefault(){}, clientX:225, deltaY:-1});
assert.equal(wave.zoom, 2); assert.equal(wave.position, 12.5); assert.equal(canvas.height, 120);
let seek = null; wave.onSeek = time => { seek = time; };
canvas.events.pointerdown({button:0,clientX:350,pointerId:1});
canvas.events.pointerup({clientX:350});
assert.equal(seek, 37.5, 'click maps to the visible timeline');
canvas.events.pointerdown({button:0,clientX:300,pointerId:1});
canvas.events.pointermove({clientX:200}); canvas.events.pointerup({clientX:200});
assert.equal(wave.position, 22.5, 'drag pans without seeking'); assert.equal(seek, 37.5);
audio.currentTime = 90; audio.paused = false; wave.showTime(90);
assert.equal(wave.position, 50, 'playing cursor scrolls into view without passing the end');
wave.reset(); assert.equal(wave.duration, 0); assert.equal(wave.zoom, 1);
console.log('waveform tests passed');
