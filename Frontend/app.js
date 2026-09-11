const state = { current: 'dashboard', selectedFile: null, currentResult: null, user: null };
const $ = (selector) => document.querySelector(selector);
const formatRisk = (score) => score >= 81 ? 'CRITICAL' : score >= 61 ? 'HIGH' : score >= 31 ? 'MEDIUM' : 'LOW';
const riskClass = (score) => `badge-${formatRisk(score).toLowerCase()}`;

function normalizeDocumentTypeOptions() {
  document.querySelectorAll('#document-type option, #history-type option').forEach((option) => {
    if (option.textContent === 'National ID') option.textContent = 'Voter Card';
    if (option.textContent === 'Permit') option.textContent = 'Aadhaar Card';
  });
}

function navigate(view) {
  state.current = view;
  document.querySelectorAll('[data-view]').forEach((element) => element.classList.toggle('active', element.dataset.view === view));
  document.querySelectorAll('.view').forEach((element) => element.classList.toggle('hidden', element.id !== `view-${view}`));
  const pageName = ({ dashboard:'Operations overview', screening:'New document screening', ocr:'OCR extraction', validation:'Document validation', tampering:'Tampering detection', face:'Face verification', risk:'Risk assessment', result:'Screening report', history:'Screening history', settings:'System settings', governance:'TrustID governance' })[view] || 'Operations overview';
  $('#page-title').textContent = pageName; $('#page-heading').textContent = pageName;
  $('#sidebar').classList.remove('open');
  if (view === 'dashboard') loadDashboard();
  if (view === 'history') loadHistory();
  if (view === 'result') loadReport();
  if (view === 'governance') { loadGovernance(); if (window.loadTrustReferences) window.loadTrustReferences(); }
}

function renderRecent(rows) {
  $('#recent-table').innerHTML = rows.map((row) => `<tr><td><strong>${row.screening_id}</strong></td><td>${row.document_type}</td><td><small class="muted">${row.created_at}</small></td><td><strong>${row.risk_score}</strong></td><td><span class="badge ${riskClass(row.risk_score)}">${formatRisk(row.risk_score)}</span></td><td><span class="status-${row.status === 'Verified' ? 'pass' : 'review'}">${row.status}</span></td></tr>`).join('');
}

async function readResponse(response) {
  const data = await response.json().catch(() => ({ error: 'The server returned an invalid response.' }));
  if (!response.ok) throw new Error(data.error || 'The request failed.');
  return data;
}

async function loadDashboard() {
  $('#dashboard-loading').classList.remove('hidden');
  const data = await readResponse(await fetch('/dashboard-stats'));
  $('#stat-total').textContent = data.total; $('#stat-verified').textContent = data.verified; $('#stat-review').textContent = data.review; $('#stat-high').textContent = data.high_risk;
  $('#dist-bars').innerHTML = Object.entries(data.distribution).map(([label, value]) => `<div class="bar" style="height:${Math.max(12, value / Math.max(1, data.total) * 160)}px"><span>${label.toUpperCase()}<br>${value}</span></div>`).join('');
  renderRecent(data.recent);
  $('#dashboard-loading').classList.add('hidden');
}

async function loadHistory() {
  const rows = await readResponse(await fetch('/screening-history'));
  const query = $('#history-search').value.toLowerCase(); const level = $('#history-level').value; const type = $('#history-type').value;
  const filtered = rows.filter((row) => (!query || `${row.screening_id} ${row.document_type}`.toLowerCase().includes(query)) && (!level || formatRisk(row.risk_score) === level) && (!type || row.document_type === type));
  $('#history-table').innerHTML = filtered.map((row) => `<tr><td><strong>${row.screening_id}</strong></td><td>${row.date}</td><td>${row.document_type}</td><td><span class="badge ${riskClass(row.risk_score)}">${row.risk_score}</span></td><td>${formatRisk(row.risk_score)}</td><td>${row.status}</td><td>${row.review_required === 'Yes' ? '<span class="status-review">Review</span>' : '<span class="status-pass">Clear</span>'}</td></tr>`).join('');
}

function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' })[character]); }

async function governanceAction(url, options = {}) {
  const response = await fetch(url, options);
  const result = await readResponse(response);
  await loadGovernance();
  return result;
}

async function loadGovernance() {
  const [reviews, datasets, models] = await Promise.all([
    readResponse(await fetch('/reviews')),
    readResponse(await fetch('/datasets')),
    readResponse(await fetch('/models')),
  ]);
  $('#governance-reviews').innerHTML = reviews.map((item) => `<tr><td>${escapeHtml(item.screening_id)}</td><td>${escapeHtml(item.document_type)}</td><td>${escapeHtml(item.risk_score)}</td><td>${escapeHtml(item.trusted_label || 'PENDING')}</td><td><select class="form-select form-select-sm review-label" data-case="${escapeHtml(item.screening_id)}"><option>GENUINE</option><option>SUSPICIOUS</option><option>FRAUDULENT</option><option>UNCERTAIN</option></select><button class="btn btn-sm btn-outline-light mt-2 save-review" data-case="${escapeHtml(item.screening_id)}">Save label</button></td></tr>`).join('');
  $('#governance-datasets').innerHTML = datasets.map((item) => `<tr><td>${escapeHtml(item.version)}</td><td>${escapeHtml(item.status)}</td><td>${escapeHtml(item.sample_count)}</td><td>${escapeHtml(JSON.stringify(item.class_distribution || {}))}</td><td>${escapeHtml(item.created_at)}</td><td>${item.status === 'DRAFT' ? `<button class="btn btn-sm btn-outline-light publish-dataset" data-version="${escapeHtml(item.version)}">Publish</button>` : ''}</td></tr>`).join('');
  $('#governance-models').innerHTML = models.map((item) => `<tr><td>${escapeHtml(item.version)}</td><td>${escapeHtml(item.status)}</td><td>${escapeHtml(item.dataset_version)}</td><td>${escapeHtml(item.algorithm)}</td><td>${escapeHtml(item.evaluation?.accuracy == null ? 'INSUFFICIENT DATA' : `F1 ${item.evaluation.f1}`)}</td><td>${escapeHtml(item.approved_by || '—')}</td><td>${item.status === 'EVALUATED' ? `<button class="btn btn-sm btn-outline-light approve-model" data-version="${escapeHtml(item.version)}">Approve</button>` : ''}${item.status === 'APPROVED' ? `<button class="btn btn-sm btn-primary activate-model ms-2" data-version="${escapeHtml(item.version)}">Activate</button>` : ''}</td></tr>`).join('');
  document.querySelectorAll('.save-review').forEach((button) => button.addEventListener('click', async () => { const label = document.querySelector(`.review-label[data-case="${button.dataset.case}"]`).value; try { await governanceAction('/review', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ screening_id:button.dataset.case, trusted_label:label }) }); } catch (error) { alert(error.message); } }));
  document.querySelectorAll('.publish-dataset').forEach((button) => button.addEventListener('click', async () => { try { await governanceAction(`/datasets/${button.dataset.version}/publish`, { method:'POST' }); } catch (error) { alert(error.message); } }));
  document.querySelectorAll('.approve-model').forEach((button) => button.addEventListener('click', async () => { try { await governanceAction(`/models/${button.dataset.version}/approve`, { method:'POST' }); } catch (error) { alert(error.message); } }));
  document.querySelectorAll('.activate-model').forEach((button) => button.addEventListener('click', async () => { try { await governanceAction(`/models/${button.dataset.version}/activate`, { method:'POST' }); } catch (error) { alert(error.message); } }));
}

function setupGovernanceInterface() {
  $('#sidebar').insertAdjacentHTML('beforeend', '<div class="nav-label">Governance</div><div class="nav-link" data-view="governance"><i class="bi bi-diagram-3"></i>TrustID governance</div>');
  $('.main').insertAdjacentHTML('beforeend', `<div id="view-governance" class="view hidden"><div class="screening-intro"><div><div class="eyebrow mb-2">GOVERNED LEARNING / HUMAN REVIEW</div><h2>TrustID governance</h2><p class="muted mb-0">Human labels are the only source of training truth. Models remain advisory screening signals.</p></div><button id="create-dataset" class="btn btn-primary">Create dataset version</button></div><div class="panel mt-4"><div class="card-head"><h3 class="section-title">Human verification queue</h3><span class="muted small">Assign trusted labels</span></div><div class="table-wrap"><table class="table"><thead><tr><th>Case</th><th>Type</th><th>Risk</th><th>Label</th><th>Action</th></tr></thead><tbody id="governance-reviews"></tbody></table></div></div><div class="panel mt-4"><div class="card-head"><h3 class="section-title">Dataset versions</h3><span class="muted small">Published versions are immutable</span></div><div class="table-wrap"><table class="table"><thead><tr><th>Version</th><th>Status</th><th>Samples</th><th>Classes</th><th>Created</th><th>Action</th></tr></thead><tbody id="governance-datasets"></tbody></table></div></div><div class="panel mt-4"><div class="card-head"><h3 class="section-title">Model lifecycle</h3><span class="muted small">Train, approve, activate</span></div><div class="d-flex gap-2 mb-3"><input id="train-dataset-version" class="form-control" placeholder="Published dataset version"><button id="train-model" class="btn btn-outline-light">Train model</button></div><div class="table-wrap"><table class="table"><thead><tr><th>Version</th><th>Status</th><th>Dataset</th><th>Algorithm</th><th>Metric</th><th>Approved by</th><th>Action</th></tr></thead><tbody id="governance-models"></tbody></table></div></div></div>`);
  $('#create-dataset').addEventListener('click', async () => { try { await governanceAction('/datasets', { method:'POST' }); } catch (error) { alert(error.message); } });
  $('#train-model').addEventListener('click', async () => { try { await governanceAction('/models/train', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ dataset_version:$('#train-dataset-version').value.trim() }) }); } catch (error) { alert(error.message); } });
}

function setupReferenceInterface() {
  $('#view-governance').insertAdjacentHTML('beforeend', `<div class="panel mt-4"><div class="card-head"><div><h3 class="section-title">Trusted Reference records</h3><div class="muted small">Admin-only project-owned references. No government verification is implied.</div></div><button id="refresh-references" class="btn btn-sm btn-outline-light">Refresh</button></div><div class="row g-2 mb-3"><div class="col-md-3"><input id="reference-type" class="form-control" placeholder="Document type" value="Passport"></div><div class="col-md-3"><input id="reference-number" class="form-control" placeholder="Document number"></div><div class="col-md-4"><input id="reference-fields" class="form-control" placeholder='Fields JSON, e.g. {"name":"..."}'></div><div class="col-md-2"><button id="create-reference" class="btn btn-primary w-100">Create</button></div></div><div class="table-wrap"><table class="table"><thead><tr><th>Reference</th><th>Type</th><th>Fields</th><th>Created</th></tr></thead><tbody id="reference-table"></tbody></table></div></div>`);
  async function loadReferences() {
    try {
      const references = await readResponse(await fetch('/references'));
      $('#reference-table').innerHTML = references.map((item) => `<tr><td>${escapeHtml(item.reference_id)}</td><td>${escapeHtml(item.document_type)}</td><td>${escapeHtml(JSON.stringify(item.fields))}</td><td>${escapeHtml(item.created_at)}</td></tr>`).join('');
    } catch (error) { $('#reference-table').innerHTML = `<tr><td colspan="4" class="muted">${escapeHtml(error.message)}</td></tr>`; }
  }
  window.loadTrustReferences = loadReferences;
  $('#refresh-references').addEventListener('click', loadReferences);
  $('#create-reference').addEventListener('click', async () => { try { const fields = JSON.parse($('#reference-fields').value || '{}'); await readResponse(await fetch('/references', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ document_type:$('#reference-type').value.trim(), document_number:$('#reference-number').value.trim(), fields }) })); $('#reference-number').value = ''; $('#reference-fields').value = ''; await loadReferences(); } catch (error) { alert(error.message); } });
}

function showResult(result) {
  state.currentResult = result;
  $('#result-id').textContent = result.screening_id; $('#result-time').textContent = result.created_at; $('#result-type').textContent = result.document_type; $('#result-filename').textContent = result.filename;
  $('#result-ocr-fields').innerHTML = Object.entries(result.ocr.fields).map(([key, value]) => `<div class="col-md-6"><div class="field-card"><div class="field-label">${key}</div><div class="field-value">${value}</div></div></div>`).join('');
  $('#result-validation-list').innerHTML = result.validation.map((item) => `<div class="d-flex gap-3 align-items-start border-bottom border-secondary-subtle py-3"><span class="badge status-${item.status.toLowerCase()}">${item.status === 'PASS' ? '✓' : item.status === 'REVIEW' ? '⚠' : '✕'} ${item.status}</span><div><strong>${item.label}</strong><div class="muted small mt-1">${item.detail}</div></div></div>`).join('');
  $('#result-tampering-risk').textContent = `${result.tampering.risk}%`; $('#tampering-copy').textContent = result.tampering.explanation; $('#result-tampering-regions').innerHTML = result.tampering.regions.map((item) => `<span class="badge badge-medium me-1">${item}</span>`).join('');
  $('#result-face-score').textContent = `${result.face.similarity}%`; $('#face-status').textContent = result.face.status; $('#face-detail').textContent = result.face.detail;
  $('#report-face-detected').textContent = result.face.detected ? 'Face detected' : 'Face not reliably detected'; $('#report-face-status').textContent = result.face.status; $('#result-risk-score').textContent = `${result.risk.score}/100`; $('#result-risk-level').textContent = `${result.risk.level} RISK`; $('#result-status').textContent = 'COMPLETED'; $('#final-report-status').textContent = result.risk.score >= 31 ? 'REVIEW REQUIRED' : 'VERIFIED WITH REVIEW'; $('#risk-factors').innerHTML = result.risk.reasons.map((reason, index) => `<div class="factor-row"><div class="factor-label"><span>${reason}</span><strong>${[72,58,43][index] || 36}%</strong></div><div class="factor-track"><span style="width:${[72,58,43][index] || 36}%"></span></div></div>`).join(''); $('#risk-score-caption').textContent = result.risk.recommendation; $('#risk-score').textContent = result.risk.score; $('#risk-level').textContent = result.risk.level; $('#risk-ring').style.background = `conic-gradient(${result.risk.score >= 61 ? 'var(--red)' : 'var(--amber)'} 0 ${result.risk.score}%, #17364d ${result.risk.score}% 100%)`; $('#risk-reasons').innerHTML = result.risk.reasons.map((reason) => `<li>${reason}</li>`).join(''); $('#recommendation').textContent = result.risk.recommendation; $('#result-recommendation').textContent = result.risk.recommendation;
  renderTrustIdResult(result);
}

async function loadReport() {
  if (state.currentResult) return;
  const history = await readResponse(await fetch('/screening-history'));
  const response = await fetch(`/screening/${history[0]?.screening_id || 'SCR-24091'}`);
  if (response.ok) showResult(await response.json());
}

function setupReportInterface() {
  $('#view-result').innerHTML = `<div class="report-toolbar"><div><div class="eyebrow">INTERNAL SECURITY ANALYSIS / PROTOTYPE</div><h2>Screening report</h2><p class="muted mb-0">A structured decision-support summary for authorized review.</p></div><div class="report-actions"><button id="download-report" class="btn btn-outline-light"><i class="bi bi-download me-2"></i>Download Report</button><button id="print-report" class="btn btn-outline-light"><i class="bi bi-printer me-2"></i>Print</button></div></div><div class="report-notice"><i class="bi bi-info-circle me-2"></i><strong>Prototype AI Result:</strong> This report contains synthetic data and advisory indicators. It does not determine guilt, prove forgery, or make final entry decisions.</div><div class="report-sheet"><div class="report-identity"><div><span class="report-kicker">SCREENING ID</span><strong id="result-id">SCR-24091</strong></div><div><span class="report-kicker">DATE & TIME</span><strong id="result-time">2026-09-05 09:42</strong></div><div><span class="report-kicker">DOCUMENT TYPE</span><strong id="result-type">Passport</strong></div><div><span class="report-kicker">PROCESSING STATUS</span><strong id="result-status" class="text-success">COMPLETED</strong></div></div><section class="report-section"><div class="report-section-heading"><span class="section-number">01</span><div><h3>Extracted information</h3><p>OCR fields from the synthetic source document.</p></div></div><div id="result-ocr-fields" class="report-fields"></div></section><section class="report-section"><div class="report-section-heading"><span class="section-number">02</span><div><h3>Validation</h3><p>Rule-based checks requiring analyst confirmation.</p></div></div><div id="result-validation-list" class="validation-report-list"></div></section><div class="report-two-column"><section class="report-section"><div class="report-section-heading"><span class="section-number">03</span><div><h3>Tampering analysis</h3><p>Image-forensics indicators, not proof of forgery.</p></div></div><div class="signal-score"><span>Tampering indicator score</span><strong id="result-tampering-risk">38%</strong></div><div class="report-label">Suspicious regions</div><div id="result-tampering-regions" class="report-tags"></div><div class="report-label mt-3">Image-forensics indicators</div><div class="indicator-list"><span><i class="bi bi-dot"></i>Compression variation</span><span><i class="bi bi-dot"></i>Portrait boundary variance</span><span><i class="bi bi-dot"></i>Metadata unavailable</span></div><p id="tampering-copy" class="report-explanation">Potential anomaly detected. Requires manual verification.</p></section><section class="report-section"><div class="report-section-heading"><span class="section-number">04</span><div><h3>Face verification</h3><p>Comparison signal from authorized imagery.</p></div></div><div class="face-result"><div class="face-result-icon"><i class="bi bi-person-check"></i></div><div><strong id="report-face-detected">Face detected</strong><span>Document photograph</span></div></div><div class="face-score-line"><span>Similarity score</span><strong id="result-face-score">91%</strong></div><div class="face-score-line"><span>Match status</span><strong id="report-face-status" class="status-pass">LIKELY MATCH</strong></div><p id="face-detail" class="report-explanation">Face comparison is a prototype signal and requires authorized human review.</p></section></div><section class="report-section risk-report-section"><div class="report-section-heading"><span class="section-number">05</span><div><h3>Risk assessment</h3><p>Composite prototype score from the screening pipeline.</p></div></div><div class="risk-report-grid"><div class="risk-score-display"><span>Risk score</span><strong id="result-risk-score">42/100</strong><b id="result-risk-level">MEDIUM RISK</b><small>Prototype signal</small></div><div class="risk-factors"><div class="report-label">Contributing factors</div><div id="risk-factors"><div class="factor-row"><div class="factor-label"><span>Potential image-region anomaly</span><strong>72%</strong></div><div class="factor-track"><span style="width:72%"></span></div></div></div></div></div><div class="report-final-status"><span>Final status</span><strong id="final-report-status">REVIEW REQUIRED</strong></div></section><section class="recommendation-panel"><div><span class="report-kicker">RECOMMENDATION</span><h3>Manual verification recommended.</h3><p id="risk-score-caption"><span id="result-recommendation">Refer for manual verification before any operational decision.</span></p></div><span class="badge badge-medium"><i class="bi bi-person-check me-1"></i>Human review</span></section></div><div class="report-footer-actions"><button id="back-dashboard" class="btn btn-outline-light"><i class="bi bi-arrow-left me-2"></i>Back to Dashboard</button><button id="new-screening-report" class="btn btn-primary"><i class="bi bi-plus-lg me-2"></i>New Screening</button></div>`;
  $('#result-type').parentElement.insertAdjacentHTML('afterend', '<div><span class="report-kicker">FILENAME</span><strong id="result-filename">synthetic-document-demo.png</strong></div>');
  $('#risk-score-caption').insertAdjacentHTML('afterend', '<span id="result-recommendation" class="visually-hidden"></span>');
  $('#back-dashboard').addEventListener('click', () => navigate('dashboard')); $('#new-screening-report').addEventListener('click', () => navigate('screening'));
}

function setupEvidenceInterface() {
  $('#view-result').insertAdjacentHTML('afterbegin', `<div id="trustid-result-panel" class="panel trustid-result-panel"><div class="trustid-result-head"><div><div class="eyebrow">TRUSTID / STRUCTURED EVIDENCE</div><h2 id="trustid-decision">REVIEW</h2><p class="muted mb-0">Automated screening is advisory. It is not a legal fraud determination or government authenticity decision.</p></div><span id="trustid-decision-level" class="badge badge-medium">MEDIUM RISK</span></div><div class="trustid-section-grid"><section><h3>Document</h3><div id="trustid-document-metrics" class="trustid-metrics"></div></section><section><h3>OCR and extraction</h3><div id="trustid-ocr-metrics" class="trustid-metrics"></div><div id="trustid-extracted-fields" class="trustid-tags"></div></section><section><h3>Validation</h3><div id="trustid-validation-metrics" class="trustid-metrics"></div><div id="trustid-validation-findings" class="trustid-findings"></div></section><section><h3>MRZ analysis</h3><div id="trustid-mrz-metrics" class="trustid-metrics"></div><div id="trustid-mrz-errors" class="trustid-findings"></div></section><section><h3>Image and face signals</h3><div id="trustid-image-metrics" class="trustid-metrics"></div><div id="trustid-image-findings" class="trustid-findings"></div></section><section><h3>Trusted Reference</h3><div id="trustid-reference-metrics" class="trustid-metrics"></div></section></div><section class="trustid-wide-section"><h3>Deterministic risk evidence</h3><div id="trustid-risk-reasons" class="trustid-findings"></div></section><section class="trustid-wide-section"><div class="d-flex justify-content-between align-items-center gap-2"><h3>ML screening signal</h3><span class="muted small">Additional signal only</span></div><div id="trustid-ml-metrics" class="trustid-metrics"></div><div id="trustid-ml-influences" class="trustid-influences"></div></section><section class="trustid-wide-section"><h3>Human verification</h3><div id="trustid-review-metrics" class="trustid-metrics"></div></section><div id="trustid-lineage" class="trustid-lineage"></div></div>`);
}

function metric(label, value) { return `<div class="trustid-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`; }

function renderTrustIdResult(result) {
  const evidence = result.evidence || {};
  const validation = evidence.validation || result.validation || [];
  const mrz = evidence.mrz || {};
  const tampering = evidence.tampering || result.tampering || {};
  const face = evidence.face || result.face || {};
  const reference = evidence.reference || {};
  const fields = evidence.extracted_fields || result.ocr?.fields || {};
  const missing = validation.filter((item) => item.status !== 'PASS' && String(item.detail || '').toLowerCase().includes('missing')).length;
  const invalid = validation.filter((item) => item.status === 'FAIL' && !String(item.detail || '').toLowerCase().includes('missing')).length;
  const decision = result.decision || (result.risk.score >= 61 ? 'SUSPICIOUS' : result.risk.score >= 31 ? 'REVIEW' : 'CLEAR');
  $('#trustid-decision').textContent = decision;
  $('#trustid-decision-level').textContent = `${result.risk.level} RISK`;
  $('#trustid-decision-level').className = `badge ${riskClass(result.risk.score)}`;
  $('#trustid-document-metrics').innerHTML = metric('Document type', evidence.document_type || result.document_type) + metric('Classification', `${Math.round((evidence.classification?.classification_confidence || 0) * 100)}%`) + metric('File', result.filename);
  $('#trustid-ocr-metrics').innerHTML = metric('Completeness', `${Math.round((evidence.ocr_completeness || 0) * 100)}%`) + metric('Confidence', `${Math.round((evidence.ocr_confidence || (result.ocr.confidence / 100)) * 100)}%`) + metric('Source', result.ocr.ocr_source || 'UNKNOWN');
  $('#trustid-extracted-fields').innerHTML = Object.entries(fields).map(([key, value]) => `<span class="badge badge-verified">${escapeHtml(key)}: ${escapeHtml(value)}</span>`).join('') || '<span class="muted small">No structured fields extracted.</span>';
  $('#trustid-validation-metrics').innerHTML = metric('Issues', validation.filter((item) => item.status !== 'PASS').length) + metric('Invalid fields', invalid) + metric('Missing fields', missing) + metric('Expiry signal', validation.some((item) => item.label === 'Expiry status' && item.status === 'FAIL') ? '1' : '0');
  $('#trustid-validation-findings').innerHTML = validation.map((item) => `<div class="trustid-finding"><span class="badge status-${String(item.status).toLowerCase()}">${escapeHtml(item.status)}</span>${escapeHtml(item.label)}: ${escapeHtml(item.detail)}</div>`).join('');
  $('#trustid-mrz-metrics').innerHTML = metric('Available', mrz.available ? 'PASS' : 'NOT AVAILABLE') + metric('Parsed', mrz.parsed ? 'PASS' : mrz.available ? 'FAIL' : 'NOT APPLICABLE') + metric('Format', mrz.format || 'NOT AVAILABLE') + metric('Consistency', mrz.mrz_consistency || 'NOT AVAILABLE') + metric('Mismatch', mrz.mrz_mismatch ? 'FAIL' : mrz.available ? 'PASS' : 'NOT APPLICABLE');
  $('#trustid-mrz-errors').innerHTML = (mrz.mrz_errors || []).map((item) => `<div class="trustid-finding status-fail">${escapeHtml(item)}</div>`).join('') || '<div class="trustid-finding status-pass">No MRZ errors reported.</div>';
  $('#trustid-image-metrics').innerHTML = metric('Image quality', `${Math.round((1 - (Number(tampering.risk || 0) / 100)) * 100)}%`) + metric('Tampering signals', (tampering.regions || []).length) + metric('Face available', face.detected ? 'PASS' : 'NOT AVAILABLE') + metric('Face similarity', face.detected ? `${face.similarity}%` : 'NOT AVAILABLE') + metric('Face match', face.detected ? (face.similarity >= 80 ? 'PASS' : 'REVIEW') : 'NOT AVAILABLE');
  $('#trustid-image-findings').innerHTML = (tampering.regions || []).map((item) => `<div class="trustid-finding status-review">${escapeHtml(item)}</div>`).join('') || '<div class="trustid-finding status-pass">No image signals reported.</div>';
  $('#trustid-reference-metrics').innerHTML = metric('Available', reference.reference_available ? 'PASS' : 'NOT AVAILABLE') + metric('Found', reference.reference_found ? 'PASS' : reference.reference_available ? 'NOT FOUND' : 'NOT AVAILABLE') + metric('Match', reference.reference_found ? (reference.reference_match ? 'PASS' : 'FAIL') : 'NOT AVAILABLE') + metric('Field mismatches', reference.field_mismatch_count || 0);
  $('#trustid-risk-reasons').innerHTML = result.risk.reasons.map((reason) => `<div class="trustid-finding status-review">${escapeHtml(reason)}</div>`).join('');
  const ml = result.ml || { model_status: 'NOT_AVAILABLE', reason: 'ML screening unavailable - no active model.' };
  $('#trustid-ml-metrics').innerHTML = metric('Status', ml.model_status) + metric('Model', ml.model_version || 'NOT AVAILABLE') + metric('Dataset', ml.dataset_version || 'NOT AVAILABLE') + metric('Prediction', ml.prediction || 'NOT AVAILABLE') + metric('Probability', ml.probability == null ? 'NOT AVAILABLE' : `${(ml.probability * 100).toFixed(1)}%`) + metric('Confidence', ml.confidence == null ? 'NOT AVAILABLE' : `${(ml.confidence * 100).toFixed(1)}%`);
  $('#trustid-ml-influences').innerHTML = ml.top_feature_influences?.map((item) => `<div class="trustid-influence"><span>${escapeHtml(item.feature)} <small class="muted">(${escapeHtml(item.value)})</small></span><strong class="${item.contribution >= 0 ? 'text-warning' : 'text-success'}">${item.contribution >= 0 ? '+' : ''}${item.contribution} ${item.contribution >= 0 ? 'suspicious influence' : 'clearing influence'}</strong></div>`).join('') || `<div class="trustid-finding">${escapeHtml(ml.reason || 'No active model.')}</div>`;
  const review = result.review || {};
  $('#trustid-review-metrics').innerHTML = metric('Status', review.review_status || 'PENDING') + metric('Reviewer', review.reviewer || 'NOT ASSIGNED') + metric('Trusted label', review.trusted_label || 'PENDING') + metric('Reviewed', review.created_at || 'NOT REVIEWED') + metric('Notes', review.notes || '');
  $('#trustid-lineage').innerHTML = `<span>Case ${escapeHtml(result.screening_id)}</span><span>Screened ${escapeHtml(result.created_at)}</span><span>Model ${escapeHtml(ml.model_version || 'NOT AVAILABLE')}</span><span>Dataset ${escapeHtml(ml.dataset_version || 'NOT AVAILABLE')}</span>`;
}

async function startScreening() {
  const form = new FormData(); form.append('document_type', $('#document-type').value); if (state.selectedFile) form.append('document', state.selectedFile); if ($('#selfie-input').files[0]) form.append('selfie', $('#selfie-input').files[0]);
  $('#screening-progress').classList.remove('hidden'); $('#screening-button').disabled = true; $('#screening-button').innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Screening...'; setPipelineState('processing');
  const responsePromise = fetch('/upload', { method:'POST', body:form }); const [response] = await Promise.all([responsePromise, new Promise((resolve) => setTimeout(resolve, 900))]); const result = await readResponse(response);
  state.selectedFile = null; $('#screening-progress').classList.add('hidden'); $('#screening-button').disabled = false; $('#screening-button').innerHTML = '<i class="bi bi-stars me-2"></i>Start AI screening'; setPipelineState('completed'); renderScreeningSummary(result); showResult(result); navigate('result');
}

function setPipelineState(stateName) {
  document.querySelectorAll('[data-stage]').forEach((stage) => {
    stage.classList.remove('is-processing', 'is-completed');
    stage.querySelector('small').textContent = stateName === 'completed' ? 'Completed' : 'Pending';
    if (stateName === 'processing') stage.classList.add('is-processing');
    if (stateName === 'completed') stage.classList.add('is-completed');
  });
  if (stateName === 'processing') {
    const stages = [...document.querySelectorAll('[data-stage]')];
    stages.forEach((stage, index) => setTimeout(() => { stages.forEach((item) => item.classList.remove('is-processing')); stage.classList.add('is-processing'); stage.querySelector('small').textContent = 'Processing'; }, index * 140));
  }
}

function renderScreeningSummary(result) {
  $('#screening-summary').classList.remove('hidden');
  $('#summary-ocr').textContent = `${result.ocr.confidence}%`;
  $('#summary-validation').textContent = result.validation.some((item) => item.status === 'FAIL') ? 'FAIL' : result.validation.some((item) => item.status === 'REVIEW') ? 'REVIEW' : 'PASS';
  $('#summary-tampering').textContent = `${result.tampering.risk}%`;
  $('#summary-face').textContent = `${result.face.similarity}%`;
  $('#summary-risk').textContent = `${result.risk.score}/100`;
  $('#final-risk-score').textContent = `${result.risk.score}/100`;
  $('#final-risk-level').textContent = result.risk.level;
  $('#final-status').textContent = result.risk.score >= 31 ? 'REVIEW REQUIRED' : 'VERIFIED WITH REVIEW';
  $('#risk-reasons-screening').innerHTML = result.risk.reasons.map((reason) => `<li>${reason}</li>`).join('');
}

function setupUpload() {
  const zone = $('#upload-zone'); const input = $('#document-input');
  const selfieField = document.createElement('div'); selfieField.className = 'mt-3'; selfieField.innerHTML = '<label class="form-label small muted" for="selfie-input">Comparison selfie (optional)</label><input id="selfie-input" class="form-control" type="file" accept="image/png,image/jpeg,image/webp"><div class="muted small mt-1">A clear face image enables real similarity analysis.</div>'; zone.insertAdjacentElement('afterend', selfieField);
  zone.addEventListener('click', () => input.click()); input.addEventListener('change', () => handleFile(input.files[0]));
  ['dragenter','dragover'].forEach((event) => zone.addEventListener(event, (e) => { e.preventDefault(); zone.classList.add('dragover'); }));
  ['dragleave','drop'].forEach((event) => zone.addEventListener(event, (e) => { e.preventDefault(); zone.classList.remove('dragover'); })); zone.addEventListener('drop', (e) => handleFile(e.dataTransfer.files[0]));
}
function handleFile(file) { if (!file) return; if (!file.type.startsWith('image/') && file.type !== 'application/pdf') { $('#upload-message').textContent = 'Please select an image or PDF document.'; return; } state.selectedFile = file; $('#upload-message').innerHTML = `<strong>${file.name}</strong><br><span class="muted">Ready for prototype screening · ${(file.size / 1024).toFixed(1)} KB</span>`; $('#file-name').textContent = file.name; $('#file-size').textContent = `${(file.size / 1024).toFixed(1)} KB`; $('#file-type').textContent = $('#document-type').value; $('#file-resolution').textContent = file.type === 'application/pdf' ? 'PDF document' : 'Reading image...'; if (file.type.startsWith('image/')) { const image = new Image(); image.onload = () => { $('#file-resolution').textContent = `${image.naturalWidth} × ${image.naturalHeight} px`; URL.revokeObjectURL(image.src); }; image.src = URL.createObjectURL(file); } $('#screening-button').classList.add('is-ready'); }

function setupScreeningInterface() {
  const view = $('#view-screening');
  view.innerHTML = `<div class="screening-intro"><div><div class="eyebrow mb-2">SECURE INTAKE / PROTOTYPE PIPELINE</div><h2>Screen a document</h2><p class="muted mb-0">Upload synthetic evidence and review each signal before making an authorized decision.</p></div><span class="badge badge-verified"><i class="bi bi-shield-check me-1"></i>Local demo mode</span></div><div class="alert-prototype mt-4"><i class="bi bi-stars me-2"></i><strong>Prototype AI Result</strong> · Results are advisory indicators and require manual verification. The system does not prove forgery or make entry decisions.</div><div class="row g-4 mt-1"><div class="col-xl-7"><div class="panel screening-upload-panel"><div class="card-head"><div><h3 class="section-title">Document intake</h3><div class="muted small mt-1">Accepted: PNG, JPG, WEBP, PDF · maximum 10 MB</div></div><label class="screening-select-label">Document type<select id="document-type" class="form-select mt-1"><option>Passport</option><option>Visa</option><option>National ID</option><option>Driving License</option><option>Permit</option></select></label></div><div id="upload-zone" class="upload-zone"><input id="document-input" type="file" accept="image/*,.pdf" hidden><div><div class="upload-orbit"><i class="bi bi-cloud-arrow-up"></i></div><h3 class="mt-3">Drop your document here</h3><p id="upload-message" class="muted">or browse synthetic evidence from your device</p><span class="btn btn-outline-light btn-sm"><i class="bi bi-folder2-open me-2"></i>Choose document</span></div></div><div class="screening-actions"><button id="screening-button" class="btn btn-primary btn-lg"><i class="bi bi-stars me-2"></i>Start AI screening</button><div id="screening-progress" class="hidden screening-progress"><span class="spinner-border spinner-border-sm text-info me-2"></span>Processing document signals...</div></div></div><div class="panel mt-4"><div class="card-head"><h3 class="section-title">Screening pipeline</h3><span class="muted small">Signal orchestration</span></div><div class="pipeline" aria-label="Screening pipeline"><div class="pipeline-stage is-pending" data-stage="upload"><span class="pipeline-icon"><i class="bi bi-cloud-arrow-up"></i></span><strong>UPLOAD</strong><small>Pending</small></div><span class="pipeline-arrow">→</span><div class="pipeline-stage is-pending" data-stage="ocr"><span class="pipeline-icon"><i class="bi bi-file-earmark-text"></i></span><strong>OCR</strong><small>Pending</small></div><span class="pipeline-arrow">→</span><div class="pipeline-stage is-pending" data-stage="validation"><span class="pipeline-icon"><i class="bi bi-check2-square"></i></span><strong>VALIDATION</strong><small>Pending</small></div><span class="pipeline-arrow">→</span><div class="pipeline-stage is-pending" data-stage="tampering"><span class="pipeline-icon"><i class="bi bi-bezier2"></i></span><strong>TAMPERING</strong><small>Pending</small></div><span class="pipeline-arrow">→</span><div class="pipeline-stage is-pending" data-stage="face"><span class="pipeline-icon"><i class="bi bi-person-bounding-box"></i></span><strong>FACE</strong><small>Pending</small></div><span class="pipeline-arrow">→</span><div class="pipeline-stage is-pending" data-stage="risk"><span class="pipeline-icon"><i class="bi bi-speedometer2"></i></span><strong>RISK</strong><small>Pending</small></div></div></div></div><div class="col-xl-5"><div class="panel preview-panel"><div class="card-head"><h3 class="section-title">Image preview</h3><span class="badge badge-medium">Awaiting file</span></div><div class="preview-box"><div class="document-mock"><div class="portrait"></div><div class="mock-lines"><div></div><div style="width:75%"></div><div style="width:90%"></div><div></div><div style="width:62%"></div></div></div></div><div class="file-info-grid"><div><span>Filename</span><strong id="file-name">No file selected</strong></div><div><span>File size</span><strong id="file-size">—</strong></div><div><span>Resolution</span><strong id="file-resolution">—</strong></div><div><span>Document type</span><strong id="file-type">Passport</strong></div></div></div></div></div><div id="screening-summary" class="hidden"><div class="summary-heading"><div><div class="eyebrow">POST-PROCESSING REVIEW</div><h3>Screening signals</h3></div><span class="badge badge-verified"><i class="bi bi-check2-circle me-1"></i>Pipeline completed</span></div><div class="metric-strip"><div><span>OCR confidence</span><strong id="summary-ocr">—</strong></div><div><span>Validation status</span><strong id="summary-validation">—</strong></div><div><span>Tampering risk</span><strong id="summary-tampering">—</strong></div><div><span>Face similarity</span><strong id="summary-face">—</strong></div><div><span>Overall risk score</span><strong id="summary-risk">—</strong></div></div><div class="final-risk-card"><div><div class="eyebrow mb-2">PROTOTYPE AI RESULT</div><div class="final-risk-score" id="final-risk-score">72/100</div><div class="final-risk-caption">Risk score</div></div><div class="final-risk-level"><span id="final-risk-level" class="badge badge-high">HIGH</span><strong id="final-status">REVIEW REQUIRED</strong><span>Requires manual verification</span></div><div class="risk-reasons"><div class="field-label mb-2">Contributing reasons</div><ul id="risk-reasons-screening"><li>Results will appear after processing.</li></ul></div></div></div></div>`;
  $('#document-type').addEventListener('change', () => { $('#file-type').textContent = $('#document-type').value; });
}

function init() {
  document.querySelectorAll('#view-dashboard').forEach((element, index) => { if (index === 0) element.remove(); });
  setupScreeningInterface();
  setupReportInterface();
  setupEvidenceInterface();
  setupGovernanceInterface();
  setupReferenceInterface();
  normalizeDocumentTypeOptions();
  document.querySelectorAll('[data-view]').forEach((element) => element.addEventListener('click', () => navigate(element.dataset.view)));
  $('#mobile-menu').addEventListener('click', () => $('#sidebar').classList.toggle('open')); $('#start-screening').addEventListener('click', () => navigate('screening')); $('#screening-button').addEventListener('click', startScreening); setupUpload();
  $('#demo-login').addEventListener('click', () => { $('#login-user').value = 'demo@screening.local'; $('#login-password').value = 'demo123'; }); $('#login-form').addEventListener('submit', async (event) => { event.preventDefault(); const button = event.target.querySelector('button[type="submit"]'); button.disabled = true; try { const loginResult = await readResponse(await fetch('/login', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ username:$('#login-user').value.trim(), password:$('#login-password').value }) })); state.user = loginResult.user; $('#login-screen').classList.add('hidden'); $('#app-shell').classList.remove('hidden'); await loadDashboard(); } catch (error) { alert(error.message); } finally { button.disabled = false; } });
  ['history-search','history-level','history-type'].forEach((id) => $(`#${id}`).addEventListener('input', loadHistory)); $('#global-search').addEventListener('input', (event) => { const query = event.target.value.trim().toLowerCase(); if (query) { navigate('history'); $('#history-search').value = query; loadHistory(); } }); $('#notification-button').addEventListener('click', () => { $('#notification-button').classList.add('has-read'); $('#notification-button').setAttribute('title', 'No new notifications'); }); $('#print-report').addEventListener('click', () => window.print()); $('#download-report').addEventListener('click', () => { const report = JSON.stringify(state.currentResult, null, 2); const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([report], {type:'application/json'})); link.download = `${state.currentResult?.screening_id || 'screening-report'}.json`; link.click(); });
}
document.addEventListener('DOMContentLoaded', init);
