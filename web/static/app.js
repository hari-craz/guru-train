const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api = (u, body, method) => fetch(u, {method: method || (body ? 'POST' : 'GET'),
  headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined}).then(r => r.json());
const openDlg = id => $(id).showModal();

let S = {}, trains = [], alerts = [], kpi = {}, events = [], meta = {stations: [], tracks: [], categories: []};
let view = 'dashboard', subTab = 'stn', schedCache = [], regCache = [];
const charts = {};
const CAT_COL = {EXPRESS: '#ffd166', PASSENGER: '#7cc7ff', GOODS: '#9be3a0', FREIGHT: '#c7a3ff'};
const TRK_Y = {2: 60, 1: 130, 3: 200, 4: 270, 5: 340};
const TRK_COL = {1: '#1aa7ec', 2: '#7a8cb5', 3: '#f5a524', 4: '#f5a524', 5: '#c7a3ff'};

// ---------- navigation
function show(v) {
  if (!document.getElementById('v-' + v)) v = 'dashboard';
  view = v;
  document.querySelectorAll('.view').forEach(e => e.classList.toggle('on', e.id === 'v-' + v));
  document.querySelectorAll('#side a[data-v]').forEach(a => a.classList.toggle('act', a.dataset.v === v));
  $('side').classList.remove('open');
  if (v === 'train-mgmt') loadReg();
  if (v === 'scheduling') loadSched();
  if (v === 'alerts') loadAlerts();
  if (v === 'analytics') loadAnalytics();
  render();
}
window.addEventListener('hashchange', () => show(location.hash.slice(1)));
$('burger').onclick = () => $('side').classList.toggle('open');

// ---------- clock
setInterval(() => {
  const d = new Date();
  $('clk').textContent = d.toLocaleTimeString('en-GB');
  $('dt').textContent = d.toLocaleDateString('en-GB', {weekday: 'short', day: '2-digit', month: 'short', year: 'numeric'}).toUpperCase();
}, 1000);

// ---------- websocket
function connect() {
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/ui');
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    S = m.state; trains = m.trains; alerts = m.alerts; kpi = m.kpi;
    if (m.events) events = m.events;
    render();
  };
  ws.onclose = () => setTimeout(connect, 2000);
}

// ---------- filters
function stationSel() { return meta.stations.find(s => s.code === $('fStn').value) || meta.stations[0]; }
function fillFilters() {
  const divs = [...new Set(meta.stations.map(s => s.division))];
  $('fDiv').innerHTML = divs.map(d => `<option>${esc(d)}</option>`).join('');
  fillStations();
  $('fCat').innerHTML = '<option value="">All Categories</option>' + meta.categories.map(c => `<option>${c}</option>`).join('');
  $('tCat').innerHTML = meta.categories.map(c => `<option>${c}</option>`).join('');
}
function fillStations() {
  $('fStn').innerHTML = meta.stations.filter(s => s.division === $('fDiv').value)
    .map(s => `<option value="${s.code}">${esc(s.name)} (${s.code})</option>`).join('');
}
$('fDiv').onchange = () => { fillStations(); render(); };
$('fStn').onchange = render; $('fCat').onchange = render;
const visible = () => trains.filter(t => !$('fCat').value || t.category === $('fCat').value);

// ---------- rendering
function render() {
  if (!S.mode) return;
  const st = stationSel();
  if (st) { $('hStation').textContent = '| ' + st.name + ` (${st.code})`; }
  $('modeLine').textContent = `[${S.paused ? 'PAUSED' : 'SIMULATION'} ${S.speed}x + LIVE RIG ${S.device_online ? 'ONLINE' : 'OFFLINE'}] Tamil Nadu Zone`;
  $('bPause').textContent = S.paused ? '▶ Resume Simulation' : '⏸ Pause Simulation';
  if (view === 'dashboard') renderDash();
  if (view === 'monitoring') renderMon();
  if (view === 'station-mgmt') renderStations();
  if (view === 'track-mgmt') renderTracks();
  if (view === 'ai-dispatch') $('aiBig').innerHTML = aiHtml(true);
}

function renderDash() {
  const ts = visible();
  $('kActive').textContent = kpi.active; $('kPunc').textContent = kpi.punctuality + '%';
  $('kDelay').textContent = kpi.avg_delay + 'm';
  $('kInter').textContent = kpi.interlocking;
  $('kInter').style.color = kpi.interlocking === 'NOMINAL' ? 'var(--accent)' : 'var(--bad)';
  $('kInterS').textContent = kpi.interlocking === 'NOMINAL' ? 'All Line Relays Clear' : 'Conflict predicted - AI action pending';
  const st = stationSel();
  $('ctcTitle').textContent = st ? `${st.name} [${st.division.split('(')[1]?.replace(')', '') || ''} DIVISION]` : '';
  drawCtc(ts);
  renderSub();
  $('occ').innerHTML = [1, 2, 3, 4, 5].map(n => {
    const on = trains.filter(t => t.track === n);
    const cls = on.length > 1 ? 'CONFLICT' : on.length ? 'OCCUPIED' : 'CLEAR';
    const tr = meta.tracks.find(x => x.id === n) || {name: ''};
    return `<div class="occ"><b>T${n}</b><div>${esc(tr.name)}<br><small>${on.length ? on.map(t => '#' + esc(t.number)).join(', ') : 'None'}</small></div><span class="st ${cls}">${cls}</span></div>`;
  }).join('');
  $('aiBox').innerHTML = aiHtml(false);
  $('dDot').className = 'dot' + (S.device_online ? ' on' : '');
  $('dTxt').textContent = S.device_online ? 'ESP32 Online' : 'ESP32 Offline';
  $('rigSw').textContent = 'Switch 1A: ' + S.switch + (S.switch === 'LOOP' ? ' (Track 3)' : ' (Track 1)');
  $('rigBlk').textContent = S.occupied ? 'BLOCK OCCUPIED' : 'BLOCK CLEAR';
  $('l1').textContent = S.lcd[0] || ' '; $('l2').textContent = S.lcd[1] || ' ';
  $('log').innerHTML = events.slice(0, 12).map(e =>
    `<div><span>${new Date(e.ts * 1000).toLocaleTimeString()}</span>[${esc(e.kind)}] ${esc(e.msg)}</div>`).join('');
}

function drawCtc(ts) {
  let g = '';
  [2, 1, 3, 4, 5].forEach(n => {
    const y = TRK_Y[n], tr = meta.tracks.find(x => x.id === n) || {name: '', direction: '', limit: ''};
    g += `<line x1="40" y1="${y}" x2="920" y2="${y}" stroke="${TRK_COL[n]}" stroke-width="6" stroke-linecap="round" opacity="${n === 3 && S.switch !== 'LOOP' ? .45 : 1}"/>`;
    g += `<text x="44" y="${y - 12}">TRK ${n} | ${esc(tr.name)} [${tr.limit} KM/H] ${tr.direction === 'UP' ? '➔' : tr.direction === 'DOWN' ? '⬅' : '⇄'}</text>`;
  });
  const sw = S.switch === 'LOOP';
  g += `<line x1="250" y1="130" x2="300" y2="200" stroke="#f5a524" stroke-width="6" ${sw ? 'class="sw-live"' : 'opacity=".35"'}/>`;
  g += `<line x1="640" y1="200" x2="690" y2="130" stroke="#f5a524" stroke-width="6" ${sw ? 'class="sw-live"' : 'opacity=".35"'}/>`;
  g += `<circle cx="250" cy="130" r="8" fill="${sw ? '#f5a524' : '#fff'}"/><text x="214" y="116">SWITCH 1A</text>`;
  g += `<circle cx="690" cy="130" r="8" fill="${sw ? '#f5a524' : '#fff'}"/><text x="672" y="116">SWITCH 1B</text>`;
  g += `<text x="40" y="395">WEST ENTRY INTERLOCKING (approach block)</text><text x="640" y="395">EAST EXIT INTERLOCKING (departure block)</text>`;
  ts.forEach(t => {
    const y = TRK_Y[t.track], down = t.track === 2 || t.track === 4;
    const x = 50 + (down ? 100 - t.progress : t.progress) * 8.4;
    const hold = t.status === 'HOLD', real = t.real;
    g += `<g><title>#${esc(t.number)} ${esc(t.name)}\n${t.category} | ${t.speed} km/h | delay ${t.delay}m\n${esc(t.from)} → ${esc(t.to)}\nStatus: ${t.status}${real ? ' (PHYSICAL RIG TRAIN)' : ''}</title>
      <rect x="${x - 22}" y="${y - 11}" width="44" height="22" rx="5" fill="${CAT_COL[t.category] || '#fff'}" stroke="${hold ? '#ff5d5d' : real ? '#fff' : 'none'}" stroke-width="3"/>
      <text x="${x}" y="${y + 4}" text-anchor="middle" style="fill:#05101f;font-weight:700">${esc(String(t.number).slice(-5))}</text>
      ${hold ? `<text x="${x}" y="${y + 26}" text-anchor="middle" style="fill:#ff9a9a">🛑 HOLD</text>` : ''}
      ${t.status === 'DIVERTED' ? `<text x="${x}" y="${y + 26}" text-anchor="middle" style="fill:#f5a524">↪ DIVERTED</text>` : ''}</g>`;
  });
  $('ctc').innerHTML = g;
}

function renderSub() {
  const st = stationSel(); let h = '';
  const row = t => `<tr><td>#${esc(t.number)}</td><td>${esc(t.name)}</td><td>${t.category}</td><td>T${t.track}</td><td>${t.eta}</td><td>${t.delay ? '+' + t.delay + ' min' : 'On Time'}</td></tr>`;
  const head = '<table><thead><tr><th>NO</th><th>NAME</th><th>CAT</th><th>LINE</th><th>ETA</th><th>DELAY</th></tr></thead><tbody>';
  if (subTab === 'stn' && st) {
    h = `<div class="row" style="gap:24px"><div><small>ACTIVE TERMINAL</small><br><b>${st.code}</b><br>${esc(st.name)}</div>
      <div><small>DIVISION</small><br>${esc(st.division)}</div><div><small>PLATFORMS</small><br>${st.platforms}</div>
      <div><small>INTERLOCKED TRACKS</small><br>5 lines</div><div><small>STATUS</small><br>${kpi.interlocking === 'NOMINAL' ? 'Operational (CTC Normal)' : 'Conflict handling'}</div></div>`;
  } else if (subTab === 'inc') h = head + trains.filter(t => t.progress < 50).map(row).join('') + '</tbody></table>';
  else if (subTab === 'trn') h = head + trains.filter(t => t.progress >= 50).map(row).join('') + '</tbody></table>';
  else h = '<table><thead><tr><th>NO</th><th>STOP</th><th>ARR</th><th>DEP</th><th>PF</th></tr></thead><tbody>' +
    schedCache.filter(s => !st || s.code === st.code).map(s => `<tr><td>#${esc(s.number)}</td><td>${esc(s.station)}</td><td>${s.arr}</td><td>${s.dep}</td><td>${s.platform}</td></tr>`).join('') + '</tbody></table>';
  $('subBody').innerHTML = h;
}
$('subTabs').onclick = e => {
  if (!e.target.dataset.t) return;
  subTab = e.target.dataset.t;
  document.querySelectorAll('#subTabs button').forEach(b => b.classList.toggle('on', b === e.target));
  if (subTab === 'sch' && !schedCache.length) loadSched().then(renderSub); else renderSub();
};

function stepsHtml(status) {
  const idx = {PREDICTED: 1, DIVERTED: 4, HELD: 4, RESOLVED: 5}[status] || 1;
  return '<div class="steps">' + ['1. PREDICTED', '2. ACKNOWLEDGED', '3. DECISION', '4. DIVERSION', '5. RESOLVED']
    .map((s, i) => `<span class="${i < idx ? 'on' : ''}">${s}</span>`).join('') + '</div>';
}
function aiHtml(big) {
  const a = alerts[0];
  if (!a) return `<h3>🚨 AI Predictive Conflict Center</h3><div class="row"><span class="st CLEAR">MONITORING</span></div>
    <p><b>NOMINAL TRAFFIC MONITORING</b><br>All 5 track sections clear. Automatic predictive AI monitoring is active for the Southern Railway corridor.</p>
    <p class="note">🛡 AI Collision Prevention &amp; Block Protection Active</p>`;
  const pending = a.status === 'PREDICTED';
  return `<h3>🚨 AI Predictive Conflict Center</h3>
    <div class="row"><span class="st ${a.status}">${pending ? 'CONFLICT PREDICTED' : a.status}</span><b>⚠ TRACK ${a.track} CONFLICT – ${esc(a.kind)}</b></div>
    <p>Winner <b>#${esc(a.winner)}</b> keeps Track ${a.track}. Loser <b>#${esc(a.loser)}</b>.</p>
    <p><b>AI RECOMMENDATION:</b> ${esc(a.action)}</p><p class="note">${esc(a.detail)}</p>${stepsHtml(a.status)}
    ${pending ? `<div class="row"><button onclick="decide(${a.id},'approve')">✓ Approve diversion</button><button class="ghost" onclick="decide(${a.id},'reject')">✕ Reject (hold)</button></div>
      <p class="note">${S.mode === 'AUTO' ? 'Automatic dispatch is ON.' : 'Manual approval mode: controller confirmation required.'}</p>` : ''}`;
}
const decide = (id, action) => api(`/api/alerts/${id}/decide`, {action});

function renderMon() {
  $('monBody').innerHTML = trains.map(t => `<tr><td>#${esc(t.number)}<br><small>${esc(t.name)}${t.real ? ' · RIG' : ''}</small></td>
    <td>${t.category}</td><td>Track ${t.track}</td><td><small>${esc(t.from)} ➔ ${esc(t.to)}</small></td><td>${t.speed} km/h</td>
    <td>${t.progress}%</td><td>${t.eta}</td><td>${t.delay ? '+' + t.delay + ' min' : 'On Time'}</td>
    <td><span class="st ${t.status}">${t.status}</span></td></tr>`).join('');
}
function renderStations() {
  $('stnBody').innerHTML = meta.stations.map(s => `<tr><td>${s.code}</td><td>${esc(s.name)}</td><td>${esc(s.division)}</td>
    <td>${s.platforms}</td><td>5</td><td><span class="st CLEAR">OPERATIONAL</span></td></tr>`).join('');
}
function renderTracks() {
  $('trkBody').innerHTML = meta.tracks.map(k => {
    const on = trains.filter(t => t.track === k.id);
    return `<tr><td>T${k.id}</td><td>${esc(k.name)}</td><td>${k.direction}</td><td>${k.limit} km/h</td>
      <td><span class="st ${on.length > 1 ? 'CONFLICT' : on.length ? 'OCCUPIED' : 'CLEAR'}">${on.length ? on.length + ' train(s)' : 'CLEAR'}</span></td></tr>`;
  }).join('');
  $('swNow').textContent = 'Switch 1A: ' + S.switch; $('modeNow').textContent = 'Mode: ' + S.mode;
  $('scanTxt').textContent = S.last_scan ? `Last scan ${S.last_scan.uid} → #${S.last_scan.train.number} ${S.last_scan.train.name} (${S.last_scan.train.type})` : 'No RFID scan yet.';
}

// ---------- data views
async function loadReg() {
  regCache = await api('/api/trains');
  $('regBody').innerHTML = regCache.map(r => `<tr><td>${esc(r.uid)}</td><td>#${esc(r.number)}</td><td>${esc(r.name)}</td>
    <td><span class="tag ${r.type}" style="color:${CAT_COL[r.type]}">${r.type}</span></td>
    <td><button class="ghost" onclick="editTrain('${esc(r.uid)}')">✏ Edit</button> <button class="ghost" onclick="delTrain('${esc(r.uid)}')">🗑</button></td></tr>`).join('');
  $('simTrain').innerHTML = regCache.map(r => `<option value="${esc(r.uid)}">#${esc(r.number)} ${esc(r.name)}</option>`).join('');
}
function editTrain(uid) {
  const r = regCache.find(x => x.uid === uid); if (!r) return;
  $('tUid').value = r.uid; $('tNum').value = r.number; $('tName').value = r.name; $('tCat').value = r.type; openDlg('dTrain');
}
async function saveTrain() {
  await api('/api/trains', {uid: $('tUid').value.trim(), number: $('tNum').value, name: $('tName').value, type: $('tCat').value});
  $('dTrain').close(); loadReg();
}
async function delTrain(uid) { if (confirm('Delete train ' + uid + '?')) { await api('/api/trains', {uid}, 'DELETE'); loadReg(); } }

async function loadSched() {
  schedCache = await api('/api/schedules');
  $('schBody').innerHTML = schedCache.map(s => `<tr><td>#${esc(s.number)}<br><small>${esc(s.name)}</small></td><td>${esc(s.station)} ${s.code}</td>
    <td>${s.arr}</td><td>${s.dep}</td><td>Platform ${s.platform}</td><td>Stop #${s.seq}</td><td>${s.halt} min</td>
    <td><button class="ghost" onclick="editSched(${s.id})">✏ Edit</button></td></tr>`).join('');
}
function editSched(id) {
  const s = schedCache.find(x => x.id === id);
  $('sId').value = id; $('sArr').value = s.arr; $('sDep').value = s.dep; $('sPf').value = s.platform; $('sHalt').value = s.halt; openDlg('dSch');
}
async function saveSched() {
  await api('/api/schedules/' + $('sId').value, {arr: $('sArr').value, dep: $('sDep').value, platform: $('sPf').value, halt: $('sHalt').value}, 'PUT');
  $('dSch').close(); loadSched();
}
async function loadAlerts() {
  const rows = await api('/api/alerts');
  $('alBody').innerHTML = rows.length ? rows.map(a => `<tr><td>#${a.id}</td><td>#${esc(a.winner)}</td><td>#${esc(a.loser)}</td><td>${esc(a.kind)}</td>
    <td>${new Date(a.ts * 1000).toLocaleTimeString()}</td><td>${esc(a.action)}</td><td><span class="st ${a.status}">${a.status}</span></td><td>Track ${a.track}</td></tr>`).join('')
    : '<tr><td colspan="8">No alerts recorded yet.</td></tr>';
}

function chart(id, type, labels, data, colors) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart($(id), {type, data: {labels, datasets: [{data, backgroundColor: colors, borderColor: '#1aa7ec', tension: .3}]},
    options: {plugins: {legend: {display: type === 'doughnut'}}, responsive: true}});
}
async function loadAnalytics() {
  if (!window.Chart) return;
  Chart.defaults.color = '#8a9bbd'; Chart.defaults.borderColor = '#1b2d57';
  const a = await api('/api/analytics'), pal = ['#1aa7ec', '#f5a524', '#2ecc71', '#c7a3ff', '#ff5d5d'];
  chart('cA', 'bar', Object.keys(a.delay), Object.values(a.delay), '#f5a524');
  chart('cB', 'line', Object.keys(a.hourly), Object.values(a.hourly), '#1aa7ec');
  chart('cC', 'doughnut', Object.keys(a.punctuality), Object.values(a.punctuality), Object.keys(a.punctuality).map(k => k === 'On time' ? '#2ecc71' : '#ff5d5d'));
  chart('cD', 'bar', Object.keys(a.track_util), Object.values(a.track_util), '#1aa7ec');
  chart('cE', 'doughnut', Object.keys(a.categories), Object.values(a.categories), pal);
  chart('cF', 'bar', Object.keys(a.resolution), Object.values(a.resolution), pal);
  const r = a.rig;
  $('rigStats').innerHTML = `<span class="tag">Trains through rig: ${r.total}</span><span class="tag">Avg transit: ${r.avg_transit}s</span>
    <span class="tag">MAIN: ${r.by_route.MAIN || 0}</span><span class="tag">LOOP: ${r.by_route.LOOP || 0}</span>`;
  $('rigBody').innerHTML = r.recent.map(m => `<tr><td>${esc(m.train_name)}</td><td>${esc(m.train_type)}</td><td>${m.route}</td><td>${m.transit_s.toFixed(1)}s</td></tr>`).join('');
}

// ---------- controls
$('bPause').onclick = () => api('/api/sim', {action: S.paused ? 'resume' : 'pause'});
$('bMode').onclick = () => api('/api/mode', {mode: S.mode === 'AUTO' ? 'MANUAL' : 'AUTO'});
$('pAuto').onclick = () => api('/api/mode', {mode: 'AUTO'});
$('pMan').onclick = () => api('/api/mode', {mode: 'MANUAL'});
document.querySelectorAll('[data-sim]').forEach(b => b.onclick = () => api('/api/simulate', {action: b.dataset.sim, uid: $('simTrain').value}));

(async function init() {
  meta = await api('/api/meta');
  fillFilters();
  await loadReg(); await loadSched();
  show(location.hash.slice(1) || 'dashboard');
  connect();
  setInterval(() => { if (view === 'analytics') loadAnalytics(); if (view === 'alerts') loadAlerts(); }, 10000);
})();
