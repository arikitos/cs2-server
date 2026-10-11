'use strict';
const $ = (id) => document.getElementById(id);
let csrf = '', setupRequired = false, status = null, view = 'dashboard', dismissedBuild = null;
const busyStages = new Set(['building','installing','checking','updating','starting']);
function show(id, visible) { $(id).classList.toggle('hidden', !visible); }
function notify(message) { $('notice').textContent = message; show('notice', Boolean(message)); }
async function api(path, data) {
  const options = {credentials:'same-origin', headers:{}};
  if (data !== undefined) { options.method = 'POST'; options.headers = {'Content-Type':'application/json','X-CSRF-Token':csrf}; options.body = JSON.stringify(data); }
  const response = await fetch('/api/' + path, options);
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) { csrf = ''; await session(); }
    throw new Error(result.error || 'Request failed');
  }
  return result;
}
async function session() {
  const result = await api('session');
  csrf = result.csrf || ''; setupRequired = result.setup_required;
  show('auth', !result.authenticated); show('dashboard', result.authenticated && view === 'dashboard'); show('console', result.authenticated && view === 'console'); show('logout', result.authenticated);
  $('auth-title').textContent = setupRequired ? 'Set up your control panel' : 'Welcome back';
  $('auth-copy').textContent = setupRequired ? 'Create the administrator account for this computer.' : 'Sign in to manage your CS2 server.';
  $('auth-submit').textContent = setupRequired ? 'Create administrator' : 'Sign in';
  show('token-field', setupRequired); $('token-field').querySelector('input').required = setupRequired;
  $('auth-form').elements.password.autocomplete = setupRequired ? 'new-password' : 'current-password';
  if (result.authenticated) {
    await refresh();
    try {
      const preflight = await api('preflight');
      $('preflight').textContent = preflight.supported ? `Docker connected · ${preflight.architecture} · ${preflight.memory_gb} GiB memory assigned` : 'Unsupported Docker engine: use Linux containers on an x86-64 machine.';
    } catch (error) { $('preflight').textContent = error.message; }
  }
}
function render() {
  if (!status) return;
  const {job, config, server} = status;
  const busy = busyStages.has(job.stage), running = server?.running || false;
  const state = busy ? job.stage : running ? (server.health === 'healthy' ? 'ready' : server.health) : job.stage === 'ready' ? 'stopped' : job.stage;
  $('server-name').firstChild.textContent = (config?.server_name || 'Your CS2 server') + ' ';
  $('badge').textContent = !job.installed && !busy ? 'Not installed' : state.replaceAll('_',' ');
  $('badge').className = 'badge ' + (state === 'ready' ? 'ready' : state === 'failed' ? 'failed' : '');
  $('address').textContent = '127.0.0.1:' + (config?.port || 27015);
  $('map-label').textContent = config?.map || 'de_dust2';
  $('start').disabled = !job.installed || busy || running;
  $('restart').disabled = !job.installed || busy || !running;
  $('stop').disabled = !job.installed || busy || !running;
  show('installer', !job.installed); show('installed-details', Boolean(job.installed));
  for (const input of $('install-form').elements) input.disabled = busy;
  $('stage').textContent = job.stage.replaceAll('_',' ').toUpperCase();
  const log = $('install-log'), bottom = log.scrollHeight - log.scrollTop - log.clientHeight < 50;
  log.textContent = status.logs.length ? status.logs.join('\n') : 'Ready when you are.';
  if (bottom) log.scrollTop = log.scrollHeight;
  $('health').textContent = running ? server.health : 'Stopped';
  $('build').textContent = job.installed_build || '—'; $('slots').textContent = (config?.max_players || 10) + ' slots';
  $('info-status').textContent = state; $('info-map').textContent = config?.map || '—'; $('info-network').textContent = config?.network_mode || '—';
  $('info-started').textContent = running && server.started_at ? new Date(server.started_at).toLocaleString() : '—';
  if (job.error || status.docker_error) notify(job.error || status.docker_error);
  if (job.stage === 'update_available' && dismissedBuild !== job.available_build && !$('update-dialog').open) {
    $('update-description').textContent = `Installed build: ${job.installed_build}. Available build: ${job.available_build}.`;
    $('update-dialog').showModal();
  }
}
async function refresh() {
  if (!csrf) return;
  try {
    status = await api('status'); render();
    if (view === 'console') $('console-output').textContent = (await api('console')).output || 'No server output yet.';
  } catch (error) { notify(error.message); }
}
$('auth-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const button = $('auth-submit'); button.disabled = true;
  try {
    const result = await api(setupRequired ? 'setup' : 'login', Object.fromEntries(new FormData(event.target)));
    csrf = result.csrf; event.target.reset(); notify(''); await session();
  } catch (error) { notify(error.message); } finally { button.disabled = false; }
});
$('install-form').elements.network_mode.addEventListener('change', (event) => {
  const internet = event.target.value === 'internet'; show('gslt-field', internet); $('install-form').elements.gslt.required = internet;
  if (!internet) $('install-form').elements.gslt.value = '';
});
$('install-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  notify('');
  $('install').disabled = true;
  try { await api('install', data); $('install-form').elements.gslt.value = ''; $('install-form').elements.join_password.value = ''; await refresh(); }
  catch (error) { notify(error.message); $('install').disabled = false; }
});
for (const action of ['start','restart','stop']) $(action).addEventListener('click', async () => {
  $(action).disabled = true; if (action !== 'stop') dismissedBuild = null;
  notify('');
  try { await api(action, {}); await refresh(); } catch (error) { notify(error.message); }
});
$('cancel-update').addEventListener('click', () => { dismissedBuild = status.job.available_build; $('update-dialog').close(); });
$('update-dialog').addEventListener('cancel', () => { dismissedBuild = status.job.available_build; });
$('approve-update').addEventListener('click', async () => {
  const build = status.job.available_build; dismissedBuild = build; $('update-dialog').close();
  notify('');
  try { await api('start', {approved_build:build}); await refresh(); } catch (error) { notify(error.message); }
});
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
  if (!csrf) return; view = button.dataset.view;
  document.querySelectorAll('[data-view]').forEach(item => item.classList.toggle('active', item === button));
  show('dashboard', view === 'dashboard'); show('console', view === 'console'); refresh();
}));
$('command-form').addEventListener('submit', async (event) => {
  event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
  try { $('command-output').textContent = (await api('command', {command:$('command').value})).output || 'Command sent.'; $('command').value = ''; await refresh(); }
  catch (error) { notify(error.message); } finally { button.disabled = false; }
});
$('refresh-console').addEventListener('click', refresh);
$('logout').addEventListener('click', async () => { try { await api('logout', {}); csrf = ''; await session(); } catch (error) { notify(error.message); } });
$('copy-connect').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(`connect 127.0.0.1:${status.config.port}`); $('copy-connect').textContent = 'Copied'; setTimeout(() => $('copy-connect').textContent = 'Copy connect command', 2000); }
  catch { notify(`Connect in CS2: connect 127.0.0.1:${status.config.port}`); }
});
session().catch(error => notify(error.message));
setInterval(refresh, 2500);
