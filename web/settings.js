/* Settings tab: edit your race and phases, and log FTP tests and device readings.
 * Everything is saved on your own server in data/*.json. */
(function () {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const say = (id, text, err) => { const el = $(id); if (!el) return; el.textContent = text; el.classList.toggle('err', !!err); };
  const getStore = async (name) => (await dash.api(`/api/store/${name}`)).rows || [];
  const putStore = async (name, rows) => {
    const out = await dash.api(`/api/store/${name}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rows }) });
    dash.refresh(name);
    return out.rows;
  };
  const formRow = (form) => Object.fromEntries([...form.querySelectorAll('[name]')].map((el) => [el.name, el.value.trim()]));
  const today = () => new Date().toISOString().slice(0, 10);

  // ---- race
  async function loadRace() {
    const r = (await getStore('race'))[0] || {};
    document.querySelectorAll('#race-form [name]').forEach((el) => { el.value = r[el.name] ?? ''; });
  }
  $('#race-save').addEventListener('click', async () => {
    try { await putStore('race', [formRow($('#race-form'))]); say('#race-msg', 'Saved.'); }
    catch (e) { say('#race-msg', e.message, true); }
  });

  // ---- phases
  const PCOLS = ['Phase', 'Start', 'End', 'Focus', 'Status'];
  function phaseRow(p = {}) {
    const tr = document.createElement('tr');
    PCOLS.forEach((c) => {
      const td = document.createElement('td');
      if (c === 'Focus') td.className = 'hide-narrow';
      const el = document.createElement(c === 'Focus' ? 'textarea' : 'input');
      el.dataset.col = c;
      if (c === 'Start' || c === 'End') el.type = 'date';
      el.value = p[c] ?? '';
      if (c === 'Status') el.placeholder = 'TBC';
      td.append(el); tr.append(td);
    });
    const td = document.createElement('td');
    const del = document.createElement('button'); del.type = 'button'; del.className = 'tx-btn danger'; del.textContent = 'Remove';
    del.addEventListener('click', () => tr.remove());
    td.append(del); tr.append(td);
    tr.dataset.colour = p.Colour || '';
    return tr;
  }
  async function loadPhases() {
    const body = $('#phase-edit tbody'); body.replaceChildren();
    (await getStore('phases')).forEach((p) => body.append(phaseRow(p)));
  }
  $('#phase-add').addEventListener('click', () => $('#phase-edit tbody').append(phaseRow()));
  $('#phase-save').addEventListener('click', async () => {
    const rows = [...document.querySelectorAll('#phase-edit tbody tr')].map((tr) => {
      const r = { Colour: tr.dataset.colour || '' };
      tr.querySelectorAll('[data-col]').forEach((el) => { r[el.dataset.col] = el.value.trim(); });
      return r;
    }).filter((r) => r.Phase && r.Start && r.End);
    const bad = rows.find((r) => r.End < r.Start);
    if (bad) return say('#phase-msg', `"${bad.Phase}" ends before it starts.`, true);
    rows.sort((a, b) => (a.Start < b.Start ? -1 : 1));
    try { await putStore('phases', rows); say('#phase-msg', `Saved ${rows.length} phases.`); loadPhases(); }
    catch (e) { say('#phase-msg', e.message, true); }
  });

  // ---- FTP tests
  $('#ftp-add').addEventListener('click', async () => {
    const r = formRow($('#ftp-form'));
    if (!r.Date || !(Number(r['FTP (W)']) > 0)) return say('#ftp-msg', 'Add a date and an FTP in watts.', true);
    try { const rows = await getStore('ftp_tests'); rows.push(r); await putStore('ftp_tests', rows); say('#ftp-msg', 'Added.'); $('#ftp-form').querySelectorAll('input').forEach((el) => { if (el.name !== 'Date') el.value = ''; }); }
    catch (e) { say('#ftp-msg', e.message, true); }
  });

  // ---- device log
  async function loadLog() {
    const rows = await getStore('device_log');
    const body = $('#log-manage'); body.replaceChildren();
    rows.slice().sort((a, b) => (a.Date < b.Date ? 1 : -1)).slice(0, 30).forEach((r) => {
      const tr = document.createElement('tr');
      [r.Date, r.Category, r.Metric, [r.Value, r.Unit].filter(Boolean).join(' ')].forEach((v, i) => { const td = document.createElement('td'); td.textContent = v || ''; if (i === 3) td.className = 'num'; tr.append(td); });
      const td = document.createElement('td'); const del = document.createElement('button'); del.type = 'button'; del.className = 'tx-btn danger'; del.textContent = 'Delete';
      del.addEventListener('click', async () => { try { const all = await getStore('device_log'); await putStore('device_log', all.filter((x) => x.Entry !== r.Entry)); loadLog(); } catch (e) { say('#log-msg', e.message, true); } });
      td.append(del); tr.append(td); body.append(tr);
    });
  }
  $('#log-add').addEventListener('click', async () => {
    const r = formRow($('#log-form'));
    if (!r.Date || !r.Metric || !r.Value) return say('#log-msg', 'Add a date, a metric and a value.', true);
    try {
      const rows = await getStore('device_log');
      r.Entry = String(rows.reduce((m, x) => Math.max(m, Number(x.Entry) || 0), 0) + 1);
      rows.push(r); await putStore('device_log', rows); say('#log-msg', 'Added.'); loadLog();
    } catch (e) { say('#log-msg', e.message, true); }
  });

  // ---- Garmin + token
  const tok = $('#app-token');
  try { tok.value = localStorage.getItem('t100_token') || ''; } catch (e) { /* private mode */ }
  tok.addEventListener('change', () => { try { localStorage.setItem('t100_token', tok.value); } catch (e) { /* ignore */ } dash.refresh(); init(); });
  $('#garmin-refresh').addEventListener('click', async () => {
    say('#garmin-msg', 'Refreshing…');
    try { await dash.api('/api/refresh', { method: 'POST' }); dash.refresh(); say('#garmin-msg', 'Fetching the latest from Garmin.'); }
    catch (e) { say('#garmin-msg', e.message, true); }
  });

  document.querySelectorAll('#ftp-form [name="Date"], #log-form [name="Date"]').forEach((el) => { el.value = today(); });
  function init() { loadRace().catch(() => {}); loadPhases().catch(() => {}); loadLog().catch(() => {}); }
  init();

  // Keep the page background in step with dark mode.
  const tx = document.querySelector('.tx');
  if (tx) new MutationObserver(() => document.body.classList.toggle('is-dark', tx.classList.contains('tx-dark'))).observe(tx, { attributes: true, attributeFilter: ['class'] });
  if (tx) document.body.classList.toggle('is-dark', tx.classList.contains('tx-dark'));

  // Installable app: register the service worker.
  if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
})();
