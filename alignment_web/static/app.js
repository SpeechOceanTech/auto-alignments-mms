const $ = (selector) => document.querySelector(selector);
const statusNames = {queued: '排队中', running: '对齐中', completed: '已完成', failed: '失败'};
let languageChoices = [];
const state = {csrf: '', user: null, offset: 0, limit: 20, total: 0, jobs: [], selected: new Map()};
let userFilterLoadVersion = 0;
let apiKeyViewVersion = 0;
function node(tag, text, cls) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; }
function action(text, callback, cls = '') { const el = node('button', text, `text-button ${cls}`); el.type = 'button'; el.onclick = callback; return el; }
function formatTime(seconds) { if (!Number.isFinite(Number(seconds))) return '--:--'; const ms = Math.round(Math.max(0, Number(seconds)) * 1000); const hours = Math.floor(ms / 3600000); const minutes = Math.floor(ms % 3600000 / 60000); const remainder = (ms % 60000 / 1000).toFixed(3).padStart(6, '0'); return `${hours ? `${hours}:` : ''}${String(minutes).padStart(2, '0')}:${remainder}`; }
function formatDate(value) { if (value == null) return ''; const input = typeof value === 'number' ? value * 1000 : (!/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value.replace(' ', 'T') + 'Z' : value); const d = new Date(input); return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString(); }
async function request(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.method && !['GET', 'HEAD'].includes(options.method.toUpperCase()) && state.csrf) headers.set('X-CSRF-Token', state.csrf);
  const response = await fetch(url, {...options, headers});
  if (!response.ok) { let error; try { error = (await response.json()).detail; } catch (_) {} if (response.status === 401 && state.user) showAccount(null); throw new Error(typeof error === 'string' ? error : `请求失败 (${response.status})`); }
  return response.json();
}
function json(body) { return {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}; }
function showAccount(user, csrf = '') {
  const accountChanged = state.user?.id !== user?.id || !!state.user?.is_admin !== !!user?.is_admin;
  state.user = user; state.csrf = csrf;
  $('#account-panel').hidden = !!user; $('#workspace').hidden = !user; $('#logout').hidden = !user;
  $('#account-label').textContent = user ? (user.username || user.email) : '';
  $('#admin-navigation').hidden = !user; $('#tab-accounts').hidden = !user?.is_admin; $('#tab-statistics').hidden = !user?.is_admin; $('#tab-api-keys').hidden = !user?.is_admin; $('#delete-selected').hidden = !user?.is_admin; $('#job-user-header').hidden = !user?.is_admin;
  $('#filter-owner-field').hidden = !user?.is_admin; $('.job-filters').classList.toggle('admin-filters', !!user?.is_admin);
  userFilterLoadVersion++; $('#filter-owner').replaceChildren(new Option('全部用户', ''), new Option('历史任务（无用户）', '__legacy__')); if (user?.is_admin) loadFilterUsers(user.id);
  if (accountChanged || !user?.is_admin) { hideNewKey(); $('#api-key-list').textContent = ''; $('#api-key-name').value = ''; $('#api-key-message').textContent = ''; switchTab('details'); }
  if (!user) { state.selected.clear(); closeReview(); $('#account-code').value = ''; }
}
async function loadFilterUsers(userId) { const version = ++userFilterLoadVersion; try { const data = await request('/api/admin/users'); if (version !== userFilterLoadVersion || !state.user?.is_admin || state.user.id !== userId) return; const select = $('#filter-owner'), previous = select.value, previousLabel = select.selectedOptions[0]?.textContent; const options = [new Option('全部用户', ''), new Option('历史任务（无用户）', '__legacy__')]; for (const user of data.users) options.push(new Option(user.username, user.id)); if (previous && !options.some(option => option.value === previous)) options.push(new Option(previousLabel || '未知用户', previous)); select.replaceChildren(...options); select.value = previous; } catch (error) { if (version === userFilterLoadVersion && state.user?.is_admin && state.user.id === userId) $('#jobs-message').textContent = `加载用户筛选失败：${error.message}`; } }
async function checkSession() {
  try { const data = await request('/api/auth/me'); showAccount(data.user, data.csrf_token); if (data.user) { loadLanguages(); refresh(); } }
  catch (error) { showAccount(null); $('#account-message').textContent = error.message; }
}
async function health() { try { const response = await fetch('/health'); if (!response.ok) throw new Error(); $('#health').className = 'service-status online'; $('#health').title = '服务在线'; $('#health').setAttribute('aria-label', '服务在线'); } catch (_) { $('#health').className = 'service-status offline'; $('#health').title = '服务离线'; $('#health').setAttribute('aria-label', '服务离线'); } }
$('#login-code').onclick = async () => { const email = $('#account-email').value.trim(); if (!email) { $('#account-message').textContent = '请输入邮箱'; return; } $('#login-code').disabled = true; try { await request('/api/auth/request-code', json({email})); $('#account-message').textContent = '如果邮箱符合条件，验证码将发送至邮箱。'; } catch (e) { $('#account-message').textContent = e.message; } finally { $('#login-code').disabled = false; } };
$('#account-email').addEventListener('input', (event) => { event.target.value = event.target.value.replace(/@dataoceanai\.com$/i, ''); });
$('#verify-code').onclick = async () => { const email = $('#account-email').value.trim(), code = $('#account-code').value.trim(); if (!email || !code) { $('#account-message').textContent = '请输入邮箱和验证码'; return; } $('#verify-code').disabled = true; try { const data = await request('/api/auth/verify-code', json({email, code})); showAccount(data.user, data.csrf_token); $('#account-message').textContent = ''; loadLanguages(); loadBatches(); refresh(); } catch (e) { $('#account-message').textContent = e.message; } finally { $('#verify-code').disabled = false; } };
$('#account-code').addEventListener('keydown', (event) => { if (event.key === 'Enter') $('#verify-code').click(); });
$('#logout').onclick = async () => { try { await request('/api/auth/logout', {method:'POST'}); showAccount(null); } catch (e) { alert(e.message); } };
function switchTab(tab) {
  if (['statistics', 'accounts', 'keys'].includes(tab) && !state.user?.is_admin) tab = 'details';
  $('#task-detail-panel').hidden = tab !== 'details'; $('#statistics-panel').hidden = tab !== 'statistics'; $('#admin-accounts').hidden = tab !== 'accounts'; $('#api-keys-panel').hidden = tab !== 'keys';
  $('#tab-details').classList.toggle('active', tab === 'details'); $('#tab-statistics').classList.toggle('active', tab === 'statistics'); $('#tab-api-keys').classList.toggle('active', tab === 'keys'); $('#tab-accounts').classList.toggle('active', tab === 'accounts');
  if (tab !== 'keys') hideNewKey(); if (tab === 'accounts') loadUsers(); if (tab === 'keys') loadApiKeys(); if (tab === 'statistics') loadStatistics();
}
$('#tab-details').onclick = () => switchTab('details'); $('#tab-statistics').onclick = () => switchTab('statistics'); $('#tab-api-keys').onclick = () => switchTab('keys'); $('#tab-accounts').onclick = () => switchTab('accounts');
const statsNumber = number => Number(number || 0).toLocaleString('zh-CN');
const statsHours = seconds => (Number(seconds || 0) / 3600).toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2});
function renderStatsTable(target, rows, kind, totalSeconds) {
  if (!rows.length) { target.replaceChildren(node('p', '暂无已完成任务', 'stats-empty')); return; }
  const table = node('table'), thead = node('thead'), head = node('tr'), tbody = node('tbody');
  for (const label of [kind === 'language' ? '语种' : '用户', '完成任务', '音频时长', '句数', '时长占比']) head.append(node('th', label));
  thead.append(head);
  const denominator = Number(totalSeconds) || 0;
  for (const item of rows) {
    const row = node('tr');
    const code = kind === 'language' ? item.language : (item.username || '历史任务（无用户）');
    const label = kind === 'language' ? (languageChoices.find(choice => choice.code === code)?.name || code) : code;
    const name = node('td', label); if (kind === 'language' && label !== code) name.append(node('small', code, 'stats-code'));
    const duration = Number(item.audio_duration_sample_count || 0) ? `${statsHours(item.audio_seconds)} 小时${Number(item.audio_duration_sample_count) < Number(item.jobs) ? ' *' : ''}` : '—';
    const sentences = Number(item.sentence_sample_count || 0) ? `${statsNumber(item.sentence_count)}${Number(item.sentence_sample_count) < Number(item.jobs) ? ' *' : ''}` : '—';
    const metric = node('td'), bar = node('div', undefined, 'stats-bar'), fill = node('div', undefined, 'stats-bar-fill');
    const known = Number(item.audio_duration_sample_count || 0) > 0 && denominator > 0;
    const percent = known ? Math.max(0, Math.min(100, Number(item.audio_seconds || 0) / denominator * 100)) : 0; fill.style.width = `${percent}%`; bar.append(fill); metric.append(bar, node('span', known ? `${percent.toFixed(1)}%` : '—', 'stats-percent'));
    row.append(name, node('td', statsNumber(item.jobs)), node('td', duration), node('td', sentences), metric); tbody.append(row);
  }
  table.append(thead, tbody); target.replaceChildren(table);
}
async function loadStatistics() {
  if (!state.user?.is_admin) return;
  const userId = state.user.id;
  $('#stats-message').textContent = '正在加载统计…';
  try {
    const data = await request('/api/admin/usage'); if (!state.user?.is_admin || state.user.id !== userId) return;
    const total = data.totals, completed = Number(total.completed || 0);
    const metrics = [
      ['已完成任务', statsNumber(completed), '个'],
      ['音频总时长', Number(total.audio_duration_sample_count || 0) ? statsHours(total.audio_seconds) : '—', '小时'],
      ['覆盖语种', statsNumber(total.language_count), '种'],
      ['对齐句数', Number(total.sentence_sample_count || 0) ? statsNumber(total.sentence_count) : '—', '句'],
    ];
    $('#stats-summary').replaceChildren(...metrics.map(([label, value, unit]) => { const card = node('div', undefined, 'stats-metric'); const number = node('div', undefined, 'stats-metric-value'); number.append(document.createTextNode(value), node('span', unit)); card.append(node('div', label, 'stats-metric-label'), number); return card; }));
    const missingDuration = Math.max(0, completed - Number(total.audio_duration_sample_count || 0));
    const missingSentences = Math.max(0, completed - Number(total.sentence_sample_count || 0));
    $('#stats-coverage').textContent = missingDuration || missingSentences ? `部分任务数据尚未取得：${statsNumber(missingDuration)} 个任务缺少音频时长，${statsNumber(missingSentences)} 个任务缺少句数；相应合计仅包含已有数据；分布中 * 表示该项数据不完整。` : '音频时长和句数已覆盖所有已完成任务。';
    const statuses = [['queued', '排队中'], ['running', '对齐中'], ['completed', '已完成'], ['failed', '失败']];
    $('#stats-status').replaceChildren(...statuses.map(([key, label]) => { const item = node('div', undefined, 'stats-status-item'); item.append(node('span', label, `stats-status-label ${key}`), node('strong', statsNumber(data.current[key]))); return item; }));
    renderStatsTable($('#stats-languages'), data.languages || [], 'language', total.audio_seconds); renderStatsTable($('#stats-users'), data.users || [], 'user', total.audio_seconds); $('#stats-message').textContent = '';
  } catch (error) { if (state.user?.is_admin && state.user.id === userId) $('#stats-message').textContent = `加载统计失败：${error.message}`; }
}
$('#refresh-statistics').onclick = loadStatistics;
async function loadUsers() { const list = $('#user-list'); try { const data = await request('/api/admin/users'); const table = node('table'); const head = node('tr'); for (const label of ['用户名', '邮箱', '状态', '角色', '创建时间', '操作']) head.append(node('th', label)); const thead = node('thead'); thead.append(head); const tbody = node('tbody'); for (const user of data.users) { const tr = node('tr'); for (const text of [user.username, user.email, user.is_active ? '正常' : '已停用', user.is_admin ? '管理员' : '普通用户', formatDate(user.created_at)]) tr.append(node('td', text)); const cell = node('td'); const actions = node('div', undefined, 'row-actions'); if (user.id !== state.user.id) { actions.append(action(user.is_active ? '停用' : '启用', () => updateUser(user, {is_active: !user.is_active})), action(user.is_admin ? '取消管理员' : '设为管理员', () => updateUser(user, {is_admin: !user.is_admin}))); } else actions.append(node('span', '当前账号')); cell.append(actions); tr.append(cell); tbody.append(tr); } table.append(thead, tbody); list.replaceChildren(table); } catch (e) { list.replaceChildren(node('p', e.message, 'error')); } }
async function updateUser(user, patch) { if (!confirm(`确认修改 ${user.email} 的账号设置？`)) return; try { await request(`/api/admin/users/${user.id}`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)}); $('#admin-message').textContent = '账号已更新'; loadUsers(); } catch (e) { $('#admin-message').textContent = e.message; } }
$('#refresh-users').onclick = loadUsers;
function hideNewKey() { apiKeyViewVersion++; $('#api-key-secret').value = ''; $('#new-api-key').hidden = true; $('#api-key-create').disabled = false; }
function isCurrentApiKeyView(userId, version) { return !!state.user?.is_admin && state.user.id === userId && apiKeyViewVersion === version && !$('#api-keys-panel').hidden; }
async function loadApiKeys() { if (!state.user?.is_admin || $('#api-keys-panel').hidden) return; const userId = state.user.id, version = apiKeyViewVersion, list = $('#api-key-list'); try { const data = await request('/api/auth/api-keys'); if (!isCurrentApiKeyView(userId, version)) return; if (!data.keys.length) { list.replaceChildren(node('p', '暂无 API 密钥。', 'message')); return; } const table = node('table'), thead = node('thead'), header = node('tr'), tbody = node('tbody'); for (const label of ['名称', '创建时间', '最近使用', '操作']) header.append(node('th', label)); thead.append(header); for (const key of data.keys) { const row = node('tr'); row.append(node('td', key.name), node('td', formatDate(key.created_at)), node('td', key.last_used_at ? formatDate(key.last_used_at) : '从未使用')); const cell = node('td'); cell.append(action('撤销', async () => { const actionVersion = apiKeyViewVersion; if (!isCurrentApiKeyView(userId, actionVersion) || !confirm(`确定撤销密钥“${key.name}”？使用该密钥的程序将无法继续访问。`)) return; try { await request(`/api/auth/api-keys/${key.id}`, {method:'DELETE'}); if (!isCurrentApiKeyView(userId, actionVersion)) return; $('#api-key-message').textContent = '密钥已撤销'; loadApiKeys(); } catch (e) { if (isCurrentApiKeyView(userId, actionVersion)) $('#api-key-message').textContent = e.message; } }, 'danger')); row.append(cell); tbody.append(row); } table.append(thead, tbody); list.replaceChildren(table); } catch (e) { if (isCurrentApiKeyView(userId, version)) list.replaceChildren(node('p', e.message, 'error')); } }
$('#refresh-api-keys').onclick = loadApiKeys;
$('#api-key-form').onsubmit = async event => { event.preventDefault(); if (!state.user?.is_admin || $('#api-keys-panel').hidden) return; const userId = state.user.id, version = apiKeyViewVersion, name = $('#api-key-name').value.trim(); if (!name) return; $('#api-key-create').disabled = true; try { const data = await request('/api/auth/api-keys', json({name})); if (!isCurrentApiKeyView(userId, version)) return; $('#api-key-secret').value = data.token; $('#new-api-key').hidden = false; $('#api-key-name').value = ''; $('#api-key-message').textContent = ''; loadApiKeys(); } catch (e) { if (isCurrentApiKeyView(userId, version)) $('#api-key-message').textContent = e.message; } finally { if (isCurrentApiKeyView(userId, version)) $('#api-key-create').disabled = !$('#new-api-key').hidden; } };
$('#copy-api-key').onclick = async () => { const input = $('#api-key-secret'); try { if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(input.value); else { input.focus(); input.select(); if (!document.execCommand('copy')) throw new Error('copy failed'); } $('#api-key-message').textContent = '密钥已复制'; } catch (_) { input.focus(); input.select(); $('#api-key-message').textContent = '请手动复制选中的密钥'; } };
$('#close-api-key').onclick = hideNewKey;
async function loadLanguages() { try { const data = await request('/v1/languages'); languageChoices = data.languages; } catch (_) {} }
function setupLanguagePicker(inputId, optionsId) {
  const input = $(inputId), options = $(optionsId); let active = -1, matches = [];
  function close() { options.hidden = true; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); active = -1; }
  function choose(index) { const item = matches[index]; if (!item) return; input.value = item.code; close(); input.dispatchEvent(new Event('input', {bubbles:true})); close(); }
  function highlight() { [...options.querySelectorAll('[role=option]')].forEach((item, index) => { item.setAttribute('aria-selected', String(index === active)); if (index === active) { input.setAttribute('aria-activedescendant', item.id); item.scrollIntoView({block:'nearest'}); } }); }
  function draw(showAll = false) {
    const query = showAll ? '' : input.value.trim().toLowerCase().replaceAll('-', '_');
    matches = languageChoices.filter(item => [item.code, item.name, item.iso, item.english, ...(item.aliases || [])].some(value => String(value || '').toLowerCase().replaceAll('-', '_').includes(query)));
    matches.sort((a, b) => Number(b.code.toLowerCase() === query) - Number(a.code.toLowerCase() === query));
    options.replaceChildren(); active = -1;
    if (!matches.length) { close(); return; }
    matches.forEach((item, index) => {
      const el = node('div', undefined, 'language-option');
      el.id = `${options.id}-${index}`; el.setAttribute('role', 'option'); el.setAttribute('aria-selected', 'false');
      el.setAttribute('aria-label', `${item.code} ${item.name}`);
      el.append(node('span', item.code, 'language-code'), node('span', item.name, 'language-name'));
      el.onmousedown = event => event.preventDefault(); el.onclick = () => choose(index); options.append(el);
    });
    options.hidden = false; input.setAttribute('aria-expanded', 'true');
  }
  input.addEventListener('focus', () => { draw(true); input.select(); }); input.addEventListener('input', () => draw()); input.addEventListener('blur', close);
  input.addEventListener('keydown', event => { if (event.key === 'Escape') { close(); return; } if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { if (options.hidden) draw(true); if (!matches.length) return; event.preventDefault(); active = (active + (event.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length; highlight(); } else if (event.key === 'Enter' && !options.hidden && active >= 0) { event.preventDefault(); choose(active); } });
}
setupLanguagePicker('#language', '#language-options'); setupLanguagePicker('#filter-language', '#filter-language-options');
function filters() { const query = new URLSearchParams({limit: state.limit, offset: state.offset}); for (const [id, name] of [['filter-batch','batch_id'], ['filter-language','language'], ['filter-status','status'], ['filter-q','q'], ['filter-from','created_from'], ['filter-to','created_to']]) { const value = $(`#${id}`).value.trim(); if (value) query.set(name, value); } if (state.user?.is_admin && $('#filter-owner').value) query.set('owner_id', $('#filter-owner').value); return query; }
function updateSelection() { const selectable = state.jobs.filter(j => j.status === 'completed' || j.status === 'failed'); const checked = selectable.filter(j => state.selected.has(j.id)); $('#select-all').checked = !!selectable.length && checked.length === selectable.length; $('#select-all').indeterminate = !!checked.length && checked.length < selectable.length; $('#delete-selected').disabled = !state.selected.size; $('#download-selected').disabled = !state.selected.size; $('#selection-count').textContent = state.selected.size ? `已选 ${state.selected.size} 项` : '';  }
let copyMessageUntil = 0;
async function copyText(value) {
  if (navigator.clipboard && window.isSecureContext) {
    try { await navigator.clipboard.writeText(value); return; } catch (_) { /* Fall back when browser permissions deny access. */ }
  }
  const previous = document.activeElement;
  const input = document.createElement('textarea'); input.value = value; input.setAttribute('readonly', '');
  input.style.cssText = 'position:fixed;left:-9999px;top:0'; document.body.append(input);
  try { input.focus(); input.select(); if (!document.execCommand('copy')) throw new Error('copy failed'); }
  finally { input.remove(); if (previous && typeof previous.focus === 'function') previous.focus(); }
}
async function copyJobId(id) {
  copyMessageUntil = Date.now() + 5000;
  try { await copyText(id); $('#jobs-message').textContent = `已复制完整任务 ID：${id}`; }
  catch (_) { $('#jobs-message').textContent = `复制失败，请手动复制完整任务 ID：${id}`; }
}
function showJobError(job) {
  const dialog = $('#job-error-dialog');
  $('#job-error-file').textContent = job.audio_name || '';
  const details = $('#job-error-details');
  const message = job.error_display || job.error || '暂无错误信息。';
  if (job.error_code && job.error_code !== 'unknown' && job.error_display) {
    const end = message.indexOf('。');
    const lineEnd = message.indexOf('\n');
    const split = end >= 0 ? end + 1 : lineEnd >= 0 ? lineEnd : message.length;
    details.replaceChildren(node('strong', message.slice(0, split), 'job-error-conclusion'), node('span', message.slice(split)));
  } else {
    details.textContent = job.error || job.error_display || '暂无错误信息。';
  }
  dialog.showModal();
}
function jobDuration(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds)) || Number(seconds) < 0) return '—';
  const minutes = Math.round(Number(seconds) / 60);
  return minutes === 0 && Number(seconds) > 0 ? '不足 1 分钟' : `${minutes} 分钟`;
}
function renderJob(job) {
  const row = node('tr'); const selection = node('td'); const check = node('input'); check.type = 'checkbox'; check.setAttribute('aria-label', `选择 ${job.audio_name}`); check.disabled = !['completed', 'failed'].includes(job.status); check.checked = state.selected.has(job.id); check.onchange = () => { if (check.checked) state.selected.set(job.id, job.status); else state.selected.delete(job.id); updateSelection(); }; selection.append(check); row.append(selection);
  const name = node('td', job.audio_name, 'file-name'); row.append(name, node('td', jobDuration(job.audio_duration_seconds), 'job-duration'), node('td', job.language)); if (state.user?.is_admin) row.append(node('td', job.owner_username || '—')); row.append(node('td', formatDate(job.created_at))); const idCell = node('td', undefined, 'job-id'); const idButton = action(job.id.slice(0, 8), () => copyJobId(job.id), 'job-id-button'); idButton.title = `点击复制完整任务 ID：${job.id}`; idButton.setAttribute('aria-label', `复制完整任务 ID ${job.id}`); idCell.append(idButton); row.append(idCell);
  const status = node('td'); status.append(node('span', statusNames[job.status] || job.status, `status ${job.status}`)); row.append(status);
  const cell = node('td'); const actions = node('div', undefined, 'row-actions'); actions.append(action('查看', () => showReview(job))); for (const format of job.artifacts || []) { const a = node('a', format.toUpperCase()); a.href = artifactDownloadUrl(job.id, format); actions.append(a); } if (job.status === 'failed') { const errorButton = action('错误原因', () => showJobError(job)); errorButton.setAttribute('aria-haspopup', 'dialog'); errorButton.setAttribute('aria-controls', 'job-error-dialog'); errorButton.setAttribute('aria-label', `查看 ${job.audio_name} 的错误原因`); actions.append(errorButton, action('重试', () => retry(job.id))); } if (state.user?.is_admin && ['completed', 'failed'].includes(job.status)) actions.append(action('删除', () => removeJobs([job.id]), 'danger')); cell.append(actions); row.append(cell); return row;
}
async function refresh() { if (!state.user) return; try { const data = await request(`/v1/jobs?${filters()}`); state.jobs = data.jobs; state.total = data.total; if (!data.jobs.length && state.offset > 0) { state.offset = Math.max(0, state.offset - state.limit); return refresh(); } $('#jobs').replaceChildren(...data.jobs.map(renderJob)); if (!data.jobs.length) { const row = node('tr'); const cell = node('td', '暂无任务', 'empty'); cell.colSpan = state.user?.is_admin ? 9 : 8; row.append(cell); $('#jobs').append(row); } $('#page-info').textContent = `${data.total ? state.offset + 1 : 0}–${state.offset + data.jobs.length} / ${data.total}`; $('#prev-page').disabled = state.offset === 0; $('#next-page').disabled = state.offset + data.jobs.length >= data.total; updateSelection(); if (Date.now() >= copyMessageUntil) $('#jobs-message').textContent = ''; } catch (e) { $('#jobs-message').textContent = e.message; } }
$('#select-all').onchange = (e) => { for (const job of state.jobs) if (['completed', 'failed'].includes(job.status)) { if (e.target.checked) state.selected.set(job.id, job.status); else state.selected.delete(job.id); } refresh(); };
async function removeJobs(ids) { if (!state.user?.is_admin) return; if (!confirm(`确定删除 ${ids.length} 个任务及其输入和结果文件？`)) return; let failed = 0; for (const id of ids) { try { await request(`/v1/jobs/${id}`, {method:'DELETE'}); state.selected.delete(id); } catch (_) { failed++; } } await refresh(); if (failed) $('#jobs-message').textContent = `${failed} 个任务删除失败。`; }
async function retry(id) { try { await request(`/v1/jobs/${id}/retry`, {method:'POST'}); state.selected.delete(id); refresh(); } catch (e) { $('#jobs-message').textContent = e.message; } }
$('#delete-selected').onclick = () => removeJobs([...state.selected.keys()]);
function selectedDownloadFormats() { return [...document.querySelectorAll('input[name="bulk-format"]:checked')].map(input => input.value); }
const CSV_EXPORT_VERSION = 'audition-v2';
function artifactDownloadUrl(id, format) { return `/v1/jobs/${encodeURIComponent(id)}/artifacts/${format}${format === 'csv' ? `?format_version=${CSV_EXPORT_VERSION}` : ''}`; }
function updateDownloadFormatSummary() { const formats = selectedDownloadFormats(); const labels = {csv:'CSV', textgrid:'TextGrid', txt:'TXT'}; $('#bulk-format-summary').textContent = `下载格式：${formats.length ? formats.map(format => labels[format]).join('、') : '未选择'}`; }
for (const input of document.querySelectorAll('input[name="bulk-format"]')) input.addEventListener('change', updateDownloadFormatSummary);
$('#download-selected').onclick = () => {
  const ids = [...state.selected].filter(([, status]) => status === 'completed').map(([id]) => id);
  if (!ids.length) { $('#jobs-message').textContent = '请选择已完成的任务下载。'; return; }
  if (ids.length > 200) { $('#jobs-message').textContent = '每次最多下载 200 个任务。'; return; }
  const formats = selectedDownloadFormats();
  if (!formats.length) { $('#jobs-message').textContent = '请选择至少一种下载格式。'; $('#bulk-format-menu').open = true; return; }
  $('#jobs-message').textContent = ''; $('#bulk-format-menu').open = false;
  if (ids.length === 1 && formats.length === 1) { const a = document.createElement('a'); a.href = artifactDownloadUrl(ids[0], formats[0]); a.click(); return; }
  const query = new URLSearchParams({job_ids:ids.join(','), formats:formats.join(',')});
  if (formats.includes('csv')) query.set('format_version', CSV_EXPORT_VERSION);
  fetch(`/v1/jobs/bulk-artifacts.zip?${query}`).then(async response => { if (!response.ok) { let data = {}; try { data = await response.json(); } catch (_) {} throw new Error(data.detail || `下载失败 (${response.status})`); } return response.blob(); }).then(blob => { const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = 'alignment-results.zip'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }).catch(error => { $('#jobs-message').textContent = error.message; });
};
$('#refresh').onclick = async () => { await refresh(); if (state.user?.is_admin) await loadFilterUsers(state.user.id); }; $('#prev-page').onclick = () => { state.offset = Math.max(0, state.offset - state.limit); refresh(); }; $('#next-page').onclick = () => { state.offset += state.limit; refresh(); };
let filterTimer; for (const id of ['filter-batch','filter-language','filter-status','filter-q','filter-from','filter-to','filter-owner']) $(`#${id}`).addEventListener('input', () => { clearTimeout(filterTimer); filterTimer = setTimeout(() => { state.offset = 0; state.selected.clear(); refresh(); }, 300); });
$('#filter-batch').addEventListener('change', () => { $('#download-batch').disabled = !$('#filter-batch').value; });
$('#clear-filters').onclick = () => { $('#download-batch').disabled = true; for (const id of ['filter-batch','filter-language','filter-status','filter-q','filter-from','filter-to','filter-owner']) $(`#${id}`).value = ''; state.offset = 0; state.selected.clear(); refresh(); };
const reviewAudio = $('#review-audio');
const waveform = new WaveformReview($('#waveform'), reviewAudio);
let reviewEpoch = 0, reviewSegments = [], reviewRows = [], activeRow = -1, playUntil = null, playTimer = null;
function clearPlayUntil() { playUntil = null; clearTimeout(playTimer); playTimer = null; }
function stopAtSegmentEnd() {
  clearTimeout(playTimer);
  if (playUntil === null || reviewAudio.paused) return;
  const remaining = playUntil - reviewAudio.currentTime;
  if (remaining <= 0) { reviewAudio.pause(); reviewAudio.currentTime = playUntil; clearPlayUntil(); }
  else playTimer = setTimeout(stopAtSegmentEnd, Math.max(10, remaining / (reviewAudio.playbackRate || 1) * 1000));
}
function updateReviewPlayback() {
  const next = WaveformMath.activeSegment(reviewSegments, reviewAudio.currentTime);
  if (next !== activeRow) { if (reviewRows[activeRow]) reviewRows[activeRow].classList.remove('active'); activeRow = next; if (reviewRows[next]) reviewRows[next].classList.add('active'); }
  waveform.showTime(reviewAudio.currentTime); waveform.draw(); stopAtSegmentEnd();
}
for (const event of ['timeupdate', 'seeked', 'play', 'pause', 'ratechange']) reviewAudio.addEventListener(event, updateReviewPlayback);
waveform.onSeek = time => { clearPlayUntil(); reviewAudio.currentTime = time; waveform.draw(); };
function closeReview() { reviewEpoch++; clearPlayUntil(); reviewAudio.pause(); reviewAudio.removeAttribute('src'); reviewAudio.load(); $('#review').hidden = true; waveform.reset(); }
async function showReview(job) {
  const epoch = ++reviewEpoch, current = () => epoch === reviewEpoch;
  clearPlayUntil(); reviewAudio.pause(); reviewSegments = []; reviewRows = []; activeRow = -1;
  $('#review').hidden = false; $('#review-title').textContent = `任务详情：${job.audio_name}`;
  reviewAudio.src = `/v1/jobs/${job.id}/input/audio`; waveform.reset();
  $('#wave-message').textContent = '正在加载波形…'; $('#review-input').textContent = '正在加载…';
  const list = $('#segment-list'); list.replaceChildren();
  function listMessage(message) { const row = node('tr'), cell = node('td', message, 'empty'); cell.colSpan = 4; row.append(cell); list.replaceChildren(row); }
  listMessage(job.status === 'completed' ? '正在加载…' : '任务尚未完成');
  $('#review').scrollIntoView({behavior:'smooth',block:'start'});
  fetch(`/v1/jobs/${job.id}/input/text`).then(response => { if (!response.ok) throw new Error('无法加载输入文本'); return response.text(); }).then(text => { if (current()) $('#review-input').textContent = text; }).catch(error => { if (current()) $('#review-input').textContent = error.message; });
  request(`/v1/jobs/${job.id}/waveform?points=48000`).then(data => { if (!current()) return; waveform.setData(data); $('#wave-message').textContent = data.peaks?.length ? '' : '暂无波形数据'; }).catch(error => { if (current()) $('#wave-message').textContent = `波形加载失败：${error.message}`; });
  if (job.status !== 'completed') return;
  try {
    const data = await request(`/v1/jobs/${job.id}/sentences`); if (!current()) return;
    reviewSegments = Array.isArray(data) ? data : data.sentences; waveform.setSegments(reviewSegments);
    reviewRows = reviewSegments.map(segment => { const row = node('tr'); row.tabIndex = 0; row.setAttribute('role', 'button'); row.setAttribute('aria-label', `播放第 ${segment.id} 句`); row.append(node('td', String(segment.id)), node('td', formatTime(segment.start)), node('td', formatTime(segment.end)), node('td', segment.text));
      const play = () => { clearPlayUntil(); reviewAudio.currentTime = Number(segment.start); playUntil = Number(segment.end); reviewAudio.play().then(stopAtSegmentEnd).catch(() => { clearPlayUntil(); }); };
      row.onclick = play; row.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); play(); } }; return row; });
    list.replaceChildren(...reviewRows); if (!reviewRows.length) listMessage('暂无句子'); updateReviewPlayback();
  } catch(error) { if (current()) listMessage(error.message); }
}
$('#close-review').onclick = closeReview;
// The batch is registered before files are uploaded individually, so the upload
// does not buffer several large recordings in the browser or in the server.
let batchListVersion = 0, batchList = [], pendingBatch = null;
const audioExtensions = new Set(['wav', 'mp3', 'flac', 'm4a', 'ogg', 'opus', 'aac', 'webm']);
const batchFilesHint = '在同一目录中全选音频和 UTF-8 文本；按相同文件名配对，例如 sample.wav 和 sample.txt，每行一句。';
function splitBatchFiles(files) {
  const audio = [], text = [], other = [];
  for (const file of files) {
    const ext = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : '';
    if (audioExtensions.has(ext)) audio.push(file);
    else if (ext === 'txt') text.push(file);
    else other.push(file);
  }
  return {audio, text, other};
}
$('#batch-files').onchange = () => {
  const {audio, text, other} = splitBatchFiles($('#batch-files').files);
  $('#batch-files-count').textContent = `已选择 ${audio.length} 个音频、${text.length} 个文本${other.length ? `，${other.length} 个其他文件将被忽略` : ''}；按相同文件名配对。`;
};
function uploadDialog(title, message, details, noticeOnly = false) {
  const dialog = $('#upload-dialog'); dialog.returnValue = ''; $('#upload-dialog-cancel').hidden = noticeOnly; $('#upload-dialog-continue').textContent = noticeOnly ? '知道了' : '继续提交'; $('#upload-dialog-title').textContent = title; $('#upload-dialog-message').textContent = message; $('#upload-dialog-details').textContent = details;
  return new Promise(resolve => { dialog.addEventListener('close', () => resolve(dialog.returnValue === 'continue'), {once:true}); dialog.showModal(); });
}
function describePairing(result) {
  const lines = [];
  if (result.unmatched_audio?.length) lines.push('缺少同名文本的音频：', ...result.unmatched_audio.map(name => `  ${name}`), '');
  if (result.unmatched_text?.length) lines.push('缺少同名音频的文本：', ...result.unmatched_text.map(name => `  ${name}`), '');
  for (const duplicate of result.duplicates || []) lines.push(`文件名重复，无法唯一配对：${duplicate.stem}`, ...(duplicate.audio || []).map(name => `  音频：${name}`), ...(duplicate.text || []).map(name => `  文本：${name}`), '');
  return lines.join('\n').trim();
}
async function readTextFile(file) { try { return new TextDecoder('utf-8', {fatal:true}).decode(await file.arrayBuffer()); } catch (_) { throw new Error(`文本文件 ${file.name} 无法读取或不是 UTF-8 编码`); } }
function readAudioDuration(file) {
  return new Promise(resolve => {
    let url, timer, audio;
    const finish = value => { clearTimeout(timer); if (audio) { audio.onloadedmetadata = null; audio.onerror = null; audio.removeAttribute('src'); } if (url) URL.revokeObjectURL(url); resolve(Number.isFinite(value) && value > 0 ? value : null); };
    try {
      audio = new Audio(); url = URL.createObjectURL(file); audio.preload = 'metadata';
      audio.onloadedmetadata = () => finish(audio.duration); audio.onerror = () => finish(null);
      timer = setTimeout(() => finish(null), 10000); audio.src = url;
    } catch (_) { finish(null); }
  });
}
function reviewPrecheckWarnings(warnings) {
  const dialog = $('#precheck-dialog'), list = $('#precheck-items'), checks = [];
  list.replaceChildren();
  for (const {pair, result} of warnings) {
    const label = node('label', undefined, 'precheck-item'), checkbox = node('input');
    checkbox.type = 'checkbox'; checkbox.checked = true;
    const text = node('span', undefined, 'precheck-item-text');
    text.append(node('strong', pair.audio), node('span', result.message));
    label.append(checkbox, text); list.append(label); checks.push({name:pair.audio, checkbox});
  }
  dialog.returnValue = '';
  return new Promise(resolve => { dialog.addEventListener('close', () => resolve(dialog.returnValue === 'continue' ? new Set(checks.filter(item => !item.checkbox.checked).map(item => item.name)) : null), {once:true}); dialog.showModal(); });
}
function sendJob(body, index = 0, count = 1) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest(); xhr.open('POST', '/v1/jobs'); if (state.csrf) xhr.setRequestHeader('X-CSRF-Token', state.csrf);
    xhr.upload.onprogress = e => { if (e.lengthComputable) { const pct = Math.round(e.loaded / e.total * 100); $('#upload-progress-bar').style.width = `${Math.round((index + pct / 100) / count * 100)}%`; $('#upload-progress-text').textContent = count > 1 ? `上传第 ${index + 1} / ${count} 个文件，${pct}%` : `上传中 ${pct}%`; } };
    xhr.onload = () => { let data = {}; try { data = JSON.parse(xhr.responseText); } catch (_) {} if (xhr.status >= 200 && xhr.status < 300) resolve(data); else { if (xhr.status === 401) showAccount(null); reject(new Error(typeof data.detail === 'string' ? data.detail : `提交失败 (${xhr.status})`)); } };
    xhr.onerror = () => reject(new Error('上传失败，请检查网络')); xhr.send(body);
  });
}
async function loadBatches(selected) {
  if (!state.user) return; const version = ++batchListVersion, userId = state.user.id;
  try {
    const data = await request('/v1/batches'); if (version !== batchListVersion || state.user?.id !== userId) return;
    batchList = data.batches; const select = $('#filter-batch'), previous = selected === undefined ? select.value : selected;
    const options = [new Option('全部批次', '')];
    for (const batch of data.batches) options.push(new Option(`${batch.id.slice(0, 8)} · ${formatDate(batch.created_at)} · ${batch.language}${state.user?.is_admin && batch.owner_username ? ` · ${batch.owner_username}` : ''} · ${batch.completed}/${batch.total} 完成`, batch.id));
    select.replaceChildren(...options); select.value = options.some(option => option.value === previous) ? previous : '';
    $('#download-batch').disabled = !select.value;
  } catch (error) { if (version === batchListVersion && state.user?.id === userId) $('#jobs-message').textContent = `加载批次失败：${error.message}`; }
}
$('#download-batch').onclick = () => {
  const id = $('#filter-batch').value, formats = selectedDownloadFormats(); if (!id) return;
  const batch = batchList.find(item => item.id === id);
  if (batch && !batch.completed) { $('#jobs-message').textContent = '该批次暂无已完成的任务。'; return; }
  if (batch && batch.completed < batch.total && !confirm(`该批次共 ${batch.total} 组，已完成 ${batch.completed} 组。下载包含目前已完成的结果，是否继续？`)) return;
  if (!formats.length) { $('#jobs-message').textContent = '请选择至少一种下载格式。'; $('#bulk-format-menu').open = true; return; }
  const query = new URLSearchParams({formats:formats.join(',')}); if (formats.includes('csv')) query.set('format_version', CSV_EXPORT_VERSION);
  $('#bulk-format-menu').open = false; $('#jobs-message').textContent = '';
  fetch(`/v1/batches/${encodeURIComponent(id)}/artifacts.zip?${query}`).then(async response => { if (!response.ok) { let data = {}; try { data = await response.json(); } catch (_) {} throw new Error(data.detail || `下载失败 (${response.status})`); } return response.blob(); }).then(blob => { const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = `alignment-batch-${id.slice(0, 8)}.zip`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }).catch(error => { $('#jobs-message').textContent = error.message; });
};
$('#refresh').addEventListener('click', () => loadBatches());
$('#submit-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget, language = $('#language').value.trim();
  const {audio:audioFiles, text:textFiles, other:otherFiles} = splitBatchFiles($('#batch-files').files);
  if (!language) { $('#submit-message').textContent = '请选择或输入语种'; return; }
  if (pendingBatch) { $('#submit-message').textContent = '上次批次有文件上传失败，请重试或放弃后再提交新批次。'; return; }
  if (!audioFiles.length && !textFiles.length && !otherFiles.length) { $('#submit-message').textContent = '请选择音频和文本文件'; return; }
  $('#submit').disabled = true; for (const id of ['language','batch-files']) $(`#${id}`).disabled = true; $('#submit-message').textContent = '正在检查…';
  try {
    const names = {audio_names:audioFiles.map(file => file.name), text_names:textFiles.map(file => file.name)};
    const checked = await request('/v1/batches/check', json(names)); const pairingDetails = describePairing(checked), details = [pairingDetails, otherFiles.length ? `不支持的文件，不会上传：\n${otherFiles.map(file => `  ${file.name}`).join('\n')}` : ''].filter(Boolean).join('\n\n'), initialCount = checked.pairs.length;
    if (!initialCount) { if (details) await uploadDialog('没有可配对的文件', '请检查文件名后重新选择。', details, true); $('#submit-message').textContent = '没有可配对的文件'; return; }
    if (details && !await uploadDialog('部分文件未能配对', `将检查并提交 ${initialCount} 组匹配文件；以下文件不会上传。`, details)) { $('#submit-message').textContent = '已取消提交'; return; }
    const audioByName = new Map(audioFiles.map(file => [file.name, file])), textByName = new Map(textFiles.map(file => [file.name, file]));
    const validPairs = [], invalid = [], warnings = [], lengthWarnings = [];
    for (const pair of checked.pairs) {
      $('#submit-message').textContent = `正在检查文本 ${validPairs.length + invalid.length + 1} / ${initialCount}…`;
      const file = textByName.get(pair.text); let content;
      try {
        if (file.size > 2 * 1024 * 1024) throw new Error('文本文件超过 2 MB');
        content = await readTextFile(file);
        if (!content.trim() || content.includes('\0')) throw new Error('文本为空或包含无效字符');
      } catch (error) { invalid.push(`${pair.text}：${error.message}`); continue; }
      const result = await request('/v1/language-check', json({language, text:content}));
      if (result.status === 'mismatch') warnings.push(`${pair.text}：${result.message}`);
      const duration = await readAudioDuration(audioByName.get(pair.audio));
      let lengthCheck;
      try { lengthCheck = await request('/v1/alignment-precheck', json({language, text:content, duration_seconds:duration})); }
      catch (_) { lengthCheck = {status:'unknown', message:'暂时无法检查音频和文本的长度，请自行核对。'}; }
      if (!lengthCheck || !['ok', 'warning', 'unknown'].includes(lengthCheck.status)) lengthCheck = {status:'unknown', message:'暂时无法检查音频和文本的长度，请自行核对。'};
      if (lengthCheck.status !== 'ok') lengthWarnings.push({pair, result:lengthCheck});
      validPairs.push(pair);
    }
    let count = validPairs.length;
    if (invalid.length && !count) { await uploadDialog('文本文件无法提交', '以下文件存在问题，未创建任务。', invalid.join('\n'), true); $('#submit-message').textContent = '没有可提交的文件'; return; }
    if (invalid.length && !await uploadDialog('部分文本文件无法提交', `以下文件不会上传；可继续提交其余 ${count} 组文件。`, invalid.join('\n'))) { $('#submit-message').textContent = '已取消提交'; return; }
    if (warnings.length && !await uploadDialog('语种可能不一致', '以下文本与所选语种可能不一致，请确认后再提交。', warnings.join('\n'))) { $('#submit-message').textContent = '已取消提交'; return; }
    if (lengthWarnings.length) {
      const skipped = await reviewPrecheckWarnings(lengthWarnings);
      if (skipped === null) { $('#submit-message').textContent = '已取消提交'; return; }
      for (let i = validPairs.length - 1; i >= 0; i--) if (skipped.has(validPairs[i].audio)) validPairs.splice(i, 1);
      count = validPairs.length;
      if (!count) { $('#submit-message').textContent = '没有选择需要对齐的文件'; return; }
    }
    const manifest = {audio_names:validPairs.map(pair => pair.audio), text_names:validPairs.map(pair => pair.text), language};
    const created = await request('/v1/batches', json(manifest)); const errors = [], failedPairs = [];
    $('#upload-progress').hidden = false; $('#upload-progress-bar').style.width = '0%';
    for (let i = 0; i < validPairs.length; i++) {
      const pair = validPairs[i], body = new FormData(); body.append('language', language); body.append('batch_id', created.batch_id); body.append('audio', audioByName.get(pair.audio)); body.append('text_file', textByName.get(pair.text));
      try { await sendJob(body, i, count); } catch (error) { errors.push(`${pair.audio}：${error.message}`); failedPairs.push({pair, audio:audioByName.get(pair.audio), text:textByName.get(pair.text)}); }
    }
    for (const id of ['filter-language','filter-status','filter-q','filter-from','filter-to','filter-owner']) $(`#${id}`).value = '';
    await loadBatches(created.batch_id); state.offset = 0; state.selected.clear(); await refresh();
    $('#submit-message').textContent = `批次已提交 ${count - errors.length} / ${count} 组${errors.length ? `，${errors.length} 组上传失败` : ''}。`;
    if (errors.length) { pendingBatch = {id:created.batch_id, ownerId:state.user?.id, language, items:failedPairs}; $('#batch-retry-actions').hidden = false; await uploadDialog('部分文件上传失败', '已提交的任务会继续处理；可使用“重试失败上传”继续提交至同一批次。', errors.join('\n'), true); }
    else { form.reset(); $('#batch-files-count').textContent = batchFilesHint; }
  } catch (error) { $('#submit-message').textContent = error.message || '提交失败，请检查网络'; }
  finally { $('#submit').disabled = false; for (const id of ['language','batch-files']) $(`#${id}`).disabled = false; $('#upload-progress').hidden = true; }
});
$('#batch-dismiss').onclick = () => { pendingBatch = null; $('#batch-retry-actions').hidden = true; $('#submit-message').textContent = '已放弃重试；已提交的任务仍会继续处理。'; };
$('#batch-retry').onclick = async () => {
  if (!pendingBatch) return;
  if (pendingBatch.ownerId !== state.user?.id) { pendingBatch = null; $('#batch-retry-actions').hidden = true; $('#submit-message').textContent = '用户已切换，请重新选择文件。'; return; }
  const current = pendingBatch, failed = [], errors = []; $('#batch-retry').disabled = true; $('#batch-dismiss').disabled = true; $('#submit').disabled = true; $('#language').disabled = true; $('#batch-files').disabled = true; $('#upload-progress').hidden = false;
  try {
    for (let i = 0; i < current.items.length; i++) {
      const item = current.items[i], body = new FormData(); body.append('language', current.language); body.append('batch_id', current.id); body.append('audio', item.audio); body.append('text_file', item.text);
      try { await sendJob(body, i, current.items.length); } catch (error) { failed.push(item); errors.push(`${item.pair.audio}：${error.message}`); }
    }
    current.items = failed; await loadBatches(current.id); state.offset = 0; await refresh();
    if (failed.length) { $('#submit-message').textContent = `仍有 ${failed.length} 组上传失败，可继续重试。`; await uploadDialog('部分文件上传失败', '可继续重试，已提交的任务会继续处理。', errors.join('\n'), true); }
    else { pendingBatch = null; $('#batch-retry-actions').hidden = true; $('#submit-message').textContent = '失败的文件已全部提交。'; $('#batch-files').value = ''; $('#batch-files-count').textContent = batchFilesHint; }
  } finally { $('#batch-retry').disabled = false; $('#batch-dismiss').disabled = false; $('#submit').disabled = false; $('#language').disabled = false; $('#batch-files').disabled = false; $('#upload-progress').hidden = true; }
};
health(); checkSession().then(() => loadBatches()); setInterval(() => { health(); refresh(); }, 5000); setInterval(() => loadBatches(), 15000);
