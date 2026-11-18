/* What I Did — front end. No framework, no build step, no network. */

const state = {
  boot: null,
  view: 'today',
  weekIso: null,
  report: null,
  month: null,
  monthReport: null,
  tab: 'week',
  popOpen: false,
  popBusy: false,
  planEditing: false,
  addOpen: false,
  settingsDraft: null,
  snoozedUntil: 0,
};

/* ------------------------------------------------------------------ utils */
const $ = (sel, root) => (root || document).querySelector(sel);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

function fmtDuration(min) {
  min = Math.round(Number(min) || 0);
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60), m = min % 60;
  return m === 0 ? `${h}h` : `${h}h ${String(m).padStart(2, '0')}m`;
}

function fmtClock(hhmm) {
  const [h, m] = String(hhmm || '00:00').split(':').map(Number);
  const suffix = h < 12 ? 'am' : 'pm';
  return `${h % 12 || 12}:${String(m || 0).padStart(2, '0')}${suffix}`;
}

function fmtDateLong(iso) {
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
}

function fmtDateShort(iso) {
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
}

function fmtRelative(iso) {
  if (!iso) return '—';
  const then = new Date(iso);
  const diff = Math.round((then - new Date()) / 1000);
  const abs = Math.abs(diff);
  const unit = abs < 90 ? ['second', 1] : abs < 5400 ? ['minute', 60] : abs < 172800 ? ['hour', 3600] : ['day', 86400];
  const value = Math.round(diff / unit[1]);
  return new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' }).format(value, unit[0]);
}

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/* ISO week key for a date, so the strip can jump to another week. */
function weekForDate(iso) {
  const d = new Date(iso + 'T12:00:00');
  const target = new Date(d.valueOf());
  const dayNr = (d.getDay() + 6) % 7;
  target.setDate(target.getDate() - dayNr + 3);
  const firstThursday = new Date(target.getFullYear(), 0, 4);
  const week = 1 + Math.round((target - firstThursday) / (7 * 86400000));
  return `${target.getFullYear()}-W${String(week).padStart(2, '0')}`;
}

/* Minimal markdown: exactly the subset the reports use. */
function md(text) {
  const src = esc(text || '').replace(/\r\n/g, '\n');
  const lines = src.split('\n');
  const out = [];
  let list = null, para = [];

  const inline = (s) => s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
    .replace(/(^|[\s(])_([^_\s][^_]*)_(?=[\s.,;:!?)]|$)/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

  const flushPara = () => {
    if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; }
  };
  const flushList = () => {
    if (list) { out.push(`<ul>${list.map((i) => `<li>${inline(i)}</li>`).join('')}</ul>`); list = null; }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line.trim()) { flushPara(); flushList(); continue; }
    if (/^---+$/.test(line.trim())) { flushPara(); flushList(); out.push('<hr>'); continue; }
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) { flushPara(); flushList(); const lvl = h[1].length; out.push(`<h${lvl}>${inline(h[2])}</h${lvl}>`); continue; }
    const li = line.match(/^[-*]\s+(.*)$/);
    if (li) { flushPara(); (list = list || []).push(li[1]); continue; }
    if (/^>\s?/.test(line)) {
      flushPara(); flushList();
      out.push(`<blockquote>${inline(line.replace(/^>\s?/, ''))}</blockquote>`);
      continue;
    }
    flushList();
    para.push(line.trim());
  }
  flushPara(); flushList();
  return out.join('\n');
}

/* The report file starts with its own title and score, for reading outside the
   app. Inside the app the header already says both, so drop them. */
function reportBody(markdown) {
  const lines = String(markdown || '').split('\n');
  let i = 0;
  const skipBlank = () => { while (i < lines.length && !lines[i].trim()) i++; };
  skipBlank();
  if (lines[i] && /^#\s/.test(lines[i])) i++;
  skipBlank();
  if (lines[i] && /^\*\*\s*\d+\s*\/\s*10\s*\*\*$/.test(lines[i].trim())) i++;
  if (lines[i] && /^\*\*Average\s+[\d.]+\s*\/\s*10\*\*$/i.test(lines[i].trim())) i++;
  return lines.slice(i).join('\n').trim();
}

/* -------------------------------------------------------------------- api */
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) {
    const detail = (data && (data.detail || data.error)) || `${res.status} ${res.statusText}`;
    throw new Error(detail);
  }
  return data;
}

function toast(message, isError) {
  const root = $('#toast-root');
  const el = document.createElement('div');
  el.className = 'toast' + (isError ? ' err' : '');
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; }, 2600);
  setTimeout(() => el.remove(), 3000);
}

const post = (path, body) => api(path, { method: 'POST', body: body || {} });
const put = (path, body) => api(path, { method: 'PUT', body: body || {} });
const del = (path) => api(path, { method: 'DELETE' });

/* ---------------------------------------------------------------- refresh */
async function boot(week) {
  const query = week ? `?week=${encodeURIComponent(week)}` : '';
  state.boot = await api(`/api/bootstrap${query}`);
  state.weekIso = state.boot.week.iso;
  if (!state.settingsDraft) state.settingsDraft = { ...state.boot.settings };
  $('#rail-path').textContent = state.boot.data_dir;
  render();
  updateClock();
}

async function refresh() {
  const keepScroll = window.scrollY;
  const week = state.weekIso;
  const data = await api(`/api/bootstrap${week ? `?week=${encodeURIComponent(week)}` : ''}`);
  state.boot = data;
  state.settingsDraft = { ...data.settings, llm_api_key: state.settingsDraft?.llm_api_key || '' };
  $('#rail-path').textContent = data.data_dir;
  render();
  window.scrollTo(0, keepScroll);
  updateClock();
}

/* ------------------------------------------------------------------- nav */
function setView(view) {
  state.view = view;
  document.querySelectorAll('.nav-item').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.view === view);
  });
  if (view === 'report') loadReport();
  render();
}

/* ------------------------------------------------------------------ views */
function render() {
  const main = $('#main');
  if (!state.boot) return;
  document.querySelectorAll('.nav-item').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.view === state.view);
  });
  const map = { today: viewToday, week: viewWeek, report: viewReport, settings: viewSettings };
  main.innerHTML = (map[state.view] || viewToday)(state.boot);
  main.focus({ preventScroll: true });
}

function weekEntriesFor(dayIso) {
  return (state.boot.week.entries || []).filter((e) => e.date === dayIso);
}

function weekStrip(week) {
  const start = new Date(week.start + 'T12:00:00');
  const cells = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const day = week.analysis.by_day.find((x) => x.date === iso);
    const mins = day ? day.minutes : 0;
    const pct = Math.min(100, Math.round((mins / 480) * 100));
    const cls = ['strip-cell'];
    if (!day) cls.push('is-empty');
    if (iso === state.boot.today) cls.push('is-today');
    if (iso > state.boot.today) cls.push('is-future');
    cells.push(`
      <button class="${cls.join(' ')}" data-action="goto-day" data-date="${iso}" title="${esc(fmtDateShort(iso))}">
        <span class="strip-day">${d.toLocaleDateString(undefined, { weekday: 'short' }).slice(0, 3)}</span>
        <span class="strip-min">${day ? fmtDuration(mins) : '—'}</span>
        <span class="strip-bar"><span style="width:${day ? Math.max(3, pct) : 0}%"></span></span>
      </button>`);
  }
  return `<div class="strip">${cells.join('')}</div>`;
}

function logText(text) {
  return esc(text).replace(/(^|\s)#([a-z0-9][a-z0-9_-]{0,40})/gi, '$1<span class="tag">#$2</span>');
}

function entryRow(entry, index, opts = {}) {
  const missed = entry.kind === 'missed';
  return `
    <div class="entry ${missed ? 'is-missed' : ''}" data-iso="${state.weekIso}" data-index="${index}">
      <div class="entry-time">${fmtClock(entry.start)}<br>${fmtClock(entry.end)}</div>
      <div class="entry-text">${logText(entry.text)}
        ${opts.deletable ? `<button class="entry-del" data-action="delete-entry" data-iso="${state.weekIso}" data-index="${index}" title="Delete this line">remove</button>` : ''}
      </div>
      <div class="entry-dur">${fmtDuration(entry.minutes)}</div>
    </div>`;
}

function rubricList(items, opts = {}) {
  if (!items.length) {
    return `<p class="small" style="padding:10px 2px">${esc(opts.empty || 'Nothing here yet.')}</p>`;
  }
  const analysisItems = (state.boot.week.analysis.objectives || []);
  return items.map((item, i) => {
    const stat = analysisItems.find((o) => o.slug === item.slug);
    const mins = stat ? stat.total_minutes : 0;
    const estimated = stat && stat.estimated_minutes > 0 && stat.exact_minutes === 0;
    return `
      <div class="rubric-item ${item.done ? 'is-done' : ''}">
        <button class="tick ${item.done ? 'on' : ''}" data-action="toggle-plan" data-section="${opts.section}" data-index="${i}" aria-label="${item.done ? 'Mark not done' : 'Mark done'}">✓</button>
        <div>
          <div class="rubric-text">${esc(item.text)}</div>
          ${opts.showTag ? `<span class="rubric-tag">#${esc(item.slug)}</span>` : ''}
        </div>
        <div class="rubric-min">
          ${mins ? `<span class="${estimated ? 'est' : ''}">${estimated ? '~' : ''}${fmtDuration(mins)}</span>` : (item.done ? 'done' : '—')}
        </div>
      </div>`;
  }).join('');
}

function addRow(section, placeholder) {
  return `
    <div class="row" style="padding:8px 2px;gap:8px">
      <input class="field" data-add="${section}" placeholder="${esc(placeholder)}" style="padding:7px 10px;font-size:13.5px">
      <button class="btn ghost tiny" data-action="add-plan" data-section="${section}">Add</button>
    </div>`;
}

function viewToday(boot) {
  const week = boot.week;
  const today = boot.today;
  const allEntries = week.entries.map((e, i) => ({ ...e, _i: i }));
  const todays = allEntries.filter((e) => e.date === today);
  const logged = todays.filter((e) => e.kind !== 'missed').reduce((a, e) => a + e.minutes, 0);
  const plan = week.plan;
  const staleToday = plan.today_date && plan.today_date !== today;
  const weekDone = plan.week.filter((i) => i.done).length;

  const onboarding = !plan.written ? `
    <section class="empty">
      <div class="eyebrow">Start here</div>
      <h2>What is this week for?</h2>
      <p>Four minutes on Monday. This becomes the only standard the report grades you against —
         the app has no opinion of its own about what counts as productive.</p>
      <div class="steps">
        <div class="step"><div class="step-num">01</div><div class="step-body"><h3>One month goal</h3><p>What November is for, in your words.</p></div></div>
        <div class="step"><div class="step-num">02</div><div class="step-body"><h3>Two or three objectives for this week</h3><p>Small enough to be finished, specific enough to be written in one line.</p></div></div>
        <div class="step"><div class="step-num">03</div><div class="step-body"><h3>Today's tasks</h3><p>What today is actually for. You can change it every morning.</p></div></div>
      </div>
      <div class="row" style="margin-top:18px">
        <button class="btn accent" data-action="start-plan">Write the plan</button>
        <span class="small">Saved as plain text in <span class="mono">${esc(boot.data_dir)}</span></span>
      </div>
    </section>` : '';

  return `
    <header class="view-head">
      <div>
        <div class="eyebrow">${esc(fmtDateLong(today))}</div>
        <h1>Today</h1>
        <div class="sub">${todays.filter((e) => e.kind !== 'missed').length} entries · ${fmtDuration(logged)} on the record
          ${boot.due.paused ? ` · <span style="color:var(--warn)">${esc(pausedLabel(boot.due.paused))}</span>` : ''}</div>
      </div>
      <div class="row">
        <button class="btn ghost" data-action="log-manual">Add a line</button>
        <button class="btn" data-action="checkin-now">What did you do?</button>
      </div>
    </header>

    <div class="stack gap-28">
      <div class="statusline">
        <span class="dot ${boot.due.due ? 'waiting' : boot.due.paused ? 'paused' : ''}"></span>
        <span>${boot.due.due
          ? 'A question is waiting'
          : boot.due.paused
            ? esc(pausedLabel(boot.due.paused))
            : `Next question ${esc(fmtRelative(boot.due.next_due_at))} · every ${boot.settings.interval_minutes} min`}</span>
        <span class="spacer"></span>
        <span class="rail-actions">
          <button class="mini ${boot.settings.deep_work ? 'is-on' : ''}" data-action="toggle-deepwork">Deep Work</button>
          <button class="mini ${boot.settings.muted ? 'is-on' : ''}" data-action="toggle-mute">Mute</button>
        </span>
      </div>

      ${onboarding}
      ${weekStrip(week)}

      <section>
        <div class="spread" style="margin-bottom:6px">
          <h2>Today's tasks</h2>
          <span class="small">${plan.week.length ? `${weekDone} of ${plan.week.length} objectives done` : ''}</span>
        </div>
        ${staleToday ? `
          <div class="callout" style="margin:10px 0">
            Yesterday's list is still here (<span class="mono">${esc(plan.today_date)}</span>).
            <button class="btn link" data-action="carry-over">Carry ${plan.today.filter((i) => !i.done).length || 'them'} over to today</button>
          </div>` : ''}
        <div class="rubric">
          ${rubricList(staleToday ? [] : plan.today, { section: 'today', empty: 'No tasks for today. The week objectives are what get graded — these are just for today.' })}
        </div>
        ${addRow('today', 'Add a task for today…')}
      </section>

      <section>
        <div class="spread" style="margin-bottom:6px">
          <h2>What this week is for</h2>
          <span class="small">${esc(plan.month_label || '')}</span>
        </div>
        <div class="rubric">
          ${rubricList(plan.week, { section: 'week', showTag: true, empty: 'No objectives yet. Two or three is enough — this list is the rubric you get graded against.' })}
        </div>
        ${addRow('week', 'Add an objective for this week…')}
        <div style="margin-top:18px">
          <div class="eyebrow" style="margin-bottom:6px">The month</div>
          <div class="rubric">${rubricList(plan.month, { section: 'month', showTag: true, empty: 'Nothing for the month yet.' })}</div>
        </div>
        ${addRow('month', 'Add a goal for the month…')}
      </section>

      <section>
        <div class="spread" style="margin-bottom:10px">
          <h2>The log</h2>
          ${todays.length ? `<span class="small">${todays.filter((e) => e.kind !== 'missed').length} entries · ${fmtDuration(logged)}</span>` : ''}
        </div>
        ${state.addOpen ? `
          <div class="sheet" style="margin-bottom:12px"><div class="add-form">
            <div><label class="label">Date</label><input class="field" type="date" id="add-date" value="${today}"></div>
            <div><label class="label">From</label><input class="field" type="time" id="add-start" value="09:00"></div>
            <div class="entry-text-field"><label class="label">What you did</label><input class="field" id="add-text" placeholder="One line"></div>
            <div><label class="label">To</label><input class="field" type="time" id="add-end" value="10:30"></div>
            <div style="grid-column:1/-1"><button class="btn tiny" data-action="save-manual">Save the line</button>
              <button class="btn link tiny" data-action="cancel-manual" style="margin-left:10px">Cancel</button></div>
          </div></div>` : ''}
        ${todays.length ? `
          <div class="sheet"><div class="sheet-body">
            ${todays.map((e) => entryRow(e, e._i, { deletable: true })).join('')}
          </div></div>` : `
          <div class="empty" style="border-left-color:var(--rule-strong)">
            <h3 style="margin-bottom:4px">Nothing on the record today</h3>
            <p style="margin:0">The next question comes ${boot.due.paused ? 'when you unpause' : esc(fmtRelative(boot.due.next_due_at))}.
            You can answer it early — the span is filled in for you.</p>
          </div>`}
      </section>

      <section class="small" style="color:var(--faint);line-height:1.7">
        Everything above is one text file: <span class="mono">${esc(week.log_path)}</span><br>
        Plan: <span class="mono">${esc(week.plan_path)}</span>
      </section>
    </div>`;
}

function viewWeek(boot) {
  const week = boot.week;
  const a = week.analysis;
  const byDay = {};
  week.entries.forEach((e, i) => { (byDay[e.date] = byDay[e.date] || []).push({ ...e, _i: i }); });
  const days = Object.keys(byDay).sort();
  const isCurrent = week.iso === boot.current_week;
  const startLabel = fmtDateShort(week.start).replace(/^\w+, /, '');
  const endLabel = fmtDateShort(week.end);
  const prev = new Date(new Date(week.start + 'T12:00:00').getTime() - 86400000).toISOString().slice(0, 10);
  const next = new Date(new Date(week.end + 'T12:00:00').getTime() + 86400000).toISOString().slice(0, 10);
  const hasNext = next <= boot.today || !isCurrent;

  return `
    <header class="view-head">
      <div>
        <div class="eyebrow">Week ${week.iso.split('-W')[1]} · ${esc(startLabel)} – ${esc(endLabel)}</div>
        <h1>The week</h1>
        <div class="sub">${fmtDuration(a.logged_minutes)} logged across ${a.covered_days} of ${a.elapsed_days} days
          ${a.missed ? ` · ${a.missed} unanswered` : ''}</div>
      </div>
      <div class="row">
        <button class="btn ghost tiny" data-action="goto-week" data-date="${prev}">←</button>
        ${!isCurrent ? `<button class="btn ghost tiny" data-action="goto-week" data-date="${boot.today}">This week</button>` : ''}
        <button class="btn ghost tiny" data-action="goto-week" data-date="${next}" ${hasNext ? '' : 'disabled'}>→</button>
      </div>
    </header>

    <div class="stack gap-28">
      <div class="stats">
        <div class="stat"><div class="stat-num">${fmtDuration(a.logged_minutes)}</div><div class="stat-label">on the record</div></div>
        <div class="stat"><div class="stat-num">${a.components.completion ?? '—'}<small>/100</small></div><div class="stat-label">plan completion</div></div>
        <div class="stat"><div class="stat-num">${a.components.alignment ?? '—'}<small>/100</small></div><div class="stat-label">time on plan</div></div>
        <div class="stat"><div class="stat-num">${a.components.coverage ?? '—'}<small>/100</small></div><div class="stat-label">record coverage</div></div>
      </div>

      ${a.objectives.length ? `
      <section>
        <h2 style="margin-bottom:10px">Against the plan</h2>
        <div class="sheet"><div class="sheet-body" style="padding:4px 16px">
          ${a.objectives.map((o) => `
            <div class="rubric-item">
              <div class="tick ${o.done || o.state === 'tagged' ? 'on' : ''}" style="cursor:default">${o.done || o.state === 'tagged' ? '✓' : ''}</div>
              <div>
                <div class="rubric-text">${esc(o.text)}</div>
                <span class="rubric-tag">#${esc(o.slug)} · ${o.kind}</span>
              </div>
              <div class="rubric-min">
                ${o.total_minutes ? `<span class="${o.exact_minutes ? '' : 'est'}">${o.exact_minutes ? '' : '~'}${fmtDuration(o.total_minutes)}</span>` : 'nothing'}
              </div>
            </div>`).join('')}
        </div></div>
        <p class="small" style="margin-top:8px">~ means the time was matched by words, not by hashtag. Tag a check-in with
          <span class="mono">#${esc(a.objectives[0].slug)}</span> and the credit becomes exact.</p>
      </section>` : ''}

      ${a.distractions.length ? `
      <section>
        <h2 style="margin-bottom:10px">Where the rest went</h2>
        <div class="hairline-list">
          ${a.distractions.map((d) => `
            <div class="spread" style="padding:9px 2px">
              <span style="font-size:14px">${esc(d.category)}</span>
              <span class="mono small">${fmtDuration(d.minutes)} · ${d.count} check-in${d.count === 1 ? '' : 's'}</span>
            </div>`).join('')}
        </div>
      </section>` : ''}

      <section>
        <div class="spread" style="margin-bottom:10px">
          <h2>The log, day by day</h2>
          <span class="small">${week.entries.length} lines</span>
        </div>
        ${days.length ? days.map((day) => {
          const list = byDay[day];
          const mins = list.filter((e) => e.kind !== 'missed').reduce((s, e) => s + e.minutes, 0);
          return `
            <div class="day-block">
              <div class="day-head">
                <span class="day-name">${esc(fmtDateLong(day))}</span>
                <span class="day-meta">${fmtDuration(mins)}</span>
              </div>
              <div class="sheet" style="border-top:none;border-top-left-radius:0;border-top-right-radius:0">
                <div class="sheet-body">${list.map((e) => entryRow(e, e._i, { deletable: true })).join('')}</div>
              </div>
            </div>`;
        }).join('') : `
          <div class="empty" style="border-left-color:var(--rule-strong)">
            <h3>No entries this week</h3>
            <p style="margin:0">Nothing was written down, so there is no week to read back.</p>
          </div>`}
      </section>

      ${week.report ? `
      <section>
        <div class="spread">
          <div><h2>Sunday report</h2><p class="small">Written ${esc(fmtRelative(week.report.generated_at))}</p></div>
          <div class="row"><span class="score-num" style="font-size:40px">${week.report.score ?? '—'}</span><span class="small">/10</span></div>
        </div>
        <div class="row" style="margin-top:10px"><button class="btn ghost tiny" data-action="open-report">Read it</button></div>
      </section>` : ''}
    </div>`;
}

function viewReport(boot) {
  const week = boot.week;
  const a = week.analysis;
  const report = state.report && state.report.week === week.iso ? state.report : week.report;
  const score = report ? report.score : a.score;
  const comp = a.components;
  const isCurrent = week.iso === boot.current_week;

  const bars = `
    <div class="bars">
      ${[['plan completion', comp.completion], ['time on plan', comp.alignment], ['record coverage', comp.coverage], ['time off the rails', comp.focus]]
        .map(([label, value]) => `
          <div class="bar-row">
            <span>${label}</span>
            <span class="bar-track"><span class="bar-fill ${value != null && value < 50 ? 'low' : ''}" style="width:${value ?? 0}%"></span></span>
            <span class="bar-val">${value ?? '—'}</span>
          </div>`).join('')}
    </div>`;

  const tabs = `
    <div class="tabs">
      <button class="tab ${state.tab === 'week' ? 'is-on' : ''}" data-action="tab" data-tab="week">This week</button>
      <button class="tab ${state.tab === 'month' ? 'is-on' : ''}" data-action="tab" data-tab="month">The month</button>
    </div>`;

  if (state.tab === 'month') {
    const m = state.monthReport;
    const summary = m ? m.summary : null;
    return `
      <header class="view-head">
        <div><div class="eyebrow">${esc(boot.months[0] || new Date().toISOString().slice(0, 7))}</div><h1>Report</h1></div>
        <div class="row">
          <button class="btn ghost" data-action="grade-month">${m ? 'Re-grade the month' : 'Grade the month'}</button>
        </div>
      </header>
      ${tabs}
      ${m ? `
        <div class="score-block" style="margin-bottom:24px">
          <div class="score-num ${summary.average_score == null ? 'is-none' : ''}">${summary.average_score ?? '—'}<span class="of">/10</span></div>
          <div class="small" style="max-width:44ch">
            ${summary.weeks_scored} graded week${summary.weeks_scored === 1 ? '' : 's'} ·
            ${fmtDuration(summary.total_logged_minutes)} logged ·
            ${summary.objectives_met}/${summary.objectives_total} plan items got time
            ${summary.trend != null ? ` · trend ${summary.trend > 0 ? '+' : ''}${summary.trend}` : ''}
          </div>
        </div>
        <article class="prose">${md(reportBody(m.markdown))}</article>` : `
        <div class="empty">
          <h2>No monthly report yet</h2>
          <p>It reads every recorded week of the month and tells you what you achieved, how the weeks compared,
             the habit that kept costing you, and a plan for next month. Written from your own files.</p>
          <button class="btn accent" data-action="grade-month">Grade the month</button>
        </div>`}`;
  }

  return `
    <header class="view-head">
      <div>
        <div class="eyebrow">Week ${week.iso.split('-W')[1]} · ${esc(fmtDateShort(week.start))} – ${esc(fmtDateShort(week.end))}</div>
        <h1>Report</h1>
        <div class="sub">${a.answered} answers, ${a.missed} misses · ${fmtDuration(a.logged_minutes)} on the record
          ${report ? ` · graded ${esc(fmtRelative(report.generated_at))}` : ''}</div>
      </div>
      <div class="row">
        <div class="seg" role="group" aria-label="Tone">
          ${['gentle', 'honest', 'brutal'].map((t) => `
            <button class="${boot.settings.tone === t ? 'is-on' : ''}" data-action="set-tone" data-tone="${t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join('')}
        </div>
        <button class="btn accent" data-action="grade-week">${report ? 'Re-grade' : 'Grade the week'}</button>
      </div>
    </header>
    ${tabs}

    <div class="score-block" style="margin-bottom:26px">
      <div class="score-num ${score == null ? 'is-none' : ''}">${score ?? '—'}<span class="of">/10</span></div>
      ${bars}
    </div>

    ${report ? `
      <article class="prose">${md(reportBody(report.markdown))}</article>
      <p class="small" style="margin-top:22px;color:var(--faint)">
        Saved at <span class="mono">${esc(week.report_path)}</span> ·
        ${report.source === 'llm' ? 'written by a model you chose, with your key' : 'written on your machine, no model, no key'}
      </p>` : `
      <div class="empty">
        <h2>${isCurrent ? 'Your week is not over, but it can be graded now' : 'This week was never graded'}</h2>
        <p>${a.has_plan
          ? 'The report compares the log with the plan you wrote, gives it a score out of 10, names the one pattern behind the gap, and leaves you one instruction for next week.'
          : 'There is no plan for this week, so there is nothing to grade it against. Write down what the week was for first — that plan is the only rubric this app will use.'}</p>
        <div class="row">
          ${a.has_plan
            ? '<button class="btn accent" data-action="grade-week">Grade the week</button>'
            : '<button class="btn accent" data-action="start-plan">Write the plan</button>'}
          <span class="small">Runs locally. Takes under a second.</span>
        </div>
      </div>`}

    <section style="margin-top:40px">
      <h2 style="margin-bottom:10px">Earlier weeks</h2>
      ${boot.weeks.filter((w) => w !== week.iso).length ? `
        <div class="hairline-list">
          ${boot.weeks.filter((w) => w !== week.iso).slice(0, 12).map((w) => `
            <button class="spread" style="width:100%;padding:9px 2px;text-align:left" data-action="goto-week" data-date="${w}-01">
              <span>Week ${w.split('-W')[1]}, ${w.split('-')[0]}</span>
              <span class="mono small">open →</span>
            </button>`).join('')}
        </div>` : '<p class="small">Nothing yet. This is the first week.</p>'}
    </section>`;
}

function viewSettings(boot) {
  const s = state.settingsDraft || boot.settings;
  const keySet = boot.settings.llm_api_key_set;
  return `
    <header class="view-head">
      <div><div class="eyebrow">Version ${esc(boot.version)} · MIT</div><h1>Settings</h1>
      <div class="sub">Nothing leaves this machine unless you choose a model grader and paste a key.</div></div>
    </header>

    <div class="settings-grid">
      <section class="setting">
        <div class="setting-head"><h2>How often it asks</h2><span class="mono small">${esc(s.interval_minutes)} min</span></div>
        <p class="setting-desc">Ninety minutes is the suggested start. Set it to fifteen on day one and it will drive you
          insane; set it to ninety and turn on Deep Work when you need a long run.</p>
        <div class="inline-fields">
          <div>
            <label class="label" for="interval">Every</label>
            <input class="field num-input" id="interval" type="number" min="5" max="480" step="5" value="${esc(s.interval_minutes)}" data-setting="interval_minutes">
            <span class="small">minutes</span>
          </div>
          <div class="row wrap">
            ${[30, 60, 90, 120].map((v) => `<button class="btn ghost tiny" data-action="preset-interval" data-value="${v}">${v}m</button>`).join('')}
          </div>
        </div>
        <div class="inline-fields" style="margin-top:14px">
          <div><label class="label" for="active_start">Asks between</label>
            <input class="field" id="active_start" type="time" value="${esc(s.active_start)}" data-setting="active_start"></div>
          <div><label class="label" for="active_end">&nbsp;</label>
            <input class="field" id="active_end" type="time" value="${esc(s.active_end)}" data-setting="active_end"></div>
          <label class="row" style="gap:7px;padding-bottom:9px">
            <input type="checkbox" data-setting="weekday_only" ${s.weekday_only ? 'checked' : ''}> <span class="small">Weekdays only</span>
          </label>
        </div>
      </section>

      <section class="setting">
        <div class="setting-head"><h2>How it says it</h2></div>
        <p class="setting-desc">The findings and the score are identical in all three. Only the delivery changes —
          so Gentle is not an easier grade, it is the same news without the lecture.</p>
        <div class="seg">
          ${['gentle', 'honest', 'brutal'].map((t) => `
            <button class="${s.tone === t ? 'is-on' : ''}" data-action="set-tone" data-tone="${t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join('')}
        </div>
        <p class="small" style="margin-top:10px">${
          s.tone === 'gentle' ? 'Reports what happened and the score, without judgement in how it says it.'
          : s.tone === 'honest' ? 'Direct and plain. The default.'
          : 'Short and blunt. No encouragement, no cushioning.'}</p>
      </section>

      <section class="setting">
        <div class="setting-head"><h2>Who writes the report</h2></div>
        <p class="setting-desc">The built-in analyser is deterministic and runs offline: it counts what the log says,
          compares it with the plan, and writes the report. No key, no cost, nothing sent anywhere.
          A model grader writes prose that reads a little more like a person — it needs a key, and the week's log goes
          straight to the provider you pick.</p>
        <div class="seg" style="margin-bottom:14px">
          <button class="${s.grader === 'local' ? 'is-on' : ''}" data-action="set-grader" data-grader="local">On this machine</button>
          <button class="${s.grader === 'llm' ? 'is-on' : ''}" data-action="set-grader" data-grader="llm">A model, with my key</button>
        </div>
        ${s.grader === 'llm' ? `
          <div class="stack gap-14">
            <div class="inline-fields">
              <div><label class="label">Provider</label>
                <select class="field" data-setting="llm_provider">
                  ${['openai', 'anthropic', 'gemini', 'ollama'].map((p) => `
                    <option value="${p}" ${s.llm_provider === p ? 'selected' : ''}>${
                      { openai: 'OpenAI / any compatible', anthropic: 'Anthropic', gemini: 'Google Gemini', ollama: 'Ollama (local)' }[p]}</option>`).join('')}
                </select></div>
              <div><label class="label">Model</label>
                <input class="field" data-setting="llm_model" value="${esc(s.llm_model)}" placeholder="${esc(s.llm_provider === 'ollama' ? 'llama3.1' : 'gpt-4o-mini')}"></div>
            </div>
            <div><label class="label">API key ${keySet ? '· saved, leave blank to keep it' : ''}</label>
              <input class="field" type="password" data-setting="llm_api_key" value="${esc(s.llm_api_key || '')}"
                     placeholder="${keySet ? '•••••••• saved' : 'paste your key'}" autocomplete="off"></div>
            <div><label class="label">Base URL (optional — for DeepSeek, Groq, OpenRouter, LM Studio)</label>
              <input class="field" data-setting="llm_base_url" value="${esc(s.llm_base_url)}" placeholder="${esc(s.llm_provider === 'openai' ? 'https://api.deepseek.com/v1' : 'leave blank')}"></div>
            <div class="row">
              <button class="btn ghost tiny" data-action="save-settings">Save</button>
              <button class="btn ghost tiny" data-action="test-key">Test the key</button>
              ${keySet ? '<span class="small">A report costs a few cents, paid to the provider.</span>' : ''}
            </div>
          </div>` : ''}
      </section>

      <section class="setting">
        <div class="setting-head"><h2>Your files</h2></div>
        <p class="setting-desc">Your log, plan and reports are ordinary markdown files in a folder you choose. Open,
          edit or delete them without this app. Put that folder in Syncthing, iCloud or git and your log follows you
          to another computer.</p>
        <div class="inline-fields">
          <input class="field" style="min-width:280px;flex:1" id="data_dir" value="${esc(boot.data_dir)}" data-setting="data_dir">
          <button class="btn ghost tiny" data-action="save-settings">Move</button>
        </div>
        <div class="row wrap" style="margin-top:14px">
          <a class="btn ghost tiny" href="/api/export?format=md" download>Export markdown</a>
          <a class="btn ghost tiny" href="/api/export?format=json" download>Export JSON</a>
          <button class="btn ghost tiny" data-action="notify-permission">Desktop notifications</button>
        </div>
      </section>

      <section class="setting">
        <div class="setting-head"><h2>About</h2></div>
        <p class="setting-desc">What I Did ${esc(boot.version)} · MIT licence · no account, no telemetry, no cloud.
          Run <span class="mono">whatidid serve</span> on any computer with Python; the same folder works on Windows,
          macOS and Linux.</p>
        <p class="small" style="font-family:var(--mono)">
          interval ${esc(s.interval_minutes)}m · ${esc(s.active_start)}–${esc(s.active_end)} ·
          tone ${esc(s.tone)} · grader ${esc(s.grader)}${s.grader === 'llm' ? ` (${esc(s.llm_provider)}/${esc(s.llm_model)})` : ''}
        </p>
      </section>
    </div>`;
}

function pausedLabel(reason) {
  return { 'deep-work': 'Deep Work — questions held', muted: 'Muted', 'off-hours': 'Outside your hours' }[reason] || reason;
}

/* ------------------------------------------------------------- the pop-up */
function openPop(force) {
  if (state.popOpen) return;
  const due = state.boot.due;
  if (!force && !due.due) return;
  state.popOpen = true;

  const minutes = due.ask_minutes || state.boot.settings.interval_minutes;
  const span = `${fmtClock((due.ask_start || '').slice(11, 16))} → ${fmtClock((due.ask_end || '').slice(11, 16))}`;
  const plan = state.boot.week.plan;
  const chips = [...(plan.today || []), ...(plan.week || [])]
    .slice(0, 8)
    .map((i) => `<button class="chip" data-action="chip" data-slug="${esc(i.slug)}">#${esc(i.slug)}</button>`)
    .join('');

  const root = $('#modal-root');
  root.innerHTML = `
    <div class="pop" id="pop" role="dialog" aria-modal="true" aria-labelledby="pop-q">
      <div class="pop-card">
        <div class="eyebrow">${force ? 'Logging now' : 'Check-in'}</div>
        <h2 class="pop-q" id="pop-q">What did you do in the last ${fmtDuration(minutes)}?</h2>
        <span class="pop-span">${esc(span)} · one line, six seconds</span>
        <textarea id="pop-input" placeholder="Drafted the client proposal, sent it for review" spellcheck="true"></textarea>
        ${chips ? `<div class="chips">${chips}</div>` : ''}
        <div class="pop-actions">
          <button class="btn accent" data-action="pop-save">Save it <span class="kbd" style="border-color:rgba(255,255,255,.4);color:inherit;background:transparent">↵</span></button>
          <button class="btn ghost" data-action="pop-snooze">Snooze 15m</button>
          <span class="spacer"></span>
          <button class="btn link" data-action="pop-skip">Skip</button>
          <button class="btn link" data-action="pop-deepwork">Deep Work</button>
        </div>
        <div class="pop-foot">
          <span>Esc snoozes · <span class="kbd">#</span> tags credit an objective exactly</span>
        </div>
      </div>
    </div>`;
  const input = $('#pop-input');
  input.focus();
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveCheckin(); }
  });
  document.addEventListener('keydown', popKeys);
  notify(`What did you do in the last ${fmtDuration(minutes)}?`);
}

function closePop() {
  state.popOpen = false;
  state.popBusy = false;
  $('#modal-root').innerHTML = '';
  document.removeEventListener('keydown', popKeys);
  document.title = 'What I Did';
}

function popKeys(e) {
  if (e.key === 'Escape') { e.preventDefault(); snooze(); }
}

async function saveCheckin() {
  if (state.popBusy) return;
  const input = $('#pop-input');
  const text = (input?.value || '').trim();
  if (!text) { input?.focus(); toast('One line is enough, but it has to be a line.', true); return; }
  state.popBusy = true;
  try {
    await post('/api/checkin', { text });
    closePop();
    toast('Written down.');
    await refresh();
  } catch (err) {
    state.popBusy = false;
    toast(err.message, true);
  }
}

async function snooze() {
  try { await post('/api/checkin/snooze', { minutes: 15 }); } catch (e) { /* offline: close anyway */ }
  state.snoozedUntil = Date.now() + 15000;
  closePop();
  await refresh();
}

async function skipQuestion() {
  try {
    await post('/api/checkin/skip', {});
    closePop();
    toast('Skipped. The gap is on the record.');
    await refresh();
  } catch (err) { toast(err.message, true); }
}

async function deepWorkOn() {
  await post('/api/deepwork', { on: true });
  closePop();
  toast('Deep Work on. Questions held until you come back up.');
  await refresh();
}

/* --------------------------------------------------------------- actions */
async function togglePlan(section, index) {
  const plan = state.boot.week.plan;
  const payload = { week: state.weekIso, month: plan.month, week_items: plan.week, today: plan.today, today_date: plan.today_date };
  const list = section === 'week' ? payload.week_items : section === 'month' ? payload.month : payload.today;
  if (!list[index]) return;
  list[index] = { ...list[index], done: !list[index].done };
  await post('/api/plan', payload);
  await refresh();
}

async function addPlanItem(section) {
  const input = document.querySelector(`[data-add="${section}"]`);
  const text = (input?.value || '').trim();
  if (!text) return;
  const plan = state.boot.week.plan;
  const payload = { week: state.weekIso, month: plan.month, week_items: plan.week, today: plan.today, today_date: plan.today_date };
  const list = section === 'week' ? payload.week_items : section === 'month' ? payload.month : payload.today;
  list.push({ text, done: false });
  if (section === 'today') payload.today_date = state.boot.today;
  await post('/api/plan', payload);
  await refresh();
  const next = document.querySelector(`[data-add="${section}"]`);
  next?.focus();
}

async function deleteEntry(iso, index) {
  const row = document.querySelector(`.entry[data-iso="${iso}"][data-index="${index}"]`);
  if (row) row.style.opacity = '0.4';
  try {
    await del(`/api/entries/${iso}/${index}`);
    await refresh();
  } catch (err) { toast(err.message, true); await refresh(); }
}

async function gradeWeek() {
  const btn = document.querySelector('[data-action="grade-week"]');
  if (btn) { btn.disabled = true; btn.textContent = 'Grading…'; }
  try {
    const result = await post('/api/report/week', { week: state.weekIso });
    state.report = { ...result.report, week: state.weekIso, score: result.score, source: result.source, markdown: result.markdown };
    render();
    if (result.error) toast(`Model grader failed, used the offline analyser: ${result.error}`, true);
    else toast(`Graded ${result.score ?? '—'}/10.`);
  } catch (err) {
    toast(err.message, true);
    render();
  }
}

async function loadReport() {
  if (state.tab === 'month') {
    try {
      const data = await api(`/api/report/month`);
      state.monthReport = data.report ? { markdown: data.report.markdown, summary: data.summary } : null;
    } catch (e) { state.monthReport = null; }
  }
}

async function gradeMonth() {
  const btn = document.querySelector('[data-action="grade-month"]');
  if (btn) { btn.disabled = true; btn.textContent = 'Grading…'; }
  try {
    const result = await post('/api/report/month', {});
    state.monthReport = { markdown: result.markdown, summary: result.summary };
    render();
    toast('Month graded.');
  } catch (err) { toast(err.message, true); render(); }
}

async function saveSettings() {
  const draft = state.settingsDraft;
  const payload = { ...draft };
  try {
    const res = await put('/api/settings', payload);
    state.settingsDraft = { ...res.settings, llm_api_key: '' };
    toast('Saved.');
    await boot(state.weekIso);
    if (state.view === 'settings') render();
  } catch (err) { toast(err.message, true); }
}

async function setSetting(key, value, { immediate = true } = {}) {
  state.settingsDraft[key] = value;
  if (immediate) {
    try {
      const res = await put('/api/settings', { [key]: value });
      state.boot.settings = res.settings;
      state.settingsDraft = { ...res.settings, llm_api_key: state.settingsDraft.llm_api_key };
      updateClock();
    } catch (err) { toast(err.message, true); }
  }
}

async function setTone(tone) {
  state.settingsDraft.tone = tone;
  try {
    const res = await put('/api/settings', { tone });
    state.boot.settings = res.settings;
  } catch (err) { toast(err.message, true); }
  render();
}

async function gradeWithNewTone() {
  if (state.boot.week.report) await gradeWeek();
}

/* ----------------------------------------------------------------- clock */
function updateClock() {
  if (!state.boot) return;
  const due = state.boot.due;
  const el = $('.clock');
  const value = $('#clock-value');
  const label = $('#clock-label');
  if (!el || !value) return;
  el.classList.toggle('is-due', !!due.due);
  const dw = $('.rail-actions .mini:first-child');
  const mute = $('#btn-mute');
  dw?.classList.toggle('is-on', state.boot.settings.deep_work);
  mute?.classList.toggle('is-on', state.boot.settings.muted);

  if (due.due) {
    label.textContent = 'Question waiting';
    value.textContent = 'answer it';
  } else if (due.paused) {
    label.textContent = pausedLabel(due.paused);
    value.textContent = '—';
  } else {
    label.textContent = 'Next question';
    value.textContent = fmtRelative(due.next_due_at);
  }
}

async function poll() {
  if (state.popOpen) return;
  try {
    const due = await api('/api/due');
    if (state.boot) state.boot.due = due;
    updateClock();
    if (due.due && !state.popOpen && Date.now() > state.snoozedUntil) openPop(false);
    if (due.due && document.hidden) {
      const t = `● What did you do in the last ${fmtDuration(due.ask_minutes)}?`;
      if (document.title !== t) document.title = t;
    }
  } catch (e) { /* server restarting */ }
}

/* ---------------------------------------------------------- notifications */
async function notify(body) {
  if (!('Notification' in window) || Notification.permission !== 'granted' || !document.hidden) return;
  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg) reg.showNotification('What I Did', { body, tag: 'checkin', renotify: true });
    else new Notification('What I Did', { body, tag: 'checkin' });
  } catch (e) { /* notifications are a bonus, never a requirement */ }
}

async function requestNotifications() {
  if (!('Notification' in window)) { toast('This browser has no notifications.', true); return; }
  const permission = await Notification.requestPermission();
  toast(permission === 'granted' ? 'Notifications on. It can now reach you from a background tab.'
    : 'Notifications blocked. The in-app pop still works.', permission !== 'granted');
}

/* -------------------------------------------------------------- wiring */
document.addEventListener('click', async (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  const action = el.dataset.action;
  try {
    switch (action) {
      case 'checkin-now': openPop(true); break;
      case 'toggle-deepwork': {
        const on = !state.boot.settings.deep_work;
        await post('/api/deepwork', { on });
        await refresh();
        toast(on ? 'Deep Work on. Questions held until you come back up.' : 'Deep Work off.');
        break;
      }
      case 'toggle-mute': {
        const muted = !state.boot.settings.muted;
        await post('/api/mute', { muted });
        await refresh();
        toast(muted ? 'Muted.' : 'Unmuted.');
        break;
      }
      case 'log-manual': state.addOpen = !state.addOpen; render();
        if (state.addOpen) document.getElementById('add-text')?.focus();
        break;
      case 'cancel-manual': state.addOpen = false; render(); break;
      case 'save-manual': {
        const text = ($('#add-text')?.value || '').trim();
        if (!text) { $('#add-text')?.focus(); break; }
        await post('/api/entries', {
          date: $('#add-date')?.value || state.boot.today,
          start: $('#add-start')?.value || '09:00',
          end: $('#add-end')?.value || '10:30',
          text,
        });
        state.addOpen = false;
        await refresh();
        toast('Added to the log.');
        break;
      }
      case 'start-plan': setView('today'); document.querySelector('[data-add="week"]')?.focus(); break;
      case 'toggle-plan': await togglePlan(el.dataset.section, Number(el.dataset.index)); break;
      case 'add-plan': await addPlanItem(el.dataset.section); break;
      case 'carry-over': {
        const plan = state.boot.week.plan;
        await post('/api/plan', {
          week: state.weekIso, month: plan.month, week_items: plan.week,
          today: plan.today.filter((i) => !i.done), today_date: state.boot.today,
        });
        await refresh(); toast('Carried over.'); break;
      }
      case 'delete-entry': await deleteEntry(el.dataset.iso, Number(el.dataset.index)); break;
      case 'grade-week': await gradeWeek(); break;
      case 'grade-month': await gradeMonth(); break;
      case 'open-report': setView('report'); break;
      case 'tab': state.tab = el.dataset.tab; await loadReport(); render(); break;
      case 'set-tone': await setTone(el.dataset.tone); break;
      case 'set-grader': state.settingsDraft.grader = el.dataset.grader; await setSetting('grader', el.dataset.grader); render(); break;
      case 'preset-interval': state.settingsDraft.interval_minutes = Number(el.dataset.value); await setSetting('interval_minutes', Number(el.dataset.value)); render(); break;
      case 'save-settings': await saveSettings(); break;
      case 'test-key': {
        el.disabled = true; el.textContent = 'Testing…';
        const res = await fetch('/api/settings/test-key', { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        el.disabled = false; el.textContent = 'Test the key';
        toast(data.ok ? `Key works. It replied with ${data.score}/10 on a sample week.` : `Failed: ${data.error || res.status}`, !data.ok);
        break;
      }
      case 'notify-permission': await requestNotifications(); break;
      case 'goto-week': {
        const iso = el.dataset.date;
        state.weekIso = iso;
        await boot(iso);
        break;
      }
      case 'goto-day': state.weekIso = weekForDate(el.dataset.date); await boot(state.weekIso); setView('week'); break;
      case 'pop-save': await saveCheckin(); break;
      case 'pop-snooze': await snooze(); break;
      case 'pop-skip': await skipQuestion(); break;
      case 'pop-deepwork': await deepWorkOn(); break;
      case 'chip': {
        const input = $('#pop-input');
        if (!input) break;
        const tag = ` #${el.dataset.slug}`;
        if (!input.value.includes(el.dataset.slug)) input.value = input.value.trim() + tag + ' ';
        input.focus();
        el.classList.add('is-used');
        break;
      }
    }
  } catch (err) {
    toast(err.message || String(err), true);
  }
});

document.addEventListener('keydown', async (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
  if (typing) return;
  if (e.key === 'n' && !e.metaKey && !e.ctrlKey) { openPop(true); }
  if (e.key === 'd' && !e.metaKey && !e.ctrlKey) {
    await post('/api/deepwork', { on: !state.boot.settings.deep_work });
    await refresh();
  }
  if (e.key >= '1' && e.key <= '4') {
    setView(['today', 'week', 'report', 'settings'][Number(e.key) - 1]);
  }
});

document.addEventListener('change', async (e) => {
  const el = e.target.closest('[data-setting]');
  if (!el) return;
  const key = el.dataset.setting;
  let value = el.type === 'checkbox' ? el.checked : el.value;
  if (['interval_minutes'].includes(key)) value = Number(value);
  if (key === 'llm_api_key') { state.settingsDraft[key] = value; return; }
  await setSetting(key, value);
  if (state.view === 'settings') {
    if (key === 'llm_provider') { state.settingsDraft.llm_model = ''; render(); }
  }
});

$('#btn-deepwork')?.addEventListener('click', async () => {
  await post('/api/deepwork', { on: !state.boot.settings.deep_work });
  await refresh();
  toast(state.boot.settings.deep_work ? 'Deep Work on.' : 'Deep Work off. It will ask once about the stretch.');
});

$('#btn-mute')?.addEventListener('click', async () => {
  await post('/api/mute', { muted: !state.boot.settings.muted });
  await refresh();
  toast(state.boot.settings.muted ? 'Muted. Still logging if you log.' : 'Unmuted.');
});

document.querySelectorAll('.nav-item').forEach((b) => {
  b.addEventListener('click', () => setView(b.dataset.view));
});

/* ------------------------------------------------------------------ start */
(function start() {
  boot().then(() => {
    if (state.boot.due.due) setTimeout(() => openPop(false), 900);
    setInterval(poll, 15000);
    setInterval(() => { if (!state.popOpen) updateClock(); }, 30000);
  }).catch((err) => {
    $('#main').innerHTML = `<div class="empty"><h2>Could not reach the server</h2>
      <p>${esc(err.message)}</p><p class="small">Start it with <span class="mono">whatidid</span> and reload.</p></div>`;
  });
})();