/* Discrete X/Y grid picker. Activation sends one request; the highlighted
   cell changes only when the application confirms a selection. */
(() => {
  const choices = list => list.map(o => typeof o === 'string' ? {value: o, label: o} : {value: o.value, label: o.label ?? o.value});
  const cellDefaults = {enabled: true, busy: false, reason: '', label: ''};
  let instances = 0;

  class RtplotGridPicker {
    constructor(el, request) {
      this.el = el; this.request = request;
      this.xs = choices(el.x_options); this.ys = choices(el.y_options);
      this.state = {}; this.pending = null; this.controlDisabled = false; this.controlReasonId = null;
      this.focused = null;
      const uid = `grid-picker-${instances++}`;
      this.node = document.createElement('div'); this.node.className = 'grid-picker';
      this.node.setAttribute('role', 'group'); this.node.setAttribute('aria-label', el.label || el.id);
      if (el.label) {
        const title = document.createElement('div'); title.className = 'grid-title'; title.textContent = el.label;
        this.node.appendChild(title);
      }
      const axes = document.createElement('div'); axes.className = 'grid-axes';
      const xAxis = document.createElement('span'); xAxis.textContent = `${el.x_label || 'X'} → (columns)`;
      const yAxis = document.createElement('span'); yAxis.textContent = `${el.y_label || 'Y'} ↑ (rows)`;
      axes.append(xAxis, yAxis); this.node.appendChild(axes);
      const scroll = document.createElement('div'); scroll.className = 'grid-scroll'; this.node.appendChild(scroll);
      this.table = document.createElement('div'); this.table.className = 'grid-cells';
      this.table.style.setProperty('--grid-columns', this.xs.length); scroll.appendChild(this.table);
      this.table.appendChild(document.createElement('span'));
      this.xs.forEach(x => {
        const head = document.createElement('span'); head.className = 'grid-col-label'; head.textContent = x.label;
        this.table.appendChild(head);
      });
      this.cells = new Map();
      // y_options[0] is the bottom row, so rows are emitted from the last option down.
      [...this.ys].reverse().forEach(y => {
        const rowLabel = document.createElement('span'); rowLabel.className = 'grid-row-label'; rowLabel.textContent = y.label;
        this.table.appendChild(rowLabel);
        this.xs.forEach(x => {
          const button = document.createElement('button'); button.type = 'button'; button.className = 'grid-cell';
          button.dataset.x = x.value; button.dataset.y = y.value;
          const label = document.createElement('span'); label.className = 'grid-cell-label';
          const mark = document.createElement('span'); mark.className = 'grid-cell-state';
          const reason = document.createElement('span'); reason.className = 'grid-cell-reason';
          reason.id = `${uid}-${this.cells.size}`;
          button.append(label, mark, reason);
          button.addEventListener('click', () => this.activate(x.value, y.value));
          button.addEventListener('focus', () => { this.focused = this.key(x.value, y.value); this.roving(); });
          this.table.appendChild(button);
          this.cells.set(this.key(x.value, y.value), {button, label, mark, reason, x, y});
        });
      });
      this.table.addEventListener('keydown', e => this.keydown(e));
      this.status = document.createElement('p'); this.status.className = 'grid-status'; this.status.setAttribute('role', 'status');
      this.message = document.createElement('p'); this.message.className = 'grid-message';
      this.node.append(this.status, this.message);
      this.render();
    }
    key(x, y) { return JSON.stringify([x, y]); }
    confirmed() {
      const value = this.state.value || this.el.value || {x: this.xs[0].value, y: this.ys[0].value};
      return {...value, active: this.state.active ?? this.el.active ?? true};
    }
    cell(x, y) { return {...cellDefaults, ...(this.state.cells?.[x]?.[y] || {})}; }
    blocked(x, y) { return this.controlDisabled || !this.cell(x, y).enabled; }
    activate(x, y) {
      // Focus and hover never send; disabled cells remain focusable to expose reasons.
      if (this.blocked(x, y)) return;
      this.request(x, y);
    }
    keydown(e) {
      const moves = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1]};
      const cell = this.cells.get(this.focused);
      if (!cell || !(e.key in moves || e.key === 'Home' || e.key === 'End')) return;
      e.preventDefault();
      let xi = this.xs.findIndex(x => x.value === cell.x.value), yi = this.ys.findIndex(y => y.value === cell.y.value);
      if (e.key === 'Home') xi = 0;
      else if (e.key === 'End') xi = this.xs.length - 1;
      else { xi += moves[e.key][0]; yi += moves[e.key][1]; }
      xi = Math.max(0, Math.min(this.xs.length - 1, xi)); yi = Math.max(0, Math.min(this.ys.length - 1, yi));
      this.cells.get(this.key(this.xs[xi].value, this.ys[yi].value)).button.focus();
    }
    roving() {
      const c = this.confirmed();
      const current = this.cells.has(this.focused) ? this.focused : this.key(c.x, c.y);
      this.cells.forEach((cell, key) => { cell.button.tabIndex = key === current ? 0 : -1; });
    }
    update(state, controlDisabled, controlReasonId) {
      this.state = state || {}; this.controlDisabled = controlDisabled; this.controlReasonId = controlReasonId;
      this.render();
    }
    setPending(pending) { this.pending = pending || null; this.render(); }
    label(axis, value) { return (axis === 'x' ? this.xs : this.ys).find(o => o.value === value)?.label ?? value; }
    render() {
      const c = this.confirmed(), p = this.pending;
      const xName = this.el.x_label || 'X', yName = this.el.y_label || 'Y';
      this.cells.forEach(cell => {
        const x = cell.x.value, y = cell.y.value, o = this.cell(x, y);
        const isConfirmed = c.x === x && c.y === y, active = isConfirmed && c.active;
        const remembered = isConfirmed && !c.active, pending = Boolean(p && p.x === x && p.y === y);
        const marks = [];
        if (active) marks.push('✓ Active');
        if (remembered) marks.push('○ Remembered');
        if (pending) marks.push('◌ Requested');
        if (o.busy) marks.push('◌ Busy');
        const b = cell.button;
        b.classList.toggle('active', active); b.classList.toggle('remembered', remembered);
        b.classList.toggle('pending', pending); b.classList.toggle('unavailable', !o.enabled);
        b.disabled = this.controlDisabled;
        b.setAttribute('aria-pressed', String(active));
        b.setAttribute('aria-disabled', String(this.blocked(x, y)));
        b.setAttribute('aria-busy', String(o.busy));
        cell.label.textContent = o.label; cell.label.hidden = !o.label;
        cell.mark.textContent = marks.join(' · '); cell.mark.hidden = !marks.length;
        cell.reason.textContent = o.reason; cell.reason.hidden = !o.reason;
        b.setAttribute('aria-label', [`${xName} ${cell.x.label}, ${yName} ${cell.y.label}`, o.label,
          o.enabled ? '' : 'unavailable', ...marks.map(m => m.slice(2))].filter(Boolean).join('. '));
        const described = [o.reason ? cell.reason.id : null, this.controlDisabled ? this.controlReasonId : null].filter(Boolean);
        if (described.length) b.setAttribute('aria-describedby', described.join(' ')); else b.removeAttribute('aria-describedby');
      });
      const coordinates = `${this.label('x', c.x)} · ${this.label('y', c.y)}`;
      let text = c.active ? `Active: ${coordinates}` : `No cell active · remembered ${coordinates}`;
      if (p) text += ` · Requested ${this.label('x', p.x)} · ${this.label('y', p.y)}, awaiting confirmation`;
      if (this.status.textContent !== text) this.status.textContent = text;
      this.message.textContent = this.state.message || ''; this.message.hidden = !this.state.message;
      this.roving();
    }
  }
  window.RtplotGridPicker = RtplotGridPicker;
})();
