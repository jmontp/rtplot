/* Presentation only: never rebuilds plots or sends application commands. */
(() => {
  const defaults = {enabled: true, visible: true, busy: false, selected: false, reason: ''};
  const statusLabels = {idle: '○ Idle', ready: '● Ready', busy: '◌ Busy', complete: '✓ Complete', warning: '⚠ Warning', error: '✕ Error'};
  class RtplotView {
    constructor(root, cfg, changed) {
      this.root = root; this.cfg = cfg; this.changed = changed;
      this.controls = new Map(); this.sections = new Map();
      this.state = {controls: {}, sections: {}}; this.revision = -1;
      this.available = cfg.source_available !== false; this.connected = true;
      this.reason = cfg.source_reason || '';
      this.essentialIds = new Set(cfg.view?.essential_controls || []);
      this.key = `rtplotSections.v1:${cfg.tab}`;
      try { this.prefs = JSON.parse(sessionStorage.getItem(this.key) || '{}'); } catch (_) { this.prefs = {}; }
      this.sticky = document.createElement('div'); this.sticky.className = 'ui-sticky'; root.appendChild(this.sticky);
      this.banner = document.createElement('div'); this.banner.className = 'ui-source-status';
      this.banner.setAttribute('role', 'status'); this.sticky.appendChild(this.banner);
      this.nav = document.createElement('nav'); this.nav.className = 'section-nav'; this.nav.setAttribute('aria-label', 'Sections'); root.appendChild(this.nav);
      this.more = document.createElement('details'); this.more.className = 'section-more';
      const summary = document.createElement('summary'); summary.textContent = 'More'; this.more.appendChild(summary);
      this.secondary = document.createElement('div'); this.secondary.className = 'secondary-links'; this.more.appendChild(this.secondary);
      this.essentials = document.createElement('div'); this.essentials.className = 'essential-controls';
      this.essentials.setAttribute('role', 'group'); this.essentials.setAttribute('aria-label', 'Essential actions and state');
      this.sticky.appendChild(this.essentials);
      this.overflow = document.createElement('div'); this.overflow.className = 'persistent-overflow'; this.sticky.appendChild(this.overflow);
      const view = cfg.view || {};
      (view.sections || []).forEach((s, index) => {
        const node = document.createElement('section'); node.className = 'view-section'; node.dataset.section = s.id;
        node.id = `rtplot-section-${index}`;
        node.dataset.density = s.density || 'normal';
        node.setAttribute('aria-label', s.title);
        const header = document.createElement('div'); header.className = 'section-header';
        const heading = document.createElement('h2'); heading.tabIndex = -1;
        const toggle = document.createElement(s.collapsible && s.id !== view.persistent_section ? 'button' : 'span');
        toggle.textContent = s.title; heading.appendChild(toggle); header.appendChild(heading); node.appendChild(header);
        if (s.show_heading === false) header.classList.add('heading-optional');
        if (s.description) { const d = document.createElement('p'); d.className = 'section-description'; d.textContent = s.description; node.appendChild(d); }
        const status = document.createElement('span'); status.className = 'section-status'; header.appendChild(status);
        const message = document.createElement('p'); message.className = 'section-message'; message.setAttribute('role', 'status'); node.appendChild(message);
        const body = document.createElement('div'); body.className = 'section-body'; body.id = `${node.id}-body`; node.appendChild(body);
        const link = document.createElement('a'); link.textContent = s.title; link.href = `#${node.id}`;
        const navStatus = document.createElement('span'); navStatus.className = 'nav-status'; link.appendChild(navStatus);
        (s.navigation === 'secondary' ? this.secondary : this.nav).appendChild(link);
        const section = {declaration: s, node, body, toggle, link, navStatus, heading, status, message, collapsed: false};
        this.sections.set(s.id, section);
        if (s.id === view.persistent_section) { node.classList.add('persistent-section'); this.overflow.appendChild(node); }
        else root.appendChild(node);
        const canCollapse = toggle.tagName === 'BUTTON';
        if (canCollapse) {
          toggle.setAttribute('aria-controls', body.id);
          toggle.addEventListener('click', () => this.collapse(s.id, !section.collapsed, true));
        }
        this.collapse(s.id, canCollapse && (Object.hasOwn(this.prefs, s.id) ? this.prefs[s.id] : s.collapsed));
        link.addEventListener('click', e => {
          e.preventDefault(); this.collapse(s.id, false, true);
          // A declaration/runtime-hidden section has no navigation link.
          this.more.open = false;
          this.changed(); requestAnimationFrame(() => {
            if (s.id === view.persistent_section && this.overflow.hidden) {
              this.essentials.tabIndex = -1; this.essentials.focus({preventScroll: true});
            } else {
              heading.focus({preventScroll: true}); node.scrollIntoView({block: 'start'});
            }
          });
        });
      });
      this.nav.appendChild(this.more); this.more.hidden = !this.secondary.children.length;
      this.nav.hidden = !this.sections.size;
      this.refreshAvailability();
      this.observer = new ResizeObserver(() => this.offsets());
      this.observer.observe(this.sticky); this.observer.observe(document.getElementById('header'));
      this.onFocus = e => {
        if (!root.contains(e.target) || this.sticky.contains(e.target)) return;
        const top = document.getElementById('header').getBoundingClientRect().bottom + this.sticky.getBoundingClientRect().height;
        if (e.target.getBoundingClientRect().top < top) e.target.scrollIntoView({block: 'center'});
      };
      root.addEventListener('focusin', this.onFocus);
      this.offsets();
    }
    finish() {
      // Move the existing elements once, preserving declared control order.
      // Resizing and state updates never reparent, clone, or replace them.
      this.controls.forEach((c, id) => { if (this.essentialIds.has(id)) this.essentials.appendChild(c.item); });
      this.essentials.hidden = !this.essentials.children.length;
      this.overflow.querySelectorAll('.ctrl-row').forEach(row => { if (!row.querySelector('.ctrl-item')) row.hidden = true; });
      this.overflow.hidden = !this.overflow.querySelector('.ctrl-row:not([hidden])');
      this.refreshAvailability(); this.offsets();
    }
    offsets() {
      const header = document.getElementById('header').getBoundingClientRect().height;
      this.sticky.style.top = `${header}px`;
      const margin = header + this.sticky.getBoundingClientRect().height + 12;
      document.documentElement.style.setProperty('--presentation-offset', `${margin}px`);
      this.sticky.style.setProperty('--source-height', `${this.banner.getBoundingClientRect().height}px`);
      this.sticky.style.setProperty('--essential-height', `${this.essentials.getBoundingClientRect().height}px`);
      this.sections.forEach(s => { s.node.style.scrollMarginTop = `${margin}px`; });
    }
    parent(section) { return this.sections.get(section)?.body || this.root; }
    collapse(id, value, save=false) {
      const s = this.sections.get(id); if (!s) return;
      s.collapsed = Boolean(value); s.body.hidden = s.collapsed;
      if (s.toggle.tagName === 'BUTTON') { s.toggle.setAttribute('aria-expanded', String(!s.collapsed)); }
      if (save) { this.prefs[id] = s.collapsed; try { sessionStorage.setItem(this.key, JSON.stringify(this.prefs)); } catch (_) {} }
      this.changed();
    }
    register(id, item, section) {
      if (!id) return;
      item.dataset.controlId = id;
      const reason = document.createElement('span'); reason.className = 'ctrl-reason'; reason.id = `control-reason-${this.controls.size}`; reason.hidden = true;
      const busy = document.createElement('span'); busy.className = 'ctrl-busy'; busy.textContent = '◌ Working…'; busy.hidden = true;
      const selected = document.createElement('span'); selected.className = 'ctrl-selected'; selected.textContent = '✓ Selected'; selected.hidden = true;
      item.append(reason, busy, selected);
      this.controls.set(id, {item, section, reason, busy, selected});
      this.applyControl(id);
    }
    canInteract(id) {
      const c = this.controls.get(id); if (!c) return false;
      const v = {...defaults, ...this.state.controls?.[id]};
      const s = this.sections.get(c.section);
      return this.connected && this.available && v.enabled && v.visible && (this.essentialIds.has(id) || !s || (!s.node.hidden && !s.collapsed));
    }
    applyControl(id) {
      const c = this.controls.get(id); if (!c) return;
      const v = {...defaults, ...this.state.controls?.[id]};
      const disabled = !this.connected || !this.available || !v.enabled;
      c.item.hidden = !v.visible;
      c.item.classList.toggle('ui-disabled', disabled); c.item.classList.toggle('ui-selected', v.selected);
      c.item.setAttribute('aria-busy', String(v.busy));
      c.reason.textContent = v.reason; c.reason.hidden = !v.reason; c.busy.hidden = !v.busy; c.selected.hidden = !v.selected;
      c.item.querySelectorAll('button,input,select,textarea,.ctrl-dial').forEach(el => {
        if ('disabled' in el) el.disabled = disabled;
        el.setAttribute('aria-disabled', String(disabled));
        if (v.reason) el.setAttribute('aria-describedby', c.reason.id); else el.removeAttribute('aria-describedby');
        if (el.classList.contains('ctrl-dial')) { el.setAttribute('tabindex', disabled ? '-1' : '0'); }
        if (el.classList.contains('ctrl-btn')) el.setAttribute('aria-pressed', String(v.selected));
      });
    }
    applySection(id) {
      const s = this.sections.get(id); if (!s) return;
      const v = {visible: s.declaration.visible, status: 'idle', message: '', ...this.state.sections?.[id]};
      s.node.hidden = !v.visible; s.link.hidden = !v.visible;
      this.more.hidden = !Array.from(this.secondary.children).some(link => !link.hidden);
      s.status.textContent = statusLabels[v.status] || v.status;
      s.navStatus.textContent = statusLabels[v.status] || v.status;
      s.link.dataset.status = v.status;
      s.status.dataset.status = v.status; s.message.textContent = v.message; s.message.hidden = !v.message;
    }
    apply(snapshot, revision) {
      if (revision <= this.revision) return;
      const old = this.state; this.state = snapshot; this.revision = revision;
      for (const group of ['controls', 'sections']) {
        const ids = new Set([...Object.keys(old[group] || {}), ...Object.keys(snapshot[group] || {})]);
        // Initial declarations (including hidden sections) need one application.
        if (group === 'sections' && this.revision >= 0 && !this.applied) this.sections.forEach((_, id) => ids.add(id));
        ids.forEach(id => {
          if (!this.applied || JSON.stringify(old[group]?.[id]) !== JSON.stringify(snapshot[group]?.[id])) {
            if (group === 'controls') this.applyControl(id); else this.applySection(id);
          }
        });
      }
      const visibilityChanged = !this.applied || [...this.sections.keys()].some(id => old.sections?.[id]?.visible !== snapshot.sections?.[id]?.visible);
      this.applied = true;
      if (visibilityChanged) this.changed();
    }
    refreshAvailability() {
      this.banner.hidden = this.connected && this.available;
      this.banner.textContent = !this.connected ? 'Disconnected from server — application controls unavailable' :
        this.reason || 'Source unavailable — application controls disabled';
      this.sticky.hidden = !this.sections.size && !this.essentialIds.size && this.connected && this.available;
      this.controls.forEach((_, id) => this.applyControl(id)); this.offsets();
    }
    source(available, reason) {
      if (this.available === available && this.reason === reason) return;
      this.available = available; this.reason = reason; this.refreshAvailability();
    }
    connection(connected) { this.connected = connected; this.refreshAvailability(); }
    destroy() { this.observer.disconnect(); this.root.removeEventListener('focusin', this.onFocus); }
  }
  window.RtplotView = RtplotView;
})();
