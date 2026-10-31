const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let state = { dashboard: null, invoices: [], selectedFiles: [] };
const STATUS_COLORS = {
  'Auto-Approved': '#78977a', 'Needs Approval': '#d5a45f',
  'Flagged - Possible Duplicate': '#c97969', 'Flagged - Unusual Amount': '#a95750',
  'Needs Manual Review - Extraction Incomplete': '#a7aaa2'
};
const STATUS_CLASS = status => {
  if ((status || '').includes('Flagged')) return 'flagged';
  if ((status || '').includes('Manual')) return 'manual';
  if ((status || '').includes('Needs Approval')) return 'pending';
  return 'approved';
};
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => {
  const symbol = state.dashboard?.currency_symbol || '$';
  return `${symbol}${Number(value || 0).toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}`;
};
const initials = name => (String(name || '?').trim().split(/\s+/).slice(0,2).map(x => x[0]).join('').toUpperCase() || '?');
const prettyDate = value => {
  if (!value) return '—';
  const d = new Date(`${value}T00:00:00`);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString(undefined,{day:'2-digit',month:'short',year:'numeric'});
};

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'Something went wrong. Please try again.');
  return data;
}

function setView(view) {
  $$('.view').forEach(el => el.classList.toggle('active-view', el.id === `view-${view}`));
  $$('.nav-link').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  $('#crumb').textContent = ({overview:'Overview',invoices:'All invoices',review:'Review queue',vendors:'Vendors'})[view] || 'Overview';
  $('#sidebar').classList.remove('open');
  if (view === 'invoices') loadInvoices();
  if (view === 'review') renderReview();
  if (view === 'vendors') renderVendors();
}

function renderMetrics(data) {
  const m = data.metrics;
  $('#metricSpend').textContent = money(m.total_spend);
  $('#metricInvoices').textContent = m.total_invoices.toLocaleString();
  $('#metricPending').textContent = m.pending_review.toLocaleString();
  $('#metricVendors').textContent = m.vendors.toLocaleString();
  $('#chartTotal').textContent = money(m.total_spend);
  $('#invoiceNavCount').textContent = m.total_invoices;
  $('#reviewNavCount').textContent = m.pending_review;
  $('#queueTotal').textContent = m.pending_review;
  $('#companyName').textContent = data.company || 'Finance workspace';
  $('#donutTotal').textContent = m.total_invoices;
  $('#vendorCount').textContent = m.vendors;
  $('#vendorSpend').textContent = money(m.total_spend);
  $('#vendorRisks').textContent = data.vendors.filter(v => v.risk_signals?.length).length;
}

function renderChart(monthly) {
  const chart = $('#spendChart');
  if (!monthly?.length) {
    chart.innerHTML = '<div class="empty-chart">Your spend activity will appear here once invoices are processed.</div>';
    return;
  }
  const values = monthly.slice(-7);
  const max = Math.max(...values.map(x => x.amount), 1);
  chart.innerHTML = values.map(item => {
    const height = Math.max(4, item.amount / max * 100);
    const label = item.month === 'Undated' ? 'No date' : new Date(`${item.month}-01T00:00:00`).toLocaleDateString(undefined,{month:'short'});
    return `<div class="chart-column"><div class="chart-bar" style="height:${height}%" data-value="${escapeHtml(money(item.amount))}" title="${escapeHtml(item.month)}: ${escapeHtml(money(item.amount))}"></div><span class="chart-month">${escapeHtml(label)}</span></div>`;
  }).join('');
}

function renderDonut(statuses, total) {
  const entries = Object.entries(statuses || {}).sort((a,b) => b[1]-a[1]);
  if (!total) {
    $('#statusDonut').style.background = 'conic-gradient(#dfe5dc 0 100%)';
    $('#statusLegend').innerHTML = '<span class="legend-row">No processed invoices yet</span>';
    return;
  }
  let cursor = 0;
  const stops = entries.map(([status,count]) => {
    const start = cursor; cursor += count / total * 100;
    return `${STATUS_COLORS[status] || '#a7aaa2'} ${start}% ${cursor}%`;
  });
  $('#statusDonut').style.background = `conic-gradient(${stops.join(',')})`;
  $('#statusLegend').innerHTML = entries.map(([status,count]) => `<div class="legend-row"><i class="legend-swatch" style="background:${STATUS_COLORS[status] || '#a7aaa2'}"></i><span>${escapeHtml(status.replace('Flagged - ',''))}</span><strong>${count}</strong></div>`).join('');
}

function vendorCell(record) {
  return `<div class="vendor-cell"><span class="vendor-avatar">${escapeHtml(initials(record.vendor))}</span><div><div class="vendor-name">${escapeHtml(record.vendor || 'Unknown vendor')}</div><div class="vendor-file">${escapeHtml(record.source_file || 'Document')}</div></div></div>`;
}
function statusPill(status, decision) {
  const label = decision === 'rejected' ? 'Rejected' : decision === 'approved' && status !== 'Auto-Approved' ? 'Approved' : (status || 'Unknown').replace('Flagged - ', 'Flagged · ');
  const cls = decision === 'rejected' ? 'rejected' : STATUS_CLASS(status);
  return `<span class="status-pill ${cls}">${escapeHtml(label)}</span>`;
}
function renderRecent(records) {
  const body = $('#recentTable');
  if (!records?.length) { body.innerHTML = '<tr><td colspan="6" class="table-empty">No invoices yet. Upload your first document to get started.</td></tr>'; return; }
  body.innerHTML = records.slice(0,7).map(r => `<tr><td>${vendorCell(r)}</td><td>${escapeHtml(prettyDate(r.invoice_date))}</td><td class="amount-cell">${escapeHtml(money(r.total_amount))}</td><td><span class="method-label">${escapeHtml(r.extraction_method || '—')}</span></td><td>${statusPill(r.status,r.review_decision)}</td><td><button class="row-action" data-open-invoices title="View all invoices">↗</button></td></tr>`).join('');
}

function renderInvoiceRows(records) {
  const body = $('#invoiceTable');
  $('#invoiceCountLabel').textContent = `${records.length} invoice${records.length === 1 ? '' : 's'}`;
  if (!records.length) { body.innerHTML = '<tr><td colspan="8" class="table-empty">No matching invoices. Try a different search or upload a document.</td></tr>'; return; }
  body.innerHTML = records.map(r => `<tr><td>${vendorCell(r)}</td><td>${escapeHtml(r.invoice_number || '—')}</td><td>${escapeHtml(prettyDate(r.invoice_date))}</td><td class="amount-cell">${escapeHtml(money(r.total_amount))}</td><td><span class="method-label">${escapeHtml(r.extraction_method || '—')}</span></td><td>${statusPill(r.status,r.review_decision)}</td><td>${r.reviewed ? '<span class="method-label">Reviewed</span>' : (r.status === 'Auto-Approved' ? '<span class="method-label">Automatic</span>' : '<span class="method-label">Pending</span>')}</td><td><button class="row-action" data-review-id="${r.id}" title="Review invoice">···</button></td></tr>`).join('');
}

async function loadInvoices() {
  try {
    const q = encodeURIComponent($('#invoiceSearch').value.trim());
    const status = encodeURIComponent($('#statusFilter').value);
    const data = await api(`/api/invoices?q=${q}&status=${status}`);
    state.invoices = data.invoices || [];
    renderInvoiceRows(state.invoices);
  } catch (error) { toast(error.message); }
}

function renderReview() {
  const pending = state.dashboard?.pending || [];
  $('#queueTotal').textContent = pending.length;
  const root = $('#reviewList');
  if (!pending.length) {
    root.innerHTML = '<div class="panel empty-state"><div class="empty-illustration">✓</div><h3>All caught up.</h3><p>There are no invoices waiting for your review.</p></div>';
    return;
  }
  root.innerHTML = pending.map(r => {
    const reasons = (r.flag_reasons || '').split(',').map(x => x.trim()).filter(Boolean);
    return `<article class="review-card"><div><div class="review-card-top">${statusPill(r.status)}<span class="method-label">#${r.id}</span></div><h3>${escapeHtml(r.vendor || 'Unknown vendor')}</h3><div class="review-amount">${escapeHtml(money(r.total_amount))}</div><div class="review-meta"><span>Invoice ${escapeHtml(r.invoice_number || 'number unavailable')}</span><span>${escapeHtml(prettyDate(r.invoice_date))}</span><span>${escapeHtml(r.source_file || '')}</span></div><div class="reason-list">${(reasons.length ? reasons : ['Requires a human decision']).map(x => `<span class="reason-tag">${escapeHtml(x)}</span>`).join('')}</div></div><div class="review-actions"><button class="button button-approve" data-decision="approved" data-id="${r.id}">✓ Approve</button><button class="button button-reject" data-decision="rejected" data-id="${r.id}">× Reject</button></div></article>`;
  }).join('');
}

function renderVendors() {
  const vendors = state.dashboard?.vendors || [];
  $('#vendorCount').textContent = vendors.length;
  $('#vendorSpend').textContent = money(state.dashboard?.metrics?.total_spend || 0);
  $('#vendorRisks').textContent = vendors.filter(v => v.risk_signals?.length).length;
  const root = $('#vendorList');
  if (!vendors.length) { root.innerHTML = '<div class="table-empty">Vendor profiles will appear here after processing your first invoices.</div>'; return; }
  root.innerHTML = vendors.map(v => `<div class="vendor-item"><div class="vendor-main"><span class="vendor-avatar">${escapeHtml(initials(v.vendor))}</span><div><strong>${escapeHtml(v.vendor)}</strong><small>${v.invoice_count} invoice${v.invoice_count === 1 ? '' : 's'} on record</small></div></div><div class="vendor-kpi"><span>TOTAL SPEND</span><strong>${escapeHtml(money(v.total_spend))}</strong></div><div class="vendor-kpi"><span>AVERAGE INVOICE</span><strong>${escapeHtml(money(v.average_invoice))}</strong></div><div class="vendor-kpi"><span>AUTO-APPROVAL</span><strong>${v.auto_approval_rate}%</strong></div><div class="risk-list">${v.risk_signals?.length ? v.risk_signals.map(s => `<span class="risk-chip">${escapeHtml(s)}</span>`).join('') : '<span class="risk-clear">No risk signals</span>'}</div></div>`).join('');
}

async function refreshDashboard() {
  try {
    const data = await api('/api/dashboard');
    state.dashboard = data;
    renderMetrics(data); renderChart(data.monthly_spend); renderDonut(data.statuses, data.metrics.total_invoices); renderRecent(data.recent); renderReview(); renderVendors();
  } catch (error) { toast(error.message); }
}

function openUpload() { $('#uploadModal').classList.add('open'); $('#uploadModal').setAttribute('aria-hidden','false'); }
function closeUpload() { $('#uploadModal').classList.remove('open'); $('#uploadModal').setAttribute('aria-hidden','true'); $('#uploadError').textContent = ''; }
function setFiles(fileList) {
  const allowed = ['.pdf','.jpg','.jpeg','.png','.tiff','.bmp'];
  const files = [...fileList];
  const accepted = files.filter(file => allowed.includes(file.name.slice(file.name.lastIndexOf('.')).toLowerCase()));
  const rejected = files.filter(file => !accepted.includes(file));
  state.selectedFiles = accepted;
  $('#selectedFiles').innerHTML = accepted.map(f => `<div class="file-chip"><span>▧</span><span>${escapeHtml(f.name)}</span><small>${(f.size/1024/1024).toFixed(2)} MB</small></div>`).join('');
  $('#processButton').disabled = !accepted.length || accepted.reduce((sum,f)=>sum+f.size,0) > 25*1024*1024;
  $('#uploadError').textContent = rejected.length ? `${rejected.length} unsupported file(s) were skipped.` : (accepted.reduce((sum,f)=>sum+f.size,0) > 25*1024*1024 ? 'The combined upload exceeds 25 MB.' : '');
}

async function submitUpload(event) {
  event.preventDefault();
  if (!state.selectedFiles.length) return;
  const form = new FormData(); state.selectedFiles.forEach(file => form.append('files',file));
  $('#processButton').disabled = true; $('#uploadProgress').classList.add('show'); $('#uploadError').textContent = '';
  try {
    const result = await api('/api/upload',{method:'POST',body:form});
    state.dashboard = result.dashboard;
    renderMetrics(state.dashboard); renderChart(state.dashboard.monthly_spend); renderDonut(state.dashboard.statuses,state.dashboard.metrics.total_invoices); renderRecent(state.dashboard.recent); renderReview(); renderVendors();
    closeUpload(); state.selectedFiles = []; $('#selectedFiles').innerHTML = ''; $('#fileInput').value = ''; $('#uploadProgress').classList.remove('show');
    toast(`${result.result.processed} document(s) processed successfully.`);
    if ($('#view-invoices').classList.contains('active-view')) loadInvoices();
  } catch (error) {
    $('#uploadError').textContent = error.message;
    $('#uploadProgress').classList.remove('show');
  } finally { $('#processButton').disabled = !state.selectedFiles.length; }
}

async function reviewInvoice(id, decision) {
  const label = decision === 'approved' ? 'approve' : 'reject';
  if (!window.confirm(`Are you sure you want to ${label} invoice #${id}?`)) return;
  try {
    const result = await api(`/api/invoices/${id}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision})});
    state.dashboard = result.dashboard;
    renderMetrics(state.dashboard); renderChart(state.dashboard.monthly_spend); renderDonut(state.dashboard.statuses,state.dashboard.metrics.total_invoices); renderRecent(state.dashboard.recent); renderReview(); renderVendors();
    if ($('#view-invoices').classList.contains('active-view')) loadInvoices();
    toast(`Invoice #${id} ${decision}.`);
  } catch (error) { toast(error.message); }
}

let toastTimer;
function toast(message) {
  const el = $('#toast'); el.textContent = message; el.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'),3200);
}

function init() {
  $('#todayLabel').textContent = new Date().toLocaleDateString(undefined,{weekday:'short',day:'2-digit',month:'short',year:'numeric'}).toUpperCase();
  $$('.nav-link').forEach(btn => btn.addEventListener('click',()=>setView(btn.dataset.view)));
  $$('[data-go="invoices"]').forEach(btn => btn.addEventListener('click',()=>setView('invoices')));
  $('#recentTable').addEventListener('click',e => { if (e.target.closest('[data-open-invoices]')) setView('invoices'); });
  $('#invoiceTable').addEventListener('click',e => { const btn=e.target.closest('[data-review-id]'); if(btn){ const id=Number(btn.dataset.reviewId); const record=state.invoices.find(x=>x.id===id); if(record && record.status!=='Auto-Approved' && !record.reviewed) setView('review'); else toast(`${record?.vendor || 'Invoice'} · ${record?.status || 'Record'}`); }});
  $('#reviewList').addEventListener('click',e => { const btn=e.target.closest('[data-decision]'); if(btn) reviewInvoice(Number(btn.dataset.id),btn.dataset.decision); });
  ['#openUpload','#heroUpload','#invoiceUpload'].forEach(id => $(id).addEventListener('click',openUpload));
  $('#closeUpload').addEventListener('click',closeUpload);
  $('#uploadModal').addEventListener('click',e=>{if(e.target.id==='uploadModal')closeUpload();});
  $('#fileInput').addEventListener('change',e=>setFiles(e.target.files));
  $('#dropZone').addEventListener('dragover',e=>{e.preventDefault();$('#dropZone').classList.add('dragover');});
  $('#dropZone').addEventListener('dragleave',()=>$('#dropZone').classList.remove('dragover'));
  $('#dropZone').addEventListener('drop',e=>{e.preventDefault();$('#dropZone').classList.remove('dragover');setFiles(e.dataTransfer.files);});
  $('#uploadForm').addEventListener('submit',submitUpload);
  $('#invoiceSearch').addEventListener('input',()=>{clearTimeout(window.searchDelay);window.searchDelay=setTimeout(loadInvoices,220);});
  $('#statusFilter').addEventListener('change',loadInvoices);
  $('#exportButton').addEventListener('click',()=>{window.location.href='/api/export';});
  $('#refreshButton').addEventListener('click',async()=>{await refreshDashboard();if($('#view-invoices').classList.contains('active-view'))loadInvoices();toast('Workspace refreshed.');});
  $('#mobileMenu').addEventListener('click',()=>$('#sidebar').classList.toggle('open'));
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeUpload();});
  refreshDashboard();
}
document.addEventListener('DOMContentLoaded',init);
