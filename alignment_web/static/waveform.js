/* The server returns bounded min/max peaks; the canvas only draws the visible window. */
const WaveformMath = {
  clamp(value, min, max) { return Math.max(min, Math.min(max, value)); },
  zoomWindow(duration, zoom, position, nextZoom, anchor) {
    const oldSpan = duration / zoom, newSpan = duration / nextZoom;
    return WaveformMath.clamp(position + anchor * (oldSpan - newSpan), 0, Math.max(0, duration - newSpan));
  },
  activeSegment(segments, time) {
    // Sentence results are ordered; find the last start at or before the cursor.
    let low = 0, high = segments.length;
    while (low < high) { const mid = (low + high) >> 1; if (Number(segments[mid].start) <= time) low = mid + 1; else high = mid; }
    const index = low - 1;
    return index >= 0 && time < Number(segments[index].end) ? index : -1;
  },
};

class WaveformReview {
  constructor(canvas, audio) {
    Object.assign(this, {canvas, audio});
    this.duration = 0; this.peaks = []; this.segments = []; this.position = 0; this.zoom = 1;
    this.onSeek = () => {};
    canvas.addEventListener('wheel', event => { event.preventDefault(); const rect = canvas.getBoundingClientRect(); this.setZoom(this.zoom + (event.deltaY < 0 ? 1 : -1), WaveformMath.clamp((event.clientX - rect.left) / rect.width, 0, 1)); }, {passive:false});
    canvas.addEventListener('pointerdown', event => { if (event.button !== 0 || !this.duration) return; this.drag = {x:event.clientX, position:this.position, moved:false}; canvas.setPointerCapture(event.pointerId); });
    canvas.addEventListener('pointermove', event => { if (!this.drag) return; const dx = event.clientX - this.drag.x; if (Math.abs(dx) > 3) this.drag.moved = true; if (this.drag.moved) { this.position = WaveformMath.clamp(this.drag.position - dx / canvas.clientWidth * this.duration / this.zoom, 0, this.duration - this.duration / this.zoom); this.draw(); } });
    canvas.addEventListener('pointerup', event => { if (!this.drag) return; const moved = this.drag.moved; this.drag = null; if (!moved && this.duration) { const rect = canvas.getBoundingClientRect(); this.onSeek(WaveformMath.clamp(this.position + (event.clientX - rect.left) / rect.width * this.duration / this.zoom, 0, this.duration)); } });
    canvas.addEventListener('pointercancel', () => { this.drag = null; });
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => this.draw()).observe(canvas);
    else window.addEventListener('resize', () => this.draw());
  }
  reset() { this.duration = 0; this.peaks = []; this.segments = []; this.position = 0; this.zoom = 1; this.draw(); }
  setData(data) { this.duration = Number(data.duration) || 0; this.peaks = Array.isArray(data.peaks) ? data.peaks : []; this.draw(); }
  setSegments(segments) { this.segments = segments; this.draw(); }
  setZoom(zoom, anchor) { if (!this.duration) return; const next = WaveformMath.clamp(Math.round(zoom), 1, 48); this.position = WaveformMath.zoomWindow(this.duration, this.zoom, this.position, next, anchor); this.zoom = next; this.draw(); }
  showTime(time) { if (!this.duration || this.audio.paused) return; const span = this.duration / this.zoom; if (time < this.position || time > this.position + span) this.position = WaveformMath.clamp(time - span * .35, 0, this.duration - span); }
  draw() {
    const rect = this.canvas.getBoundingClientRect(); if (!rect.width) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2), width = Math.max(1, Math.round(rect.width * ratio)), height = Math.max(1, Math.round(rect.height * ratio));
    if (this.canvas.width !== width) this.canvas.width = width; if (this.canvas.height !== height) this.canvas.height = height;
    const ctx = this.canvas.getContext('2d'); if (!ctx) return;
    ctx.clearRect(0, 0, width, height); ctx.fillStyle = '#fbfcfe'; ctx.fillRect(0, 0, width, height);
    if (!this.duration || !this.peaks.length) return;
    const span = this.duration / this.zoom, end = this.position + span;
    this.segments.forEach((segment, index) => { const start = Math.max(this.position, Number(segment.start)), stop = Math.min(end, Number(segment.end)); if (stop <= start) return; ctx.fillStyle = index % 2 ? 'rgba(180,84,8,.16)' : 'rgba(17,109,110,.18)'; ctx.fillRect((start - this.position) / span * width, 0, (stop - start) / span * width, height); });
    ctx.strokeStyle = '#475467'; ctx.lineWidth = Math.max(1, ratio); ctx.beginPath();
    for (let x = 0; x < width; x++) { const first = Math.floor((this.position + x / width * span) / this.duration * this.peaks.length), last = Math.min(this.peaks.length - 1, Math.floor((this.position + (x + 1) / width * span) / this.duration * this.peaks.length)); let min = 1, max = -1; for (let i = first; i <= last; i++) { const peak = this.peaks[i]; if (peak) { min = Math.min(min, peak[0]); max = Math.max(max, peak[1]); } } if (max >= min) { ctx.moveTo(x, (1 - max) * height / 2); ctx.lineTo(x, (1 - min) * height / 2); } }
    ctx.stroke(); const current = this.audio.currentTime; if (current >= this.position && current <= end) { const x = (current - this.position) / span * width; ctx.strokeStyle = '#b42318'; ctx.lineWidth = 2 * ratio; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke(); }
  }
}
if (typeof module !== 'undefined') module.exports = {WaveformMath, WaveformReview};
