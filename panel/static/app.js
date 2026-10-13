'use strict';
const $ = id => document.getElementById(id);
const views = ['dashboard', 'console', 'users', 'maintenance'];
const busyStages = new Set(['building','installing','checking','updating','starting','configuring','repairing','validating','restoring']);
let csrf = '', setupRequired = false, status = null, view = 'dashboard', dismissedBuild = null;
let publicAddress = null, modes = [], users = [], filter = 'all', settingsLoaded = false, hasGslt = false;
let formDirty = false, refreshing = false, wasBusy = false, lastMetrics = 0, confirmResolve = null;
function show(id, visible) { $(id).classList.toggle('hidden', !visible); }
function notify(message) { $('notice').textContent = message || ''; show('notice', Boolean(message)); }
function activeView() { views.forEach(id => show(id, Boolean(csrf) && view === id)); }
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function actionButton(label, action, disabled = false, className = 'secondary compact') {
  const button = node('button', label, className);
  button.type = 'button'; button.disabled = disabled;
  button.addEventListener('click', () => action().catch(error => notify(error.message)));
  return button;
}
async function api(path, data) {
  const options = {credentials: 'same-origin', headers: {}};
  if (data !== undefined) {
    options.method = 'POST'; options.headers = {'Content-Type':'application/json', 'X-CSRF-Token':csrf};
    options.body = JSON.stringify(data);
  }
  const response = await fetch('/api/' + path, options);
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) { csrf = ''; activeView(); show('auth', true); show('logout', false); }
    throw new Error(result.error || 'Request failed');
  }
  return result;
}
async function loadSettings() {
  const result = await api('settings');
  hasGslt = Boolean(result.has_gslt);
  if (result.settings) {
    for (const [name, value] of Object.entries(result.settings)) {
      const field = $('server-form').elements.namedItem(name);
      if (field) field.value = value;
    }
  }
  $('server-form').elements.gslt.required = !hasGslt;
  show('credentials-card', !hasGslt);
  settingsLoaded = true; formDirty = false; modeNote();
}
async function session() {
  const result = await api('session');
  csrf = result.csrf || ''; setupRequired = result.setup_required;
  show('auth', !result.authenticated); show('logout', result.authenticated); activeView();
  $('auth-title').textContent = setupRequired ? 'Step 1: Create your panel account' : 'Welcome back';
  $('auth-copy').textContent = setupRequired ? 'Choose your first panel username and password. Next, configure Steam and your server.' : 'Sign in to manage your CS2 server.';
  $('auth-submit').textContent = setupRequired ? 'Create administrator' : 'Sign in';
  show('token-field', setupRequired); $('auth-form').elements.setup_token.required = setupRequired;
  $('auth-form').elements.password.autocomplete = setupRequired ? 'new-password' : 'current-password';
  if (result.authenticated) {
    settingsLoaded = false;
    await loadSettings(); modes = (await api('modes')).modes;
    await refresh(); addressLookup().catch(error => notify(error.message));
    try {
      const info = await api('preflight');
      $('preflight').textContent = info.supported ? `Docker connected · ${info.architecture} · ${info.memory_gb} GiB assigned` : 'Use Linux containers on an x86-64 Docker engine.';
    } catch (error) { $('preflight').textContent = error.message; }
  }
}
function modeNote() {
  const selected = $('server-form').elements.game_mode.value;
  $('mode-note').textContent = selected === 'retakes'
    ? 'Retakes supports up to 10 active players; extra server slots are available for its queue and spectators.'
    : selected === 'matchzy' ? 'MatchZy manages your matches and practice tools. This preset does not connect to the FACEIT platform.'
      : 'Official Deathmatch runs without MatchZy or Retakes. The shared admin plugin remains active.';
}
async function addressLookup(force = false) {
  const result = await api(force ? 'address/refresh' : 'address', force ? {} : undefined);
  publicAddress = result.address;
  $('public-address').value = publicAddress || '';
  $('public-address').placeholder = result.error ? 'Public IP unavailable' : 'Detecting public IP…';
  $('address').textContent = publicAddress || 'Public IP unavailable';
  $('address-help').textContent = result.error || 'Share this address. Forward port 27015/UDP on your router.';
  $('copy-address').disabled = !publicAddress;
}
function render() {
  if (!status) return;
  const {job, config, server} = status, busy = busyStages.has(job.stage), running = Boolean(server?.running);
  const state = busy ? job.stage : job.stage === 'failed' ? 'failed' : running ? (server.health === 'healthy' ? 'ready' : server.health) : job.stage === 'ready' ? 'stopped' : job.stage;
  $('badge').textContent = !job.installed && !busy ? 'Not installed' : state.replaceAll('_', ' ');
  $('badge').className = 'badge ' + (state === 'ready' ? 'ready' : job.stage === 'failed' ? 'failed' : '');
  $('map-label').textContent = config?.map || 'de_dust2';
  $('mode-label').textContent = modes.find(mode => mode.id === config?.game_mode)?.label || 'FaceIt (MatchZy)';
  $('start').disabled = !job.installed || busy || running;
  $('restart').disabled = !job.installed || busy || !running;
  $('stop').disabled = !job.installed || busy || !running;
  $('save-server').textContent = job.installed ? running ? 'Save & restart server' : 'Save settings' : 'Install & start server';
  $('settings-copy').textContent = job.installed ? 'Changes apply to the next launch. Saving restarts a running server.' : 'Step 2: Configure your server and provide its Steam login token.';
  $('install-copy').textContent = job.installed ? 'Settings and mode changes keep your game files. An empty Join Password opens the server.' : 'Check the server directory, verify and update existing files or download missing files, then start the selected mode.';
  show('installed-details', Boolean(job.installed));
  for (const input of $('server-form').elements) input.disabled = busy;
  $('copy-address').disabled = busy || !publicAddress;
  for (const id of ['backup', 'repair', 'validate']) $(id).disabled = busy || !job.installed;
  $('verify-install').disabled = busy || !config || !hasGslt;
  $('edit-token').disabled = busy;
  $('stage').textContent = job.stage.replaceAll('_', ' ').toUpperCase();
  const log = $('install-log'), bottom = log.scrollHeight - log.scrollTop - log.clientHeight < 50;
  log.textContent = status.logs.length ? status.logs.join('\n') : 'Ready when you are.';
  if (bottom) log.scrollTop = log.scrollHeight;
  $('health').textContent = running ? server.health : 'Stopped'; $('build').textContent = job.installed_build || '—';
  if (job.error || status.docker_error) notify(job.error || status.docker_error);
  if (job.stage === 'update_available' && dismissedBuild !== job.available_build && !$('update-dialog').open) {
    $('update-description').textContent = `Installed build: ${job.installed_build}. Available build: ${job.available_build}.`;
    $('update-dialog').showModal();
  }
  const actions = $('mode-actions'); actions.replaceChildren();
  const mode = modes.find(item => item.id === config?.game_mode);
  for (const action of mode?.actions || []) actions.append(actionButton(action.label, async () => {
    let args = '';
    if (action.confirm || action.arg_hint) {
      const answer = await confirmAction(action.label, action.description, action.arg_hint);
      if (answer === null) return; args = answer;
    }
    $('action-output').textContent = (await api('mode/action', {key:action.key, args})).output || 'Command sent.';
  }, busy || !running));
  show('no-mode-actions', !mode?.actions?.length);
}
function confirmAction(title, description, argumentHint) {
  if ($('confirm-dialog').open) return Promise.resolve(null);
  $('confirm-title').textContent = title; $('confirm-description').textContent = description;
  show('argument-field', Boolean(argumentHint)); $('action-argument').value = '';
  $('action-argument').placeholder = argumentHint || '';
  $('confirm-dialog').showModal();
  return new Promise(resolve => { confirmResolve = resolve; });
}
function finishConfirmation(value) {
  $('confirm-dialog').close(); const resolve = confirmResolve; confirmResolve = null;
  if (resolve) resolve(value);
}
$('cancel-action').addEventListener('click', () => finishConfirmation(null));
$('confirm-action').addEventListener('click', () => finishConfirmation($('action-argument').value.trim()));
$('confirm-dialog').addEventListener('cancel', event => { event.preventDefault(); finishConfirmation(null); });
async function userAction(user, action) {
  const label = {kick:'Kick', ban:'Ban', unban:'Unban', admin:'Grant game admin', remove_admin:'Remove game admin'}[action];
  const description = action === 'ban' ? `Permanently block ${user.name} from this server until you unban them.`
    : action === 'admin' ? `Give ${user.name} full game plugin permissions. This grants no access to the web panel.`
      : `${label}: ${user.name} (${user.steamid}).`;
  if (await confirmAction(label, description) === null) return;
  const result = await api('users/action', {steamid:user.steamid, action});
  notify(result.pending ? result.message : ''); await refresh();
}
function userButtons(user, online) {
  const cell = node('td'), box = node('div', undefined, 'actions row-actions');
  const disabled = !user.steamid || user.bot || busyStages.has(status?.job.stage);
  if (online) box.append(actionButton('Kick', () => userAction(user, 'kick'), disabled));
  box.append(actionButton(user.banned ? 'Unban' : 'Ban', () => userAction(user, user.banned ? 'unban' : 'ban'), disabled, 'danger compact'));
  box.append(actionButton(user.admin ? 'Remove admin' : 'Admin', () => userAction(user, user.admin ? 'remove_admin' : 'admin'), disabled || user.banned));
  cell.append(box); return cell;
}
function nameCell(user) {
  const cell = node('td'); cell.append(node('strong', user.name || 'Unknown player'));
  cell.append(node('small', user.bot ? 'BOT' : user.steamid || 'Awaiting Steam authorization', 'player-id'));
  return cell;
}
function renderPlayers(result) {
  const body = $('players-body'); body.replaceChildren();
  $('player-count').textContent = String(result.players.length);
  $('players-message').textContent = result.error || (status.server?.running ? 'No players connected.' : 'Start the server to see connected players.');
  show('players-message', !result.players.length); show('players-table', Boolean(result.players.length));
  for (const player of result.players) {
    const row = node('tr'); row.append(nameCell(player), node('td', ['Unassigned','Spectator','T','CT'][player.team] || '—'), node('td', player.ping === null ? '—' : `${player.ping} ms`), userButtons(player, true));
    body.append(row);
  }
}
function renderUsers() {
  const visible = users.filter(user => filter === 'all' || (filter === 'banned' ? user.banned : user.admin));
  const body = $('users-body'); body.replaceChildren();
  show('users-empty', !visible.length); show('users-table', Boolean(visible.length));
  $('users-empty').textContent = filter === 'all' ? 'No player history yet.' : 'No users in this list.';
  for (const user of visible) {
    const row = node('tr'); row.append(nameCell(user), node('td', user.last_seen ? new Date(user.last_seen * 1000).toLocaleString() : '—'), node('td', user.banned ? 'Banned' : user.admin ? 'Game admin' : 'Player'), userButtons(user, false));
    body.append(row);
  }
}
async function maintenanceView() {
  const backups = (await api('backups')).backups, container = $('backups-list'); container.replaceChildren();
  if (!backups.length) container.append(node('p', 'No saved backups yet.'));
  for (const backup of backups) {
    const row = node('div', undefined, 'backup-row');
    row.append(node('span', `${new Date(backup.created_at * 1000).toLocaleString()} · ${backup.reason}`));
    row.append(actionButton('Restore', async () => {
      if (await confirmAction('Restore configuration', 'Restore server settings, bans and admin permissions from this backup. A running server will restart.') === null) return;
      await api('restore', {id:backup.id}); formDirty = false; await refresh();
    }, busyStages.has(status?.job.stage)));
    container.append(row);
  }
  const audit = (await api('audit')).entries, log = $('audit-list'); log.replaceChildren();
  if (!audit.length) log.append(node('p', 'No recorded actions yet.'));
  for (const entry of audit) log.append(node('p', `${new Date(entry.at * 1000).toLocaleString()} · ${entry.action} ${entry.target} · ${entry.outcome}`, 'audit-row'));
}
async function refresh() {
  if (!csrf || refreshing) return;
  refreshing = true;
  try {
    status = await api('status');
    const busy = busyStages.has(status.job.stage);
    if (settingsLoaded && wasBusy && !busy && !formDirty) await loadSettings();
    wasBusy = busy; render();
    if (view === 'dashboard') {
      renderPlayers(await api('players'));
      if (Date.now() - lastMetrics > 7000) {
        const metrics = await api('metrics'); lastMetrics = Date.now();
        $('resources').textContent = metrics.memory_bytes === null ? '—' : `${metrics.cpu_percent ?? '—'}% / ${(metrics.memory_bytes / 2**30).toFixed(2)} GiB`;
      }
    }
    if (view === 'console') $('console-output').textContent = (await api('console')).output || 'No output yet.';
    if (view === 'users') { users = (await api('users')).users; renderUsers(); }
    if (view === 'maintenance') await maintenanceView();
  } catch (error) { notify(error.message); } finally { refreshing = false; }
}
$('auth-form').addEventListener('submit', async event => {
  event.preventDefault(); $('auth-submit').disabled = true;
  try {
    csrf = (await api(setupRequired ? 'setup' : 'login', Object.fromEntries(new FormData(event.target)))).csrf;
    event.target.reset(); notify(''); await session();
  } catch (error) { notify(error.message); } finally { $('auth-submit').disabled = false; }
});
$('server-form').addEventListener('input', () => { formDirty = true; modeNote(); });
$('server-form').addEventListener('change', () => { formDirty = true; modeNote(); });
$('server-form').addEventListener('submit', async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target)); data.port = 27015; data.network_mode = 'internet';
  if (!data.gslt && hasGslt) delete data.gslt;
  if (status.server?.running && await confirmAction('Apply server settings', 'The server will restart to apply these settings and your selected game mode.') === null) return;
  $('save-server').disabled = true; notify('');
  try {
    await api(status.job.installed ? 'configure' : 'install', data);
    $('server-form').elements.gslt.value = ''; formDirty = false; wasBusy = true; await refresh();
  } catch (error) { notify(error.message); $('save-server').disabled = false; }
});
for (const action of ['start', 'restart', 'stop']) $(action).addEventListener('click', async () => {
  $(action).disabled = true; if (action !== 'stop') dismissedBuild = null;
  notify('');
  try { await api(action, {}); await refresh(); } catch (error) { notify(error.message); $(action).disabled = false; }
});
$('cancel-update').addEventListener('click', () => { dismissedBuild = status.job.available_build; $('update-dialog').close(); });
$('update-dialog').addEventListener('cancel', () => { dismissedBuild = status.job.available_build; });
$('approve-update').addEventListener('click', async () => {
  const build = status.job.available_build; dismissedBuild = build; $('update-dialog').close(); notify('');
  try { await api('start', {approved_build:build}); await refresh(); } catch (error) { notify(error.message); }
});
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
  if (!csrf) return; view = button.dataset.view;
  document.querySelectorAll('[data-view]').forEach(item => item.classList.toggle('active', item === button));
  activeView(); refresh();
}));
document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
  filter = button.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach(item => item.classList.toggle('active', item === button)); renderUsers();
}));
$('command-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
  try { $('command-output').textContent = (await api('command', {command:$('command').value})).output || 'Command sent.'; $('command').value = ''; }
  catch (error) { notify(error.message); } finally { button.disabled = false; }
});
for (const id of ['refresh-console', 'refresh-players', 'refresh-users']) $(id).addEventListener('click', refresh);
$('refresh-address').addEventListener('click', () => addressLookup(true).catch(error => notify(error.message)));
$('copy-address').addEventListener('click', async () => {
  if (!publicAddress) return;
  try { await navigator.clipboard.writeText(publicAddress); $('copy-address').textContent = 'Copied'; setTimeout(() => { $('copy-address').textContent = 'Copy'; }, 2000); }
  catch { $('public-address').select(); notify('Copy the selected server address.'); }
});
$('logout').addEventListener('click', async () => {
  try { await api('logout', {}); csrf = ''; $('server-form').reset(); settingsLoaded = false; await session(); }
  catch (error) { notify(error.message); }
});
$('backup').addEventListener('click', async () => {
  try { await api('backup', {}); await refresh(); } catch (error) { notify(error.message); }
});
$('verify-install').addEventListener('click', async () => {
  if (await confirmAction('Verify & update server', 'Reuse the existing server directory, verify all Steam files and update to the latest build. The server will stop first and start after successful verification. Your panel account and saved settings are kept.') === null) return;
  try { await api('install', {}); wasBusy = true; await refresh(); } catch (error) { notify(error.message); }
});
for (const action of ['repair','validate']) $(action).addEventListener('click', async () => {
  if (await confirmAction(action === 'repair' ? 'Repair required plugins' : 'Validate game files', 'The server will stop for maintenance, then restart if it was running.') === null) return;
  try { await api(action, {}); await refresh(); } catch (error) { notify(error.message); }
});
$('edit-token').addEventListener('click', () => {
  view = 'dashboard'; activeView(); show('credentials-card', true);
  $('server-form').elements.gslt.focus(); $('credentials-card').scrollIntoView({behavior:'smooth', block:'center'});
});
session().catch(error => notify(error.message));
async function poll() { await refresh(); setTimeout(poll, 2500); }
setTimeout(poll, 2500);
setInterval(() => { if (csrf) addressLookup().catch(() => {}); }, 600000);
