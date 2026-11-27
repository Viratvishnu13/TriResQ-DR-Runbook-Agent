'use strict';
// All text reaches the page through textContent (see h()), never innerHTML.

const $ = id => document.getElementById(id);
const app = { meta: null, drills: [], view: null, tab: 'chat', chats: {}, report: null, error: null, busy: false,
  briefs: {}, analysis: {}, draft: { text: '', result: null, loading: false } };

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k in el && k !== 'list') el[k] = v;
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} :
    { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  const data = await res.json();
  if (!res.ok) {
    const e = data.error || { code: res.status, message: 'Request failed' };
    throw new Error(`${e.code}: ${e.message}${Array.isArray(e.details) ? ' — ' + e.details.join('; ') : ''}`);
  }
  return data;
}

async function run(fn) {
  if (app.busy) return;
  app.busy = true; app.error = null;
  try { await fn(); }
  catch (e) {
    app.error = e.message;
    if (app.view) app.view = await api(`/api/drills/${app.view.drill_id}`).catch(() => app.view);
  }
  app.busy = false;
  app.drills = (await api('/api/drills').catch(() => ({ drills: app.drills }))).drills;
  render();
}

/* ---------- formatting ---------- */
const clock = iso => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short' });
function dur(s) {
  if (s === null || s === undefined) return 'not measured';
  const hh = Math.floor(s / 3600), mm = Math.floor(s % 3600 / 60), ss = Math.round(s % 60);
  return (hh ? hh + 'h ' : '') + (hh || mm ? mm + 'm ' : '') + ss + 's';
}
const pct = v => v === null || v === undefined ? '—' : (v * 100).toFixed(1) + '%';
const json = v => JSON.stringify(v, null, 2);
const GOOD = ['met', 'Pass', 'PASS', 'completed', 'success', 'approved', 'accepted', 'healthy', 'ready'];
const BAD = ['missed', 'Fail', 'FAIL', 'failed', 'timed_out', 'rejected', 'unknown', 'rolled_back', 'escalated'];
const mark = v => h('span', { class: GOOD.includes(v) ? 'pass' : BAD.includes(v) ? 'fail' : '' }, v ?? '—');

function table(headers, rows) {
  if (!rows.length) return h('p', { class: 'defn' }, 'None recorded.');
  return h('div', { class: 'scroll' }, h('table', null,
    h('thead', null, h('tr', null, headers.map(x => h('th', null, x)))),
    h('tbody', null, rows.map(r => h('tr', null, r.map(c => h('td', null, c ?? '—')))))));
}
const row = (k, v) => h('div', { class: 'row' }, k, h('b', null, v ?? '—'));
const card = (title, ...body) => h('div', { class: 'card wide' }, h('h4', null, title), ...body);
const button = (label, fn, cls) => h('button', { class: 'btn ' + (cls || ''), type: 'button', onclick: fn }, label);
const field = (id, label, value) => [h('label', { htmlFor: id }, label), h('input', { id, class: 'field', value: value || '', maxLength: 500 })];
const section = (title, ...body) => h('div', { class: 'section' }, h('h3', null, title), ...body);
const kpi = (label, value, sub) => h('div', { class: 'kpi' }, h('div', { class: 'kl' }, label), h('div', { class: 'kv' }, value), h('div', { class: 'ks' }, sub || ''));

/* ---------- actions ---------- */
const openDrill = id => run(async () => { app.view = await api(`/api/drills/${id}`); app.report = null; });

function send(name, args) {
  return run(async () => {
    app.view = await api(`/api/drills/${app.view.drill_id}/commands`,
      { command: name, expected_version: app.view.state_version, args: args || {} });
    app.report = null;
  });
}

function sendText() {
  const input = $('composerInput'), text = input.value.trim();
  if (!text || !app.view) return;
  input.value = '';
  const log = app.chats[app.view.drill_id] ||= [];
  log.push({ who: 'user', text, at: new Date().toISOString() });
  render();
  run(async () => {
    const r = await api(`/api/drills/${app.view.drill_id}/chat`, { text });
    app.view = r.view;
    const flagged = r.guard && !r.guard.passed
      ? `\n\n⚠ Unverified references in this answer: ${[...r.guard.unknown_steps, ...r.guard.unknown_tools, ...r.guard.unknown_citations].join(', ')}` : '';
    log.push({ who: 'agent', text: r.reply + flagged, note: (r.model_error ? r.model_error + ' · ' : '') + 'answered by ' + r.answered_by, at: new Date().toISOString() });
  });
}

/* ---------- chat feed ---------- */
const HIDDEN = new Set(['STEP_READY', 'CHECK_STARTED', 'STEP_COMPLETED', 'ACTION_DISPATCHED']);
const TOOL_EVENTS = new Set(['CHECK_COMPLETED', 'ACTION_COMPLETED', 'ACTION_FAILED', 'ACTION_TIMED_OUT', 'ACTION_UNKNOWN', 'ROLLBACK_COMPLETED', 'ADVISORY_CHECK', 'OPERATOR_REJECTED']);

function envelopeFor(e) {
  const v = app.view;
  const results = [...v.checks, ...v.action_records.map(r => r.result).filter(Boolean)];
  return results.find(x => x.action_id === e.action_id && x.step_id === e.step_id);
}

function bubble(label, color, text, meta) {
  return h('div', { class: 'msg agent' },
    h('div', { class: 'who', style: `color:${color}` }, h('span', { class: 'dot', style: `background:${color}` }), label),
    text, meta ? h('span', { class: 'meta' }, meta) : null);
}

function eventBlock(e) {
  const meta = `${clock(e.timestamp)} · ${e.event_type}`;
  if (TOOL_EVENTS.has(e.event_type)) {
    const env = envelopeFor(e);
    return h('div', { class: 'toolcall op success' },
      h('div', { class: 'tc-head' }, `${e.actor} · SIMULATED ${env ? env.tool : ''} → ${e.status.toUpperCase()}`),
      e.summary,
      env && env.rule ? h('div', { class: 'rule' }, `${env.injected ? '🎛 Your condition · ' : ''}Rule: ${env.rule}`) : null,
      env ? h('details', null, h('summary', null, `structured result · ${env.result_code}`), h('pre', null, json(env))) : null,
      h('span', { class: 'meta' }, '\n' + meta));
  }
  if (e.event_type === 'RUNBOOK_RETRIEVED') {
    const b = app.view.runbook;
    return h('div', { class: 'toolcall search success' }, h('div', { class: 'tc-head' }, 'Knowledge search · local runbook catalogue'),
      `${b.document_id} v${b.version} — ${b.title}\nstatus: ${b.approval_status} · owner: ${b.owner} · last reviewed: ${b.last_reviewed}\n${b.source_uri}`);
  }
  const agents = { 'Drill Coordinator': 'var(--accent)', 'Failover Operator': 'var(--ok)' };
  return bubble(e.actor, agents[e.actor] || 'var(--purple)', e.event_type === 'COMMUNICATION_RECORDED' ? `${e.summary}\n${e.details.draft}\n[${e.details.citation}]` : e.summary, meta);
}

function feed() {
  const v = app.view;
  const items = v.events.filter(e => !HIDDEN.has(e.event_type)).map(e => ({ at: e.timestamp, node: () => eventBlock(e) }));
  for (const m of app.chats[v.drill_id] || []) {
    items.push({ at: m.at, node: () => m.who === 'user' ? h('div', { class: 'msg user' }, m.text) : bubble('Drill Coordinator', 'var(--accent)', m.text, m.note) });
  }
  return items.sort((a, b) => new Date(a.at) - new Date(b.at)).map(i => i.node());
}

/* ---------- action panel: renders only what the backend currently allows ---------- */
function stepDetails(step) {
  return [row('Owner', step.owner), row('Tool', step.tool ? `${step.tool} (SIMULATED)` : 'none'),
    row('Prerequisites', step.prerequisites.join('; ') || '—'), row('Success criteria', step.success_criteria.join('; ')),
    row('Expected result', step.expected_result), row('Risks', step.risks || '—'),
    row('Rollback', step.rollback ? step.rollback.description : 'none'), row('Source', step.source.citation),
    h('details', null, h('summary', null, 'Runbook source text'), h('p', null, step.source.text))];
}

/* ---------- "You control the failure": choose the next simulated condition; the rules decide ---------- */
const CHOICES = {
  action: [['success', 'Succeeds'], ['transient_error', 'Temporary error (retry may be allowed)'], ['permanent_error', 'Permanent error'],
    ['timeout', 'Times out part-way'], ['response_lost_applied', 'Reply lost, but the change happened'], ['response_lost_not_applied', 'Reply lost, nothing changed']],
  health: [['healthy', 'Healthy'], ['degraded', 'Degraded (may recover)'], ['hardware_fault', 'Hardware fault']],
  rollback: [['success', 'Rollback succeeds'], ['failed', 'Rollback fails']]
};
const words = values => Object.entries(values).map(([k, x]) => `${k} = ${x}`).join(', ');

function injectBox() {
  const v = app.view;
  if (!v.controls.some(c => c.command === 'inject')) return null;
  const rollback = v.status === 'rolling_back' || !!(v.approval && v.approval.is_rollback);
  const tool = rollback ? 'rollback_step' : v.current_step.tool;
  const number = (id, label, value, max) => [h('label', { htmlFor: id }, label), h('input', { id, class: 'field', type: 'number', min: 0, max, step: 'any', value })];
  let inputs, read;
  if (tool === 'check_replication') {
    inputs = [...number('injLag', 'Replication lag, seconds (limit 10)', '45', 3600), ...number('injAge', 'Recovery point age, seconds (RPO 1800)', '600', 86400)];
    const num = id => ($(id).value.trim() === '' ? null : Number($(id).value));
    read = () => ({ lag_seconds: num('injLag'), recovery_point_age_seconds: num('injAge') });
  } else {
    const kind = tool === 'check_health' ? 'health' : rollback ? 'rollback' : 'action';
    inputs = [h('label', { htmlFor: 'injChoice' }, `What should the next ${tool} do?`),
      h('select', { id: 'injChoice', class: 'field' }, CHOICES[kind].map(([value, label], i) => h('option', { value, selected: i === CHOICES[kind].length - 1 && kind !== 'action' }, label)))];
    read = () => ({ [kind === 'health' ? 'health' : 'outcome']: $('injChoice').value });
  }
  return h('details', { class: 'inject', open: !!v.injection },
    h('summary', null, v.injection ? `🎛 You set the next result: ${words(v.injection.values)}` : '🎛 You control the failure: choose what happens next (optional)'),
    ...inputs, h('div', { class: 'actions' }, button('Use for the next attempt', () => send('inject', { values: read() }))),
    h('p', { class: 'defn' }, 'Simulation only. You choose the condition; the same rules and approvals decide what follows. It applies once and is recorded in the report.'));
}

function controlButtons(names, extraArgs) {
  const classes = { approve: 'btn-approve', reject: 'btn-reject', next: 'primary', confirm_plan: 'primary', start: 'primary', signoff: 'btn-approve', resume: 'primary' };
  const main = h('div', { class: 'actions' }, app.view.controls.filter(c => c.command !== 'inject' && (!names || names.includes(c.command)))
    .map(c => button(c.label, () => send(c.command, extraArgs(c.command)), classes[c.command])));
  return [injectBox(), main].filter(Boolean);
}

function actionPanel() {
  const v = app.view, allowed = v.controls.map(c => c.command);
  const val = id => ($(id) ? $(id).value : '');
  const argsFor = name => {
    const rationale = val('rationale');
    if (name === 'approve' || name === 'reject') return { ...(v.approval ? { request_id: v.approval.request_id } : {}), approver: val('approver'), rationale };
    if (name === 'signoff') return { approver: val('approver'), rationale };
    if (name === 'start') return { authorized: $('ackAuth').checked, simulation_ack: $('ackSim').checked };
    if (['reject_plan', 'pause', 'escalate', 'cancel', 'skip', 'rollback'].includes(name)) return { rationale };
    return {};
  };
  const note = (label = 'Reason / note (required to skip)') => field('rationale', label);

  if (!allowed.length) return resultPanel();
  if (v.paused) return card('⏸ Drill paused', h('p', null, `State is saved (version ${v.state_version}). It survives a restart. Resume to continue from ${v.current_step_id || 'the current point'}.`), controlButtons(null, argsFor));
  if (v.status === 'planned') {
    return card('📋 Drill plan — review before confirming',
      table(['Step', 'Name', 'Type', 'Owner', 'Depends on', 'Approval', 'Rollback', 'Source'], v.plan.map(p =>
        [p.step_id, p.name, p.step_type, p.owner, p.dependencies.join(', ') || '—', p.approval_required ? 'Required' : '—', p.rollback ? 'Yes' : '—', p.source.citation])),
      note(), controlButtons(null, argsFor));
  }
  if (v.status === 'ready') {
    return card('🚦 Authorization and kickoff',
      h('label', { class: 'check' }, h('input', { type: 'checkbox', id: 'ackAuth' }), 'I confirm this drill is authorized and the participants are correct.'),
      h('label', { class: 'check' }, h('input', { type: 'checkbox', id: 'ackSim' }), 'I understand this is a SIMULATION. No real system is touched.'),
      controlButtons(null, argsFor));
  }
  if (v.status === 'awaiting_approval') {
    const a = v.approval;
    return card(`⚠️ Approval required — ${a.name}`,
      row('Step', `${a.step_id} · ${a.owner}`), row('Tool call', a.tool),
      h('details', { open: true }, h('summary', null, 'Exact parameters this approval is bound to'), h('pre', null, json(a.params))),
      row('Parameter hash', a.params_hash.slice(0, 16)), row('Expected effect', a.expected_effect), row('Risks', a.risks),
      row('Rollback', a.rollback_plan), row('Success criteria', a.success_criteria.join('; ')), row('Source', a.citation), row('Expires', clock(a.expires_at)),
      field('approver', 'Approver name (recorded in the audit log)', v.coordinator), note('Rationale (optional)'), controlButtons(null, argsFor));
  }
  if (v.status === 'awaiting_signoff') {
    return card(`✍️ Sign-off required — ${v.current_step.name}`, stepDetails(v.current_step),
      field('approver', `Name of the ${v.current_step.owner}`), note('Comment (optional)'), controlButtons(null, argsFor));
  }
  if (v.status === 'blocked') {
    return card(`⛔ Blocked at ${v.blocker.step_id}`, h('p', null, v.blocker.reason), row('Attempts', String(v.step_states[v.blocker.step_id].attempts)),
      row('Retry allowed by runbook', v.blocker.retryable ? 'Yes' : 'No'), note(), controlButtons(null, argsFor));
  }
  if (v.status === 'rolling_back') {
    return card('↩️ Rollback in progress — reverse order', row('Remaining', v.rollback.queue.join(' → ')), row('Done', v.rollback.done.join(', ') || 'none'),
      row('Reason', v.rollback.reason), h('p', null, 'Each rollback step needs its own approval.'), note(), controlButtons(null, argsFor));
  }
  if (v.status === 'active') {
    const i = v.plan.findIndex(p => p.step_id === v.current_step_id);
    return card(`Step ${i + 1}/${v.plan.length} · ${v.current_step.step_id} — ${v.current_step.name}`,
      h('p', null, v.current_step.description), stepDetails(v.current_step), note(), controlButtons(null, argsFor));
  }
  return card('Action', controlButtons(null, argsFor));
}

function resultPanel() {
  const v = app.view, r = app.report;
  if (!r) return card(`Drill ended: ${v.status}`, h('p', null, 'The report is built from saved state and the event log.'),
    h('div', { class: 'actions' }, button('Generate post-drill report', () => run(async () => {
      app.report = await api(`/api/drills/${v.drill_id}/report`);
      const saved = (await api(`/api/drills/${v.drill_id}/analysis`)).analysis;
      if (saved) app.analysis[v.drill_id] = { data: saved };
    }), 'primary')));
  return card('📋 Post-Drill Report', h('p', null, r.disclaimer),
    row('Overall result', mark(r.overall_result)),
    row('Conditions you set', r.injected_conditions.length ? r.injected_conditions.map(x => `${x.step_id}: ${words(x.values)}`).join(' | ') : 'none (scenario file only)'), row('Steps completed', `${r.metrics.steps_completed}/${r.metrics.steps_total}`),
    row('Overall RTO', h('span', null, `${dur(r.rto.observed_seconds)} (target ${dur(r.rto.target_seconds)}) `, mark(r.rto.status))),
    row('RPO', h('span', null, `${dur(r.rpo.observed_seconds)} (target ${dur(r.rpo.target_seconds)}) `, mark(r.rpo.status))),
    table(['Tier', 'Target', 'Cumulative from DR start', 'Tier execution', 'Result'], r.tiers.map(t =>
      [t.label, dur(t.target_seconds), dur(t.cumulative_seconds), dur(t.tier_execution_seconds), mark(t.result)])),
    h('p', { class: 'defn' }, r.definitions.rto_definition),
    h('p', null, h('b', null, 'Deviations')), table(['ID', 'Step', 'Description', 'Severity', 'Resolution'], r.deviations.map(d => [d.id, d.step_id, d.description, d.severity, d.resolution])),
    h('p', null, h('b', null, 'Improvement actions')), table(['Action', 'Priority', 'Owner', 'Target date'], r.improvement_actions.map(a => [a.action, a.priority, a.owner, a.target_date])),
    row('Event log hash chain', r.integrity.event_chain_valid ? 'VALID' : 'BROKEN'),
    row('Actions without matching approval', String(r.integrity.actions_without_matching_approval.length)),
    h('div', { class: 'actions' }, h('a', { class: 'btn primary', href: `/api/drills/${v.drill_id}/report.md`, download: '' }, 'Download full report (Markdown)')));
}

/* ---------- AI panels: advisory only; they never press a button ---------- */
const guardLine = (g, extra) => h('p', { class: g.passed ? 'pass' : 'fail' },
  g.passed ? '✓ Step IDs and citations exist (meaning not verified)' : `⚠ Reference check failed: ${[...(g.unknown_steps || []), ...(g.unknown_tools || []), ...(g.unknown_citations || [])].join(', ') || 'unverified content'}`,
  extra ? h('span', { class: 'defn' }, ' · ' + extra) : null);
const usage = x => `${x.model} · ${x.tokens_in}+${x.tokens_out} tokens`;

function fill(el, entry) {
  if (entry.loading) return el.replaceChildren(h('h4', null, '✨ AI briefing'), h('p', { class: 'defn' }, h('span', { class: 'spinner' }), 'Asking the model… the buttons below already work.'));
  if (entry.error) return el.replaceChildren(h('h4', null, '✨ AI briefing'), h('p', { class: 'defn' }, entry.error));
  const b = entry.data;
  el.replaceChildren(...[h('h4', null, `✨ AI briefing — ${b.step_id} (advisory)`), h('p', null, b.explanation),
    b.watch_for.length ? h('ul', null, b.watch_for.map(x => h('li', null, x))) : null,
    b.recommended_option ? row('Suggested option (you decide)', b.recommended_option) : null,
    b.recommended_option ? h('p', null, b.reasoning) : null,
    h('p', { class: 'defn' }, 'Sources: ' + (b.citations.join(' · ') || 'none')),
    guardLine(b.guard, usage(b))].filter(Boolean));
}

// Updates only its own box, so a name or note being typed is never wiped.
function briefingBox() {
  const v = app.view;
  if (!app.meta.model.configured || !v.current_step || v.paused || !v.started_at) return null;
  const key = [v.drill_id, v.current_step_id, v.status, v.step_states[v.current_step_id].attempts].join('|');
  const el = h('div', { class: 'card wide ai', id: 'brief-' + key });
  let entry = app.briefs[key];
  if (!entry) {
    entry = app.briefs[key] = { loading: true };
    api(`/api/drills/${v.drill_id}/brief`, {}).then(data => { Object.assign(entry, { loading: false, data }); })
      .catch(e => { Object.assign(entry, { loading: false, error: e.message }); })
      .finally(() => { const live = $('brief-' + key); if (live) fill(live, entry); });
  }
  fill(el, entry);
  return el;
}

function analysisCard() {
  const v = app.view, entry = app.analysis[v.drill_id];
  if (!app.meta.model.configured) return null;
  if (!entry || entry.error) {
    return card('✨ AI post-drill analysis', h('p', { class: entry ? 'fail' : 'defn' }, entry ? entry.error : 'Summary, risks and proposed actions, written from this drill\'s records.'),
      h('div', { class: 'actions' }, button('Generate AI analysis', () => run(async () => {
        try { app.analysis[v.drill_id] = { data: (await api(`/api/drills/${v.drill_id}/analysis`, {})).analysis }; }
        catch (e) { app.analysis[v.drill_id] = { error: e.message }; }
      }), 'primary')));
  }
  const a = entry.data;
  const list = (title, items) => [h('p', null, h('b', null, title)), h('ul', null, items.map(x => h('li', null, x)))];
  return card('✨ AI post-drill analysis (advisory)', h('p', null, a.executive_summary), list('Went well', a.went_well), list('Risks', a.risks),
    table(['Proposed action', 'Owner', 'Priority', 'Evidence', 'Checked against records'], a.actions.map(x => [x.action, x.owner, x.priority, x.evidence.join(', '), mark(x.verified ? 'PASS' : 'FAIL')])),
    guardLine(a.guard, usage(a)), h('p', { class: 'defn' }, 'Included in the Markdown download. Results and timings above are calculated by code, not by the model.'));
}

const SAMPLE_RUNBOOK = `Payroll DR notes (draft)
1. The DB Lead checks that replication lag is under 10 seconds.
2. Promote the standby payroll database. The DB Lead confirms it accepts writes. To undo, demote it back to standby.
3. Someone from the network side moves DNS across when things look ready.
4. Restart the payroll batch scheduler.
5. Finance confirms a test payslip can be generated.`;

function interpreterSection() {
  const d = app.draft;
  const input = h('textarea', { class: 'field', rows: 8, maxLength: 8000, oninput: e => { d.text = e.target.value; } });
  input.value = d.text || SAMPLE_RUNBOOK;
  const result = d.loading ? h('p', { class: 'defn' }, h('span', { class: 'spinner' }), 'Interpreting…')
    : d.error ? h('p', { class: 'fail' }, d.error)
    : d.result ? h('div', null,
      h('p', null, `${d.result.steps.length} steps found, ${d.result.gap_count} gaps. Draft only: it cannot be run until a runbook owner approves it.`),
      table(['#', 'Step', 'Type', 'Owner', 'Success criteria', 'Rollback', 'Gaps (checked by code)', 'Source quote'], d.result.steps.map((s, i) =>
        [i + 1, s.name, s.step_type, s.owner || '—', s.success_criteria.join('; ') || '—', s.rollback || '—',
         s.gaps.length ? h('span', { class: 'fail' }, s.gaps.join(', ')) : mark('PASS'),
         h('span', { class: s.grounded ? '' : 'fail' }, (s.grounded ? '' : '⚠ not found in text: ') + s.source_quote)])),
      d.result.ambiguities.length ? h('ul', null, d.result.ambiguities.map(x => h('li', null, x))) : null,
      h('p', { class: d.result.guard.passed ? 'pass' : 'fail' }, d.result.guard.passed ? '✓ Every step quotes the source text' : `⚠ ${d.result.guard.ungrounded_steps} step(s) not traceable to the text`, h('span', { class: 'defn' }, ' · ' + usage(d.result))))
    : null;
  const go = () => {
    if (d.loading) return;
    Object.assign(d, { text: input.value, loading: true, error: null, result: null }); render();
    api('/api/interpret', { text: d.text }).then(r => { d.result = r; }).catch(e => { d.error = e.message; })
      .finally(() => { d.loading = false; if (app.tab === 'portal') render(); });
  };
  return section('✨ AI runbook review — turn free-text runbook notes into a checked draft plan',
    app.meta.model.configured ? h('div', { class: 'card wide ai' }, input, h('div', { class: 'actions' }, button('Interpret and check gaps', go, 'primary')), result)
      : h('p', { class: 'defn' }, 'Add a model key to .env to use this.'));
}

/* ---------- new drill ---------- */
function newDrillForm() {
  const m = app.meta;
  const describe = h('p', { class: 'defn' });
  const scenario = h('select', { id: 'scenario', class: 'field', onchange: () => show() },
    m.scenarios.map(s => h('option', { value: s.scenario_id, selected: s.scenario_id === 'nominal_success' }, s.title)));
  const show = () => {
    const s = m.scenarios.find(x => x.scenario_id === scenario.value);
    describe.textContent = `${s.description} Expected outcome: ${s.expected_outcome}. Lag threshold: ${s.lag_threshold_seconds}s.`;
  };
  show();
  const books = h('select', { id: 'runbook', class: 'field' }, [...m.knowledge.runbooks].sort((a, b) => b.validation.usable - a.validation.usable)
    .map(b => h('option', { value: `${b.document_id}|${b.version}|${b.application}` }, `${b.document_id} v${b.version} — ${b.approval_status}${b.validation.usable ? '' : ' (fails validation)'}`)));
  return card('New SIMULATED drill',
    h('p', null, "I'm the Drill Coordinator. I retrieve the approved runbook, guide you one step at a time, and ask for approval before every simulated action."),
    h('label', { htmlFor: 'scenario' }, 'Scenario'), scenario, describe,
    h('label', { htmlFor: 'runbook' }, 'Runbook'), books,
    field('coordinator', 'Your name (Drill Coordinator)'),
    h('div', { class: 'actions' }, button('Create drill', () => run(async () => {
      const [runbook_id, runbook_version, application] = $('runbook').value.split('|');
      app.view = await api('/api/drills', { scenario_id: scenario.value, coordinator: $('coordinator').value, runbook_id, runbook_version, application });
      app.report = null;
    }), 'primary')));
}

/* ---------- renderers ---------- */
function renderChat() {
  $('chatList').replaceChildren(...app.drills.map(d => h('button', {
    class: 'chatitem' + (app.view && app.view.drill_id === d.drill_id ? ' active' : ''), title: d.drill_id, onclick: () => openDrill(d.drill_id)
  }, `${d.scenario_id} · ${d.paused ? 'paused' : d.status}`)));
  const error = app.error ? h('div', { class: 'card wide error', role: 'alert' }, '⚠ ' + app.error) : null;
  const v = app.view;
  // Keep a typed approver name if the request failed.
  const typed = {};
  for (const el of $('msgs').querySelectorAll('input.field,select.field')) typed[el.id] = el.value;
  const panels = v ? [briefingBox(), actionPanel(), !v.controls.length && app.report ? analysisCard() : null].filter(Boolean) : [];
  $('msgs').replaceChildren(...(v ? [...feed(), ...panels] : [newDrillForm()]), ...(error ? [error] : []));
  if (app.error) for (const [id, value] of Object.entries(typed)) if ($(id)) $(id).value = value;
  // Show the top of the action card, keeping a little of the conversation above it.
  const box = $('msgs'), panel = panels[0] || box.lastElementChild;
  box.scrollTop = error ? box.scrollHeight : panel.offsetTop - box.offsetTop - 150;
  $('composerInput').disabled = !v;

  const events = v ? [...v.events].reverse().filter(e => !HIDDEN.has(e.event_type)) : [];
  $('tl').replaceChildren(...events.map(e => {
    const level = BAD.includes(e.status) ? 'bad' : ['pending', 'blocked', 'cancelled'].includes(e.status) ? 'warn' : '';
    const elapsed = v.started_at && e.drill_time >= v.started_at ? '+' + dur(Math.round((new Date(e.drill_time) - new Date(v.started_at)) / 1000)) : '';
    return h('div', { class: 'tlitem ' + level }, h('div', { class: 'tltop' }, h('span', { class: 'tltime' }, clock(e.timestamp)), h('span', { class: 'tlelapsed' }, elapsed)),
      h('div', { class: 'tltext' }, e.summary), h('span', { class: 'badge ' + (level === 'bad' ? 'b-bad' : level === 'warn' ? 'b-warn' : 'b-ok') }, `${e.status.toUpperCase()}${e.step_id ? ' · ' + e.step_id : ''}`));
  }));
}

function renderPortal() {
  const v = app.view, kb = app.meta.knowledge, out = [h('div', { class: 'portal-head' }, h('h2', null, 'DR / Backup Portal (simulated environment)'),
    h('span', { class: 'tag' }, v ? `Scenario: ${v.scenario_title}` : 'No drill selected'))];
  if (v) {
    const env = v.scenario_state, rep = [...v.checks].reverse().find(c => c.tool === 'check_replication');
    const tile = (label, value, sub) => h('div', { class: 'tile' }, h('div', { class: 'label' }, label), h('div', { class: 'value' }, value), h('div', { class: 'sub' }, sub || ''));
    out.push(h('div', { class: 'grid' },
      tile('Replication', rep ? rep.status : 'not checked', rep ? rep.details : 'Run the replication check'),
      tile('Database', env.database), tile('Application', env.application), tile('DNS', env.dns), tile('DR storage', env.storage), tile('Primary site', env.primary_site)));
    out.push(section('Recovery tiers', table(['Tier', 'Target RTO', 'Validation step', 'Step status'], v.definitions.tiers.map(t =>
      [t.label, dur(t.target_seconds), t.ready_step, mark(v.step_states[t.ready_step].status)]))));
  }
  out.push(section(`Knowledge base — ${kb.indexed_passages} passages indexed (SQLite FTS5 / BM25)`,
    table(['Document', 'Type', 'Version', 'Approval', 'Last reviewed', 'Validation'], [...kb.runbooks, ...kb.documents].map(d =>
      [`${d.document_id} — ${d.title}`, d.document_type, d.version, mark(d.approval_status), d.last_reviewed,
       !d.validation ? '—' : d.validation.usable ? mark('PASS') : h('details', null, h('summary', null, `${d.validation.issues.length} issue(s)`), d.validation.issues.map(i => h('div', null, i)))]))));
  out.push(interpreterSection());
  $('portalView').replaceChildren(...out);
}

async function renderOtel() {
  const root = $('otelView'), v = app.view;
  const head = h('div', { class: 'otel-head' }, h('h2', null, 'Local trace'), h('span', { class: 'tag' }, v ? v.correlation_id : 'no drill selected'));
  const spans = v ? (await api(`/api/drills/${v.drill_id}/spans`)).spans.filter(s => !s.name.startsWith('guard.')) : [];
  if (!spans.length) { root.replaceChildren(head, h('div', { class: 'otel-empty' }, 'No tool or model calls recorded yet.')); return; }
  const tools = spans.filter(s => s.agent === 'operator'), llm = spans.filter(s => s.name.startsWith('llm.'));
  const sum = (list, k) => list.reduce((a, s) => a + (s[k] || 0), 0);
  const t0 = Math.min(...spans.map(s => Date.parse(s.started_at)));
  const total = Math.max(...spans.map(s => Date.parse(s.started_at) - t0 + s.duration_ms), 1);
  root.replaceChildren(head, h('div', { class: 'kpis' },
    kpi('Operator calls', tools.length, `${sum(tools, 'duration_ms').toFixed(1)} ms measured`),
    kpi('Model calls', llm.length, llm.length ? `${sum(llm, 'duration_ms').toFixed(0)} ms measured` : 'none made'),
    kpi('Input tokens', sum(spans, 'tokens_in'), 'reported by the model API'), kpi('Output tokens', sum(spans, 'tokens_out'), 'reported by the model API'),
    kpi('Simulated operation time', dur(sum(spans, 'simulated_seconds')), 'from scenario fixtures')),
    table(['Span', 'Step', 'Start', 'Measured', 'Simulated', 'Tokens in', 'Tokens out', 'Status'], spans.map(s =>
      [s.name, s.step_id, clock(s.started_at), `${s.duration_ms} ms`, `${s.simulated_seconds}s`, s.tokens_in, s.tokens_out, mark(s.status)])),
    section('Waterfall', spans.map(s => h('div', { class: 'trace-row' }, h('div', { class: 'trace-name' }, `${s.name} ${s.step_id || ''}`),
      h('div', { class: 'trace-track' }, h('div', { class: 'trace-bar svc-' + s.agent, style: `left:${((Date.parse(s.started_at) - t0) / total * 99).toFixed(2)}%;width:1.2%` }))))));
}

async function renderEval() {
  const root = $('evalView'), v = app.view;
  const out = [h('div', { class: 'otel-head' }, h('h2', null, 'Evaluation'), h('span', { class: 'tag' }, 'measured results only'))];
  if (v) {
    const r = await api(`/api/drills/${v.drill_id}/report`);
    const spans = (await api(`/api/drills/${v.drill_id}/spans`)).spans.filter(s => s.guard);
    const dispatched = v.events.filter(e => e.event_type === 'ACTION_DISPATCHED').length;
    out.push(section('This drill — live audit', h('div', { class: 'kpis' },
      kpi('Approval gate', r.integrity.actions_without_matching_approval.length ? 'FAIL' : 'PASS', `${dispatched} dispatched action(s) checked`),
      kpi('Event log integrity', r.integrity.event_chain_valid ? 'VALID' : 'BROKEN', `${r.integrity.event_count} events, hash chained`),
      kpi('Evidence completeness', pct(r.metrics.evidence_completeness), 'completed steps with evidence'),
      kpi('Model answers passing guard', spans.length ? pct(spans.filter(s => s.guard.passed).length / spans.length) : '—', spans.length ? `${spans.length} checked for unknown steps, tools, citations` : 'no model answers yet'))));
  }
  const e = await api('/api/evaluation');
  const m = e.model_eval;
  out.push(m ? section(`Real-model evaluation — ${m.model}, ${new Date(m.generated_at).toLocaleString()}`,
    h('div', { class: 'kpis' }, Object.entries(m.summary).map(([k, x]) => kpi(k, `${x.passed}/${x.total}`, 'passed'))),
    h('p', { class: 'defn' }, 'A small team-written set (smoke test, not a benchmark). Prompt, search and scoring were improved after earlier runs on these questions. The failback question is answered by a code rule, not the model.'),
    table(['Category', 'Input', 'Result', 'Why'], m.cases.map(c => [c.category, c.input, mark(c.passed ? 'PASS' : 'FAIL'), c.why])))
    : h('div', { class: 'otel-empty' }, 'No real-model evaluation saved. Run: python scripts/evaluate_model.py'));
  if (e.available === false) out.push(h('div', { class: 'otel-empty' }, 'No saved evaluation run. Run: python scripts/evaluate.py'));
  else {
    out.push(section(`Last evaluation run — ${new Date(e.generated_at).toLocaleString()}`, h('div', { class: 'kpis' },
      kpi('Automated tests', `${e.tests.passed}/${e.tests.total}`, 'passed'),
      kpi('Scenarios', `${e.scenarios.filter(s => s.match).length}/${e.scenarios.length}`, 'reached the expected outcome'),
      kpi('Retrieval hit@3', pct(e.retrieval.hit_at_3), `${e.retrieval.answerable} answerable questions`),
      kpi('Out-of-scope refusals', pct(e.retrieval.refusal_accuracy), `${e.retrieval.out_of_scope} off-topic questions`),
      kpi('Report generation', `${e.report_generation_ms} ms`, 'measured on this machine'))));
    out.push(section('Safety and guardrail matrix', table(['ID', 'Dimension', 'Tests', 'Result'], e.guardrails.map(g => [g.id, g.dimension, `${g.passed}/${g.total}`, mark(g.result)]))));
    out.push(section('Scenario matrix', table(['Scenario', 'Expected', 'Actual', 'Unapproved actions', 'Log valid', 'Result'], e.scenarios.map(s =>
      [s.scenario_id, s.expected, s.actual, s.unapproved_actions, s.log_valid ? 'yes' : 'no', mark(s.match ? 'PASS' : 'FAIL')]))));
    out.push(section('Retrieval cases', table(['Question', 'Expected source', 'Top result', 'Rank'], e.retrieval.cases.map(c => [c.query, c.expected || '(should find nothing)', c.top || 'nothing', c.rank || (c.expected ? 'missed' : '—')]))));
  }
  root.replaceChildren(...out);
}

function render() {
  for (const b of document.querySelectorAll('nav button')) b.classList.toggle('active', b.dataset.view === app.tab);
  for (const name of ['chat', 'portal', 'otel', 'eval']) $(name + 'View').classList.toggle('active', name === app.tab);
  const fail = e => $(app.tab + 'View').replaceChildren(h('div', { class: 'otel-empty' }, e.message));
  if (app.tab === 'chat') renderChat();
  else if (app.tab === 'portal') renderPortal();
  else if (app.tab === 'otel') renderOtel().catch(fail);
  else renderEval().catch(fail);
}

for (const b of document.querySelectorAll('nav button')) b.addEventListener('click', () => { app.tab = b.dataset.view; render(); });
$('newChatBtn').addEventListener('click', () => { app.view = null; app.report = null; app.error = null; render(); });
$('sendBtn').addEventListener('click', sendText);
$('composerInput').addEventListener('keydown', e => { if (e.key === 'Enter') sendText(); });

(async () => {
  app.meta = await api('/api/meta');
  const m = app.meta.model;
  $('modelTag').textContent = m.configured ? `model: ${m.model}` : 'model: not configured (deterministic mode)';
  app.drills = (await api('/api/drills')).drills;
  render();
})().catch(e => $('msgs').replaceChildren(h('div', { class: 'card error' }, e.message)));
