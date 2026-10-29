/*
 * dash.js – lille, selvstændig afløser for dashboard-motoren.
 *
 * Indlæser datasættene i data/datasets.json og giver siden det samme API,
 * som den bruger: dash.data, dash.calc, dash.draw, dash.onData, dash.params,
 * dash.setParams, dash.resetParams, dash.setLink og dash.colors.
 *
 * Kræver d3 v7 (indlæses før denne fil).
 */
(function () {
  'use strict';

  const state = {
    manifest: null,
    data: {},          // id -> {status, data, columns, message}
    calcs: {},         // id -> {inputs, fn, title, description}
    draws: new Map(),  // navn -> fn eller {mount, update, unmount}
    mounted: new WeakMap(),
    onData: [],
    params: {},
    defaults: {},
    ready: false,
    queued: false,
  };

  const safe = (fn, ...args) => {
    try { return fn(...args); } catch (err) { console.error('[dash]', err); return undefined; }
  };

  const isHidden = (el) => !!el.closest('[hidden]');

  function calcResult(id) {
    const c = state.calcs[id];
    const inputs = c.inputs.map((i) => dash.data(i));
    const bad = inputs.find((d) => d.status !== 'ok');
    if (bad) return { status: bad.status, data: [], columns: [], message: bad.message };
    const out = safe(c.fn, ...inputs.map((d) => d.data));
    if (out === undefined) return { status: 'error', data: [], columns: [], message: 'Beregningen fejlede' };
    return { status: 'ok', data: out, columns: Array.isArray(out) && out[0] ? Object.keys(out[0]) : [] };
  }

  function runDraw(name) {
    const d = state.draws.get(name);
    if (!d) return;
    document.querySelectorAll(`[data-draw="${CSS.escape(name)}"]`).forEach((el) => {
      if (isHidden(el)) return;
      if (typeof d === 'function') { safe(d, el); return; }
      let made = state.mounted.get(el);
      if (made === undefined && d.mount) { el.replaceChildren(); made = safe(d.mount, el) ?? null; state.mounted.set(el, made); }
      if (d.update) safe(d.update, el, made);
    });
  }

  function renderAll() {
    state.queued = false;
    state.onData.forEach((fn) => safe(fn));
    state.draws.forEach((_, name) => runDraw(name));
  }

  function schedule() {
    if (state.queued) return;
    state.queued = true;
    requestAnimationFrame(renderAll);
  }

  const dash = {
    colors: ['#2f6fb0', '#d9822b', '#3a9a6b', '#8e5bb5', '#c4475b', '#3f9fa3', '#a8892c', '#6b7a8f'],

    data(id) {
      if (state.calcs[id]) return calcResult(id);
      return state.data[id] || { status: state.ready ? 'missing' : 'loading', data: [], columns: [] };
    },

    onData(fn) {
      state.onData.push(fn);
      if (state.ready) safe(fn);
    },

    draw(name, fn) {
      if (fn === undefined) { runDraw(name); return; }
      state.draws.set(name, fn);
      if (state.ready) runDraw(name);
    },

    calc(id, spec) { state.calcs[id] = spec; },

    loader() { /* bruges ikke i den statiske version */ },

    params() { return { ...state.params }; },

    setParams(obj) {
      Object.entries(obj || {}).forEach(([k, v]) => {
        if (v === null || v === undefined) delete state.params[k]; else state.params[k] = v;
      });
      schedule();
    },

    resetParams() { state.params = { ...state.defaults }; schedule(); },

    setLink(name) {
      if (name) history.replaceState(null, '', '#' + encodeURIComponent(name));
    },

    refresh() { load(); },
  };

  window.dash = dash;

  // Tegn igen, når en fane eller sektion vises eller skjules.
  const observer = new MutationObserver((records) => {
    const changed = records.some((m) => (m.oldValue === null) !== (m.target.getAttribute('hidden') === null));
    if (changed) schedule();
  });

  // Tegn igen, når vinduet ændrer bredde.
  let lastWidth = 0;
  window.addEventListener('resize', () => {
    if (Math.abs(window.innerWidth - lastWidth) < 8) return;
    lastWidth = window.innerWidth;
    schedule();
  });

  async function fetchText(url) {
    const res = await fetch(url, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.text();
  }

  function parse(text, file) {
    if (/\.json$/i.test(file)) {
      const j = JSON.parse(text);
      const rows = Array.isArray(j) ? j : (j.rows || j.data || j.results || []);
      return { rows, columns: rows[0] ? Object.keys(rows[0]) : [] };
    }
    const delim = /\.tsv$/i.test(file) ? '\t' : ',';
    const rows = d3.dsvFormat(delim).parse(text);
    return { rows: rows.slice(), columns: rows.columns };
  }

  function renderSources() {
    const list = document.getElementById('kildeliste');
    if (!list || !state.manifest) return;
    list.replaceChildren();
    Object.entries(state.manifest.datasets).forEach(([id, m]) => {
      const li = document.createElement('li');
      const t = document.createElement('strong'); t.textContent = m.titel;
      const a = document.createElement('a'); a.href = m.fil; a.textContent = m.fil.replace(/^data\//, ''); a.download = '';
      const d = document.createElement('span'); d.textContent = ` – ${m.beskrivelse} Opdateret ${m.opdateret}. `;
      li.append(t, d, a);
      const st = state.data[id];
      if (st && st.status === 'error') {
        const e = document.createElement('em'); e.textContent = ` (kunne ikke indlæses: ${st.message})`; li.append(e);
      }
      list.append(li);
    });
  }

  function showFileWarning() {
    if (location.protocol !== 'file:') return;
    const root = document.getElementById('dash-root');
    if (!root || document.querySelector('.dash-filewarn')) return;
    const p = document.createElement('p');
    p.className = 'dash-filewarn';
    p.textContent = 'Siden er åbnet direkte som fil, så browseren må ikke hente datafilerne. Start en lokal server i mappen (fx "python3 -m http.server") og åbn http://localhost:8000.';
    root.prepend(p);
  }

  async function load() {
    try {
      state.manifest = JSON.parse(await fetchText('data/datasets.json'));
    } catch (err) {
      console.error('[dash] kunne ikke læse data/datasets.json', err);
      showFileWarning();
      state.ready = true;
      renderAll();
      return;
    }
    if (!Object.keys(state.params).length) {
      state.defaults = { ...(state.manifest.params || {}) };
      state.params = { ...state.defaults };
    }
    const ids = Object.keys(state.manifest.datasets);
    ids.forEach((id) => { if (!state.data[id] || state.data[id].status !== 'ok') state.data[id] = { status: 'loading', data: [], columns: [] }; });
    state.ready = true;
    renderAll();

    await Promise.all(ids.map(async (id) => {
      const file = state.manifest.datasets[id].fil;
      try {
        const { rows, columns } = parse(await fetchText(file), file);
        state.data[id] = { status: 'ok', data: rows, columns };
      } catch (err) {
        state.data[id] = { status: 'error', data: [], columns: [], message: String(err.message || err) };
      }
    }));
    if (ids.some((id) => state.data[id].status === 'error')) showFileWarning();
    renderSources();
    renderAll();
  }

  document.addEventListener('DOMContentLoaded', () => {
    observer.observe(document.body, { subtree: true, attributes: true, attributeFilter: ['hidden'], attributeOldValue: true });
    lastWidth = window.innerWidth;
    load();
  });
})();
