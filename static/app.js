'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const today = () => new Date().toLocaleDateString('en-CA');
const thisMonth = () => today().slice(0, 7);

// Every state-changing call carries X-Requested-With: the server rejects cross-site form posts without it.
async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !location.pathname.startsWith('/login')) location.href = '/login';
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function toast(message, kind = 'success') {
  const area = $('#toast-area');
  if (!area) return;
  area.innerHTML = `<div class="alert alert-${kind} alert-dismissible" role="alert">${esc(message)}<button class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button></div>`;
}
const attempt = async (fn, ok) => { try { const r = await fn(); if (ok) toast(ok); return r; } catch (e) { toast(e.message, 'danger'); } };
const debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const badge = (status) => `<span class="badge text-bg-${{ pending: 'warning', approved: 'success', rejected: 'danger', cancelled: 'secondary' }[status] || 'secondary'}">${esc(status)}</span>`;
const num = (v) => (v === null || v === undefined ? '–' : v);
const pct = (v) => (v === null || v === undefined ? '–' : `${v}%`);

function pager(el, data, go) {
  if (data.pages <= 1) { el.innerHTML = `<small class="text-muted">${data.total} record${data.total === 1 ? '' : 's'}</small>`; return; }
  el.innerHTML = `<nav class="d-flex justify-content-between align-items-center"><small class="text-muted">${data.total} records</small>
    <div class="btn-group btn-group-sm"><button class="btn btn-outline-secondary" ${data.page <= 1 ? 'disabled' : ''} data-p="${data.page - 1}">Previous</button>
    <button class="btn btn-outline-secondary" disabled>Page ${data.page} / ${data.pages}</button>
    <button class="btn btn-outline-secondary" ${data.page >= data.pages ? 'disabled' : ''} data-p="${data.page + 1}">Next</button></div></nav>`;
  el.querySelectorAll('[data-p]').forEach((b) => b.addEventListener('click', () => go(Number(b.dataset.p))));
}

const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== '' && v != null)).toString();
let me;

// ---- login / logout ---------------------------------------------------------------------------
const pages = {
  login() {
    $('#login-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const ok = await attempt(() => api('/api/login', { method: 'POST', body: { email: $('#email').value, password: $('#password').value } }));
      if (ok) location.href = '/';
    });
    document.querySelectorAll('[data-demo]').forEach((a) => a.addEventListener('click', (e) => {
      e.preventDefault(); $('#email').value = a.dataset.demo; $('#password').value = 'demo1234';
    }));
  },

  // ---- dashboard ------------------------------------------------------------------------------
  async dashboard() {
    const refresh = async () => {
      const rec = await api('/api/attendance/today');
      $('#today-status').innerHTML = !rec ? 'Not checked in yet.'
        : `Checked in at <b>${esc(rec.check_in)}</b>${rec.late ? ' <span class="badge text-bg-warning">late</span>' : ''}` +
          (rec.check_out ? `, out at <b>${esc(rec.check_out)}</b> (${rec.hours} h)` : ' — still working.');
      $('#check-in').disabled = $('#check-in-remote').disabled = !!rec;
      $('#check-out').disabled = !rec || !!rec.check_out;
      const b = await api('/api/leave/balances');
      $('#balance-year').textContent = b.year;
      $('#balances').innerHTML = b.balances.map((x) => {
        const used = x.used + x.pending, cap = x.allowance;
        const width = cap ? Math.min(100, Math.round((100 * used) / cap)) : 0;
        return `<div class="balance-row"><div class="d-flex justify-content-between"><b>${esc(x.leave_type)}</b>
          <span>${cap === null ? `${x.used} used (no limit)` : `${x.remaining} of ${cap} left`}</span></div>
          ${cap ? `<div class="progress" style="height:6px"><div class="progress-bar" style="width:${width}%"></div></div>` : ''}
          <small class="text-muted">${x.used} approved${x.pending ? `, ${x.pending} pending` : ''}</small></div>`;
      }).join('');
      if ($('#approvals')) await loadApprovals();
    };
    $('#check-in').onclick = () => attempt(() => api('/api/attendance/check-in', { method: 'POST', body: {} }), 'Checked in').then(refresh);
    $('#check-in-remote').onclick = () => attempt(() => api('/api/attendance/check-in', { method: 'POST', body: { status: 'remote' } }), 'Checked in (remote)').then(refresh);
    $('#check-out').onclick = () => attempt(() => api('/api/attendance/check-out', { method: 'POST', body: {} }), 'Checked out').then(refresh);

    const types = await api('/api/leave/types');
    $('#lf-type').innerHTML = types.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
    $('#lf-start').min = $('#lf-end').min = today();
    $('#leave-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const r = await attempt(() => api('/api/leave/requests', { method: 'POST', body: {
        leave_type_id: Number($('#lf-type').value), start_date: $('#lf-start').value, end_date: $('#lf-end').value, reason: $('#lf-reason').value } }),
        'Leave request submitted');
      if (r) { e.target.reset(); refresh(); }
    });
    await refresh();
  },
};

async function loadApprovals() {
  const data = await api('/api/leave/requests?status=pending&per_page=50');
  const rows = data.items.filter((r) => r.user_id !== me.id);
  $('#approvals').innerHTML = rows.length ? `<table class="table table-sm align-middle"><tbody>${rows.map((r) => `
    <tr><td><b>${esc(r.employee)}</b><br><small class="text-muted">${esc(r.leave_type)} · ${esc(r.start_date)} → ${esc(r.end_date)} · ${r.days} day(s)</small>
      ${r.reason ? `<br><small>${esc(r.reason)}</small>` : ''}</td>
      <td class="text-end text-nowrap"><button class="btn btn-sm btn-success" data-act="approve" data-id="${r.id}">Approve</button>
      <button class="btn btn-sm btn-outline-danger" data-act="reject" data-id="${r.id}">Reject</button></td></tr>`).join('')}</tbody></table>`
    : '<span class="text-muted">Nothing waiting.</span>';
  document.querySelectorAll('#approvals [data-act]').forEach((b) => b.addEventListener('click', () => decide(b.dataset.id, b.dataset.act, loadApprovals)));
}

async function decide(id, action, after) {
  let comment = '';
  if (action === 'reject') {
    comment = prompt('Reason for rejecting (shown to the employee):');
    if (!comment) return;
  }
  await attempt(() => api(`/api/leave/requests/${id}/${action}`, { method: 'POST', body: { comment } }), `Request ${action}d`);
  after();
}

// ---- attendance page --------------------------------------------------------------------------
pages.attendance = async function () {
  const isStaff = !!$('#att-q');
  let page = 1;
  $('#att-month').value = thisMonth();
  $('#af-date').value = today();
  $('#af-date').max = today();
  if ($('#af-user')) {
    const users = await api('/api/users');
    $('#af-user').innerHTML = users.map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join('');
  }
  const load = async () => {
    const data = await api(`/api/attendance?${qs({ month: $('#att-month').value, q: isStaff ? $('#att-q').value : '', page })}`);
    $('#att-table tbody').innerHTML = data.items.map((a) => `<tr><td>${esc(a.date)}</td>${isStaff ? `<td>${esc(a.employee)}<br><small class="text-muted">${esc(a.department)}</small></td>` : ''}
      <td>${esc(a.check_in)} ${a.late ? '<span class="badge text-bg-warning">late</span>' : ''}</td><td>${esc(a.check_out) || '–'}</td>
      <td>${a.hours || '–'}</td><td>${esc(a.status.replace('_', ' '))}</td></tr>`).join('') || `<tr><td colspan="6" class="text-muted">No records.</td></tr>`;
    pager($('#att-pager'), data, (p) => { page = p; load(); });
  };
  $('#att-month').addEventListener('change', () => { page = 1; load(); });
  if (isStaff) $('#att-q').addEventListener('input', debounce(() => { page = 1; load(); }));
  $('#att-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = { date: $('#af-date').value, check_in: $('#af-in').value, check_out: $('#af-out').value || null,
      status: $('#af-status').value, note: $('#af-note').value };
    if ($('#af-user')) body.user_id = Number($('#af-user').value);
    if (await attempt(() => api('/api/attendance', { method: 'POST', body }), 'Attendance saved')) { e.target.reset(); $('#af-date').value = today(); load(); }
  });
  load();
};

// ---- leave page -------------------------------------------------------------------------------
pages.leave = async function () {
  const isStaff = !!$('#lv-q');
  let page = 1;
  const params = () => ({ q: isStaff ? $('#lv-q').value : '', status: $('#lv-status').value, from: $('#lv-from').value, to: $('#lv-to').value });
  const load = async () => {
    const data = await api(`/api/leave/requests?${qs({ ...params(), page })}`);
    $('#lv-table tbody').innerHTML = data.items.map((r) => {
      const mine = r.user_id === me.id, canReview = r.status === 'pending' && !mine && me.role !== 'employee';
      const canCancel = mine && ['pending', 'approved'].includes(r.status) || (me.role === 'admin' && r.status === 'pending');
      return `<tr><td>${esc(r.employee)}<br><small class="text-muted">${esc(r.department)}</small></td><td>${esc(r.leave_type)}</td>
        <td>${esc(r.start_date)} → ${esc(r.end_date)}<br><small class="text-muted">${esc(r.reason)}</small></td><td>${r.days}</td>
        <td>${badge(r.status)}${r.review_comment ? `<br><small class="text-muted">${esc(r.review_comment)}</small>` : ''}</td><td>${esc(r.reviewer) || '–'}</td>
        <td class="text-end text-nowrap">${canReview ? `<button class="btn btn-sm btn-success" data-act="approve" data-id="${r.id}">Approve</button>
          <button class="btn btn-sm btn-outline-danger" data-act="reject" data-id="${r.id}">Reject</button>` : ''}
          ${canCancel ? `<button class="btn btn-sm btn-outline-secondary" data-act="cancel" data-id="${r.id}">Cancel</button>` : ''}</td></tr>`;
    }).join('') || '<tr><td colspan="7" class="text-muted">No leave requests match.</td></tr>';
    $('#lv-table tbody').querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', async () => {
      if (b.dataset.act === 'cancel') { await attempt(() => api(`/api/leave/requests/${b.dataset.id}/cancel`, { method: 'POST', body: {} }), 'Request cancelled'); load(); }
      else decide(b.dataset.id, b.dataset.act, load);
    }));
    pager($('#lv-pager'), data, (p) => { page = p; load(); });
    if ($('#lv-export')) $('#lv-export').href = `/api/reports/leave-requests.csv?${qs(params())}`;
  };
  document.querySelectorAll('#lv-status,#lv-from,#lv-to').forEach((el) => el.addEventListener('change', () => { page = 1; load(); }));
  if (isStaff) $('#lv-q').addEventListener('input', debounce(() => { page = 1; load(); }));
  load();
};

// ---- reports ----------------------------------------------------------------------------------
pages.reports = async function () {
  $('#rp-month').value = thisMonth();
  const depts = await api('/api/departments');
  $('#rp-dept').innerHTML += depts.map((d) => `<option value="${d.id}">${esc(d.name)}</option>`).join('');
  const load = async () => {
    const q = qs({ month: $('#rp-month').value, department_id: $('#rp-dept').value, q: $('#rp-q').value });
    const [emp, dept] = await Promise.all([api(`/api/reports/attendance-summary?${q}`), api(`/api/reports/department-summary?${q}`)]);
    $('#print-title').textContent = `Attendance report · ${$('#rp-month').value}`;
    $('#dept-table tbody').innerHTML = dept.map((d) => `<tr><td>${esc(d.department)}</td><td class="text-end">${d.headcount}</td><td class="text-end">${d.expected_days}</td>
      <td class="text-end">${d.attended_days}</td><td class="text-end">${d.leave_days}</td><td class="text-end">${d.absent_days}</td><td class="text-end">${d.late_count}</td>
      <td class="text-end">${d.total_hours}</td><td class="text-end">${pct(d.attendance_rate)}</td></tr>`).join('') || '<tr><td colspan="9" class="text-muted">No data.</td></tr>';
    $('#emp-table tbody').innerHTML = emp.map((r) => `<tr><td>${esc(r.employee)}</td><td>${esc(r.department)}</td><td class="text-end">${r.expected_days}</td>
      <td class="text-end">${r.present_days}</td><td class="text-end">${r.half_days}</td><td class="text-end">${r.leave_days}</td>
      <td class="text-end ${r.absent_days > 0 ? 'text-danger' : ''}">${r.absent_days}</td><td class="text-end">${r.late_count}</td>
      <td class="text-end">${r.total_hours}</td><td class="text-end">${pct(r.attendance_rate)}</td></tr>`).join('') || '<tr><td colspan="10" class="text-muted">No data.</td></tr>';
    $('#export-emp').href = `/api/reports/attendance-summary.csv?${q}`;
    $('#export-dept').href = `/api/reports/department-summary.csv?${q}`;
  };
  document.querySelectorAll('#rp-month,#rp-dept').forEach((el) => el.addEventListener('change', load));
  $('#rp-q').addEventListener('input', debounce(load));
  load();
};

// ---- user admin -------------------------------------------------------------------------------
pages.users = async function () {
  const depts = await api('/api/departments');
  $('#uf-dept').innerHTML = depts.map((d) => `<option value="${d.id}">${esc(d.name)}</option>`).join('');
  const load = async () => {
    const users = await api(`/api/users?${qs({ q: $('#us-q').value })}`);
    $('#uf-manager').innerHTML = '<option value="">No manager</option>' +
      users.filter((u) => u.role !== 'employee').map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join('');
    $('#us-table tbody').innerHTML = users.map((u) => `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${esc(u.role)}</td>
      <td>${esc(u.department)}</td><td>${esc(u.manager) || '–'}</td>
      <td class="text-end">${u.id !== me.id ? `<button class="btn btn-sm btn-outline-danger" data-deact="${u.id}">Deactivate</button>` : ''}</td></tr>`).join('');
    document.querySelectorAll('[data-deact]').forEach((b) => b.addEventListener('click', async () => {
      if (confirm('Deactivate this account? They will no longer be able to log in.')) {
        await attempt(() => api(`/api/users/${b.dataset.deact}/deactivate`, { method: 'POST', body: {} }), 'Account deactivated'); load();
      }
    }));
  };
  $('#us-q').addEventListener('input', debounce(load));
  $('#user-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = { name: $('#uf-name').value, email: $('#uf-email').value, password: $('#uf-password').value, role: $('#uf-role').value,
      department_id: Number($('#uf-dept').value), manager_id: $('#uf-manager').value ? Number($('#uf-manager').value) : null };
    if (await attempt(() => api('/api/users', { method: 'POST', body }), 'User created')) { e.target.reset(); load(); }
  });
  load();
};

// ---- boot -------------------------------------------------------------------------------------
(async () => {
  const page = document.body.dataset.page;
  if (!page && $('#login-form')) return pages.login();
  if (!page) return;
  me = await api('/api/me');
  $('#logout')?.addEventListener('click', async () => { await api('/api/logout', { method: 'POST', body: {} }); location.href = '/login'; });
  pages[page]?.();
})();
