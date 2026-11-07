/* Training Dashboard runtime.
 * A small stand-in for the data layer the dashboard was first built on: it fetches each
 * dataset from the local server, works out the calculated tables, and redraws every
 * [data-draw] element whenever data, filters, visibility or width change.
 */
(function () {
  'use strict';

  // Where each dataset comes from. {name} is filled from the current parameters.
  const DATASETS = {
    activities: '/api/activities?start={act_start}&end={today}',
    effect: '/api/effect?limit=15',
    vo2: '/api/vo2?start={h90_start}&end={today}',
    hrv: '/api/hrv?start={h30_start}&end={today}',
    sleep: '/api/sleep?start={h30_start}&end={today}',
    rhr: '/api/rhr?end={today}&days=30',
    load: '/api/load?start={h30_start}&end={today}',
    balance: '/api/balance?date={today}',
    plan: '/api/scheduled?start={today}&end={plan_end}',
    ftp_garmin: '/api/ftp',
    devices: '/api/devices',
    race: '/api/store/race',
    phases: '/api/store/phases',
    device_log: '/api/store/device_log',
    ftp_tests: '/api/store/ftp_tests',
  };

  const state = {};
  const calcs = {};
  const draws = {};
  const dataFns = [];
  let params = {};
  let version = 0;
  const calcMemo = {};

  const token = () => { try { return localStorage.getItem('t100_token') || ''; } catch (e) { return ''; } };
  const urlFor = (id) => DATASETS[id].replace(/\{(\w+)\}/g, (_, k) => encodeURIComponent(params[k] ?? ''));
  const usesParam = (id, names) => names.some((n) => DATASETS[id] && DATASETS[id].includes('{' + n + '}'));

  async function api(path, opts = {}) {
    const headers = Object.assign({ Accept: 'application/json' }, opts.headers || {});
    const t = token(); if (t) headers['X-App-Token'] = t;
    const res = await fetch(path, Object.assign({}, opts, { headers }));
    let body = null;
    try { body = await res.json(); } catch (e) { body = null; }
    if (!res.ok) throw new Error((body && body.error) || `${res.status} ${res.statusText}`);
    return body;
  }

  function load(id, force) {
    if (!DATASETS[id]) { state[id] = { status: 'missing', data: [], columns: [], message: 'Unknown source' }; return; }
    const s = state[id];
    if (s && !force && (s.status !== 'idle')) return;
    const prev = s && s.status === 'ok' ? s : null;
    const url = urlFor(id);
    state[id] = prev ? Object.assign({}, prev, { refreshing: true, url }) : { status: 'loading', data: [], columns: [], url };
    api(url).then((body) => {
      if (state[id].url !== url) return;
      state[id] = { status: 'ok', data: body.rows || [], columns: body.columns || [], cut: !!body.cut, source: body.source || null, url, refreshing: false };
      schedule();
    }).catch((e) => {
      if (state[id].url !== url) return;
      state[id] = { status: 'error', data: [], columns: [], message: String(e.message || e), url };
      console.warn(`[t100] ${id} failed:`, e);
      schedule();
    });
  }

  function dataOf(id) {
    if (calcs[id]) {
      const memo = calcMemo[id];
      if (memo && memo.v === version) return memo.r;
      const c = calcs[id];
      const ins = c.inputs.map((i) => dataOf(i));
      let r;
      const bad = ins.find((x) => x.status === 'error' || x.status === 'missing');
      if (bad) r = { status: 'error', data: [], columns: [], message: bad.message };
      else if (ins.some((x) => x.status !== 'ok')) r = { status: 'loading', data: [], columns: [] };
      else {
        try {
          const out = c.fn(...ins.map((x) => x.data));
          r = { status: 'ok', data: out, columns: Array.isArray(out) && out[0] ? Object.keys(out[0]) : [], refreshing: ins.some((x) => x.refreshing) };
        } catch (e) { console.error(`[t100] calc ${id} failed:`, e); r = { status: 'error', data: [], columns: [], message: String(e) }; }
      }
      calcMemo[id] = { v: version, r };
      return r;
    }
    if (!state[id]) { state[id] = { status: 'idle' }; load(id); }
    const s = state[id];
    return { status: s.status === 'idle' ? 'loading' : s.status, data: s.data || [], columns: s.columns || [], message: s.message, refreshing: !!s.refreshing, source: s.source || null, meta: [] };
  }

  let pending = false;
  function schedule() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; runAll(); });
  }

  function visible(el) { return !el.closest('[hidden]'); }

  function runDraw(name) {
    const fn = draws[name];
    if (!fn) return;
    document.querySelectorAll(`[data-draw="${CSS.escape(name)}"]`).forEach((el) => {
      if (!visible(el)) return;
      try { fn(el); } catch (e) { console.error(`[t100] drawing ${name} failed:`, e); }
    });
  }

  function runAll() {
    version++;
    for (const fn of dataFns) { try { fn(); } catch (e) { console.error('[t100] onData failed:', e); } }
    Object.keys(draws).forEach(runDraw);
  }

  const dash = {
    data: dataOf,
    onData(fn) { dataFns.push(fn); schedule(); },
    draw(name, fn) {
      if (typeof fn === 'function') { draws[name] = fn; schedule(); }
      else if (fn && typeof fn.update === 'function') { draws[name] = (el) => fn.update(el, el.__made || (el.__made = fn.mount ? fn.mount(el) : undefined)); schedule(); }
      else runDraw(name);
    },
    calc(id, def) { calcs[id] = { inputs: def.inputs || [], fn: def.fn, title: def.title, description: def.description }; schedule(); },
    loader() { /* the server already returns tables */ },
    params() { return Object.assign({}, params); },
    setParams(obj) {
      const changed = Object.keys(obj).filter((k) => params[k] !== obj[k]);
      params = Object.assign({}, params, obj);
      Object.keys(state).forEach((id) => { if (usesParam(id, changed)) load(id, true); });
      schedule();
    },
    resetParams() { params = {}; Object.keys(state).forEach((id) => load(id, true)); schedule(); },
    refresh(id) { if (id) load(id, true); else Object.keys(state).forEach((k) => load(k, true)); schedule(); },
    setLink(name) { try { history.replaceState(null, '', name ? '#' + name : location.pathname); } catch (e) { /* ignore */ } },
    colors: ['#0181d1', '#00bf6f', '#d84d04', '#faad00', '#ca426e', '#5c3d8f', '#8c9894', '#183029'],
    api,
  };
  window.dash = dash;

  // Redraw when a page (tab) is shown: drawings inside hidden pages are skipped until then.
  const shownState = new WeakMap();
  new MutationObserver((records) => {
    if (records.some((r) => r.target.classList && r.target.classList.contains('tx-page') && shownState.get(r.target) !== r.target.hidden && (shownState.set(r.target, r.target.hidden), true))) schedule();
  }).observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ['hidden'] });
  let rt = null;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(schedule, 120); });
})();
