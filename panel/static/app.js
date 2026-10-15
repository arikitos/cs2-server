"use strict";

const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const icon = (name) =>
  `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const names = {
  dashboard: "Dashboard",
  console: "Console",
  players: "Players",
  modes: "Game modes",
  settings: "Server settings",
  maintenance: "Maintenance",
  activity: "Activity log",
};
const mapNames = {
  de_dust2: "Dust II",
  de_mirage: "Mirage",
  de_inferno: "Inferno",
  de_nuke: "Nuke",
  de_ancient: "Ancient",
  de_anubis: "Anubis",
  de_overpass: "Overpass",
  de_train: "Train",
  de_vertigo: "Vertigo",
};
const mapLabel = (map) =>
  mapNames[map] || String(map || "").replace(/^de_/, "");
const timeLabel = (iso) =>
  iso
    ? new Date(iso).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "-";
const dateLabel = (iso) => (iso ? new Date(iso).toLocaleString() : "-");
let state = null;
let selectedMode = null;
let draft = {};
let savedDraft = {};
let players = [];
let page = "dashboard";
let busy = false;
let refreshing = false;
let connected = false;
let liveMap = null;
let selectedJob = null;
let lastHealth = 0;
let lastActivity = 0;
const cpuHistory = [];
let commandCatalog = [];

async function api(path, { method = "GET", body, ...options } = {}) {
  const mutation = method !== "GET";
  const response = await fetch("/api/v3/" + path, {
    method,
    cache: "no-store",
    credentials: "same-origin",
    signal: AbortSignal.timeout(45000),
    headers: {
      "X-CS2-Panel": "1",
      ...(mutation ? { "Content-Type": "application/json" } : {}),
    },
    ...(mutation ? { body: JSON.stringify(body || {}) } : {}),
    ...options,
  });
  const type = response.headers.get("Content-Type") || "";
  if (!type.includes("application/json")) {
    throw new Error(
      response.status === 401
        ? "Your session needs authentication. Reload the panel to sign in."
        : `The server returned an unexpected response (${response.status}).`,
    );
  }
  const result = await response.json();
  if (!response.ok || result.ok === false)
    throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}

function message(text, type = "info") {
  $("message").textContent = text;
  $("message").dataset.type = type;
  $("message").hidden = !text;
}

function dirty() {
  return JSON.stringify(draft) !== JSON.stringify(savedDraft);
}
function selectedMeta() {
  return state?.mode_meta?.[selectedMode] || {};
}
function activeMode() {
  return state?.active?.mode;
}
function activeMeta() {
  return state?.mode_meta?.[activeMode()] || {};
}
function endpoint() {
  return state ? `${state.endpoint.ip}:${state.endpoint.port}` : "";
}
function formatFor(mode, settings) {
  return (state?.mode_meta?.[mode]?.formats || []).find(
    (f) => f.key === settings?.format,
  );
}

async function confirmAction(title, detail, accept = "Continue") {
  const dialog = $("confirmDialog");
  $("confirmTitle").textContent = title;
  $("confirmDetail").textContent = detail;
  $("confirmAccept").textContent = accept;
  dialog.returnValue = "cancel";
  dialog.showModal();
  return new Promise((resolve) =>
    dialog.addEventListener(
      "close",
      () => resolve(dialog.returnValue === "confirm"),
      { once: true },
    ),
  );
}

function lockButtons() {
  const ready = connected && !busy && !state?.maintenance_active;
  const installed = state?.installation?.ready === true;
  document
    .querySelectorAll(
      "button[data-action]:not(.icon-button):not(.sidebar-shade), #saveModeButton, #consoleSend, #accessForm button",
    )
    .forEach((button) => {
      const harmless = [
        "refresh",
        "menu",
        "close-menu",
        "copy-connect",
        "copy-endpoint",
        "refresh-activity",
        "refresh-players",
        "refresh-jobs",
        "view-job",
        "reset-draft",
      ].includes(button.dataset.action);
      if (!harmless) button.disabled = !ready;
      if (
        button.dataset.action === "start-mode" ||
        (button.dataset.action === "maintenance" &&
          button.dataset.kind !== "install")
      )
        button.disabled = !ready || !installed;
      if (
        button.dataset.action === "start-map" &&
        !draft.map_pool?.includes(button.dataset.map)
      )
        button.disabled = true;
    });
  $("startButton").disabled =
    !ready || !installed || !!state?.active || !selectedMode;
  $("restartButton").disabled = !ready || !state?.active || !activeMode();
  $("stopButton").disabled = !ready || !state?.active;
  $("consoleSend").disabled = !ready || !state?.active;
}

async function run(operation, success) {
  if (busy) return;
  busy = true;
  lockButtons();
  message("");
  try {
    const result = await operation();
    if (success) message(success, "success");
    return result;
  } catch (error) {
    message(error.message, "error");
  } finally {
    busy = false;
    lockButtons();
    await refresh();
  }
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    message("Copied to clipboard.", "success");
  } catch {
    message(`Copy this value: ${text}`);
  }
}

function renderStatus() {
  const running = !!state.active;
  const ready = state.operational_state === "Ready";
  const maintenance = state.maintenance_active;
  const status = maintenance
    ? "Maintenance"
    : ready
      ? "Online"
      : state.operational_state === "UnknownMode"
        ? "Choose a mode"
        : running
          ? "Starting"
          : "Stopped";
  const tone =
    maintenance || (running && !ready) ? "amber" : ready ? "green" : "neutral";
  const mode = activeMode();
  const settings = state.modes[mode || selectedMode] || {};
  const format = formatFor(mode || selectedMode, settings);
  const label = activeMeta().label || "No active mode";
  $("serverName").textContent =
    (running ? settings.hostname : state.server.hostname) ||
    "CS2 Dedicated Server";
  $("sideServer").textContent = $("serverName").textContent;
  $("stateBadge").textContent = status;
  $("stateBadge").className = "badge " + tone;
  $("sideDot").className =
    "status-dot " +
    (ready ? "online" : running || maintenance ? "starting" : "");
  $("endpoint").textContent = endpoint();
  $("copyEndpoint").textContent = endpoint();
  $("connectCommand").textContent = "connect " + endpoint();
  $("activeMode").textContent = label;
  $("activeMap").textContent = running
    ? mapLabel(settings.map_pool?.[0])
    : "No map loaded";
  $("infoStatus").innerHTML = `<span class="badge ${tone}">${status}</span>`;
  $("infoContainer").textContent = state.containers[0]?.name || "-";
  $("infoAccess").textContent =
    state.visibility === "private" ? "Private · password protected" : "Public";
  $("consoleTarget").textContent = label;
  $("settingsEndpoint").textContent = endpoint();
  $("settingsPort").textContent = state.endpoint.port;
  $("settingsMode").textContent = label;
  $("overviewMode").textContent = running ? label : "Ready for your next game";
  $("overviewModeDetail").textContent = running
    ? activeMeta().implementation
    : "Choose FaceIt competitive or Retakes.";
  $("modeMonogram").innerHTML =
    mode === "faceit"
      ? "F<span>/</span>"
      : mode === "retakes"
        ? "R<span>/</span>"
        : "CS<span>2</span>";
  $("modeVisualTag").textContent =
    mode === "faceit"
      ? "COMPETITIVE · MATCHZY"
      : mode === "retakes"
        ? "RETAKE. DEFUSE. REPEAT."
        : "YOUR DEDICATED SERVER";
  $("formatBadge").textContent = running
    ? format?.label || settings.format || "-"
    : "2 modes";
  $("dashboardModePills").innerHTML = state.mode_order
    .map(
      (id) =>
        `<button class="mode-pill ${id === mode ? "active" : ""}" data-action="configure-mode" data-mode="${esc(id)}">${esc(state.mode_meta[id].label)} ${id === mode ? "· active" : ""}</button>`,
    )
    .join("");
  $("maintenanceBadge").textContent = maintenance
    ? "Maintenance running"
    : "Idle";
  $("maintenanceBadge").className =
    "badge " + (maintenance ? "amber" : "neutral");
  const installation = state.installation || {};
  $("installationNotice").hidden = installation.ready === true;
  $("installationNoticeDetail").textContent = maintenance
    ? "Setup is running. Follow its progress and download output in Maintenance."
    : "Your panel is ready. Complete server installation in Maintenance before starting a game.";
  $("installationBadge").textContent = installation.ready
    ? "Installed"
    : installation.game_files
      ? "Setup incomplete"
      : "Not installed";
  $("installationBadge").className =
    "badge " + (installation.ready ? "green" : "amber");
  $("installationDetail").textContent = installation.ready
    ? "Your server is installed. You can repair the installation here; existing game files are reused and the game is left stopped."
    : "Install CS2, Metamod and CounterStrikeSharp, then choose FaceIt or Retakes. Downloads start only when you press Install server. Failed downloads can be retried here while the panel stays available.";
  $("installServerButton").textContent = installation.ready
    ? "Repair installation"
    : "Install server";
  updateUptime();
  lockButtons();
}

function updateUptime() {
  const started = state?.active?.started_at;
  const seconds = started
    ? Math.max(0, Math.floor((Date.now() - new Date(started).getTime()) / 1000))
    : 0;
  $("uptime").textContent = started
    ? `${Math.floor(seconds / 86400)}d ${Math.floor(seconds / 3600) % 24}h ${Math.floor(seconds / 60) % 60}m`
    : "-";
}

function renderMetrics(stats) {
  const running = !!state.active;
  $("cpuValue").textContent =
    stats.cpu_percent != null ? `${stats.cpu_percent.toFixed(1)}%` : "-";
  $("cpuNote").textContent = running
    ? "Across all CPU cores"
    : "Server is stopped";
  if (stats.cpu_percent != null) {
    cpuHistory.push(stats.cpu_percent);
    if (cpuHistory.length > 30) cpuHistory.shift();
    const ceiling = Math.max(100, ...cpuHistory);
    $("cpuLine").setAttribute(
      "points",
      cpuHistory
        .map(
          (v, i) =>
            `${(i * 200) / Math.max(1, cpuHistory.length - 1)},${31 - (v / ceiling) * 29}`,
        )
        .join(" "),
    );
  } else {
    cpuHistory.length = 0;
    $("cpuLine").setAttribute("points", "");
  }
  $("memoryValue").textContent =
    stats.mem_used_mb != null
      ? `${(stats.mem_used_mb / 1024).toFixed(2)} GB`
      : "-";
  $("memoryNote").textContent = stats.mem_limit_mb
    ? `of ${(stats.mem_limit_mb / 1024).toFixed(1)} GB available to the container`
    : "Server is stopped";
  $("memoryBar").value = stats.mem_percent || 0;
  $("diskValue").textContent =
    stats.disk_used_gb != null ? `${stats.disk_used_gb.toFixed(1)} GB` : "-";
  $("diskNote").textContent = stats.disk_total_gb
    ? `of ${stats.disk_total_gb.toFixed(1)} GB · game filesystem`
    : "Disk metrics unavailable";
  $("diskBar").value = stats.disk_percent || 0;
}

function renderHealth(result) {
  const checks = result.checks;
  const items = [
    ["RCON", checks.rcon],
    ["Metamod", checks.metamod],
    ["CounterStrikeSharp", checks.counterstrikesharp],
    ...Object.entries(checks.required_plugins || {}),
  ];
  $("pluginHealth").innerHTML = state.active
    ? items
        .map(
          ([name, ok]) =>
            `<div class="plugin-row ${ok === true ? "pass" : ok === false ? "fail" : ""}"><span>${esc(name)}</span>${icon(ok === true ? "check" : "clock")}</div>`,
        )
        .join("")
    : '<p class="empty">Start the server to check its plugins.</p>';
  const verified =
    checks.rcon &&
    checks.metamod &&
    checks.counterstrikesharp &&
    Object.values(checks.required_plugins || {}).every(Boolean);
  $("healthSummary").textContent = !state.active
    ? "Server stopped"
    : verified
      ? "All healthy"
      : "Checking";
  $("healthSummary").className = "badge " + (verified ? "green" : "neutral");
  if (checks.map) {
    liveMap = checks.map;
    $("activeMap").textContent = mapLabel(checks.map);
  }
  const capacity = formatFor(activeMode(), state.modes[activeMode()])?.capacity;
  $("infoPlayers").textContent =
    checks.players != null
      ? `${checks.players} / ${capacity || "-"} players`
      : state.active
        ? "Waiting for RCON"
        : "0 players";
  $("navPlayers").textContent =
    checks.players != null ? checks.players : state.active ? "-" : "0";
}

function loadDraft(mode) {
  selectedMode = mode;
  draft = structuredClone(state.modes[mode]);
  savedDraft = structuredClone(draft);
  renderModeEditor();
}

async function selectMode(mode) {
  if (mode === selectedMode) return;
  if (
    dirty() &&
    !(await confirmAction(
      "Discard unsaved changes?",
      "Switching presets discards the edits you have not saved.",
      "Discard & switch",
    ))
  )
    return;
  loadDraft(mode);
}

function renderModeEditor() {
  if (!state || !selectedMode) return;
  const meta = selectedMeta();
  const controls = meta.panel?.controls || [];
  $("modeSelector").innerHTML = state.mode_order
    .map(
      (id) =>
        `<button class="mode-choice ${id === selectedMode ? "selected" : ""}" data-action="select-mode" data-mode="${esc(id)}"><span>${icon(id === "faceit" ? "shield" : "modes")}</span><span><strong>${esc(state.mode_meta[id].label)}</strong><small>${esc(state.mode_meta[id].implementation)}</small></span>${id === activeMode() ? '<span class="badge green">Active</span>' : ""}</button>`,
    )
    .join("");
  $("setupTitle").textContent = `${meta.label} configuration`;
  $("modePolicy").textContent = meta.panel?.note || "";
  $("commonForm").innerHTML = controls.includes("identity")
    ? `<div><label class="field-label" for="hostnameInput">Server name</label><input type="text" id="hostnameInput" data-field="hostname" maxlength="80" value="${esc(draft.hostname)}" required></div>`
    : "";
  $("formatBlock").hidden = !controls.includes("format");
  $("formatRow").innerHTML = (meta.formats || [])
    .map(
      (f) =>
        `<button type="button" class="format-option ${f.key === draft.format ? "selected" : ""}" data-action="format" data-format="${esc(f.key)}"><strong>${esc(f.label)}</strong><small>${esc(f.detail)}</small></button>`,
    )
    .join("");
  renderMapPool();
  updateDraftFlag();
  lockButtons();
}

function renderMapPool() {
  const pool = draft.map_pool || [];
  $("poolCount").textContent = `${pool.length} selected`;
  $("mapGrid").innerHTML = (state.allowed_maps || [])
    .map((map) => {
      const included = pool.includes(map),
        start = pool[0] === map;
      return `<div class="map-tile ${included ? "selected" : ""}"><label><input type="checkbox" data-map="${esc(map)}" ${included ? "checked" : ""}>${esc(mapLabel(map))}</label><div class="map-tile-footer"><span>${start ? "START MAP" : "DEFUSAL"}</span><button type="button" class="start-map" data-action="start-map" data-map="${esc(map)}" ${!included ? "disabled" : ""} title="Set starting map">${start ? "★" : "Set start"}</button></div></div>`;
    })
    .join("");
}

function updateDraftFlag() {
  $("unsavedFlag").hidden = !dirty();
  const changedFormat = draft.format !== savedDraft.format;
  $("saveHint").textContent = changedFormat
    ? "Changing the format requires a server restart."
    : "Saved settings apply on the next start or restart.";
}

async function saveMode(start = false) {
  if (!selectedMode) return;
  if (!draft.map_pool?.length) {
    $("validationMsg").textContent = "Select at least one map.";
    return;
  }
  if (
    start &&
    state.active &&
    !(await confirmAction(
      "Restart in " + selectedMeta().label + "?",
      "The current game stops and connected players will be disconnected. Your selected preset and map pool will be applied.",
      "Save & restart",
    ))
  )
    return;
  await run(
    async () => {
      const result = await api(
        `modes/${selectedMode}/${start ? "start" : "settings"}`,
        { method: start ? "POST" : "PUT", body: draft },
      );
      draft = structuredClone(result.settings);
      savedDraft = structuredClone(draft);
      $("validationMsg").textContent = "";
      renderModeEditor();
      lastHealth = 0;
    },
    start
      ? "Starting the selected game mode. Watch the status for readiness."
      : "Settings saved. They apply on the next start or restart.",
  );
}

async function serverAction(action) {
  if (!state) return;
  if (action === "start") {
    await saveMode(true);
    return;
  }
  const detail =
    action === "stop"
      ? "The game process will stop and connected players will be disconnected."
      : "The game process will restart. Connected players will be disconnected and the saved settings will be applied.";
  if (
    !(await confirmAction(
      action === "stop" ? "Stop the server?" : "Restart the server?",
      detail,
      action === "stop" ? "Stop server" : "Restart server",
    ))
  )
    return;
  await run(
    () => api("server/" + action, { method: "POST" }),
    action === "stop" ? "Server stopped." : "Server is restarting.",
  );
  lastHealth = 0;
}

async function loadCommands() {
  const result = await api("commands");
  commandCatalog = result.groups || [];
  $("commandGroups").innerHTML = !state.active
    ? '<p class="empty">Start the server to use commands.</p>'
    : commandCatalog
        .map(
          (group) =>
            `<div><h4>${esc(group.label)}</h4><div class="command-buttons">${group.commands.map((command) => `<button class="button" data-action="command" data-command="${esc(command.cmd)}" data-hint="${esc(command.arg_hint || "")}" data-confirm="${command.confirm ? "1" : "0"}" title="${esc(command.description)}">${esc(command.label)}${command.arg_hint ? "..." : ""}</button>`).join("")}</div></div>`,
        )
        .join("");
  const quickKeys =
    activeMode() === "faceit"
      ? ["start", "pause", "unpause", "end"]
      : ["force_a", "force_b", "force_auto", "scramble"];
  let quick = commandCatalog
    .flatMap((group) => group.commands)
    .filter((cmd) => quickKeys.includes(cmd.key))
    .slice(0, 4);
  if (!quick.length)
    quick = commandCatalog
      .flatMap((group) => group.commands)
      .filter((cmd) => !cmd.arg_hint)
      .slice(0, 4);
  $("quickActions").innerHTML = state.active
    ? quick
        .map(
          (command) =>
            `<button class="button" data-action="command" data-command="${esc(command.cmd)}" data-hint="${esc(command.arg_hint || "")}" data-confirm="${command.confirm ? "1" : "0"}">${icon("modes")}${esc(command.label)}</button>`,
        )
        .join("")
    : '<p class="empty">Start a game mode to see its controls.</p>';
  const pool = state.modes[activeMode()]?.map_pool || [];
  $("mapSwitch").innerHTML = state.active
    ? pool
        .map(
          (map) =>
            `<button class="button" data-action="map" data-map="${esc(map)}">${icon("map")}${esc(mapLabel(map))}</button>`,
        )
        .join("")
    : "";
  lockButtons();
}

async function sendCommand(command, needsConfirm = false) {
  if (!command.trim()) return;
  if (
    needsConfirm &&
    !(await confirmAction(
      "Run this command?",
      `${command}\n\nThis action can change the current match.`,
      "Run command",
    ))
  )
    return;
  await run(async () => {
    const result = await api("console/command", {
      method: "POST",
      body: { command: command.trim() },
    });
    $("commandOutput").textContent =
      `> ${result.command}\n${result.output || "(No output)"}`;
    $("commandOutput").hidden = false;
    $("consoleInput").value = "";
    if (page !== "console")
      message("Command sent: " + result.command, "success");
  });
}

async function loadLogs() {
  if ($("pauseLogs").checked) return;
  const result = await api(
    `logs/stream?source=${encodeURIComponent($("logSource").value)}&tail=300`,
  );
  const log = $("logs");
  log.textContent =
    result.logs ||
    (state?.active
      ? "Waiting for game output..."
      : "The game server is stopped. Select a mode and start it to see game logs.");
  if ($("followLogs").checked) log.scrollTop = log.scrollHeight;
}

async function loadPlayers() {
  const result = await api("players");
  players = result.players || [];
  $("playersNote").textContent =
    result.note ||
    (result.source === "status"
      ? "Basic player information from CS2 status. Team and Steam ID details require PanelBridge."
      : "Player information is refreshed while this page is open.");
  $("playerCount").textContent = players.length;
  renderPlayers();
}

function renderPlayers() {
  const filter = $("playerSearch").value.toLowerCase();
  const visible = players.filter((player) =>
    player.name.toLowerCase().includes(filter),
  );
  $("playersBody").innerHTML = visible.length
    ? visible
        .map(
          (player) =>
            `<tr><td><div class="player-name"><span class="player-avatar">${esc(player.name.charAt(0).toUpperCase())}</span><span>${esc(player.name)} ${player.bot ? '<span class="badge neutral">BOT</span>' : ""}</span></div></td><td><span class="badge ${player.team === 3 ? "violet" : player.team === 2 ? "amber" : "neutral"}">${esc(player.team_label)}</span></td><td>${player.ping != null ? `${player.ping} ms` : "-"}</td><td class="steam-id">${esc(player.steamid64 || "-")}</td><td><div class="row-actions"><button class="button small" data-action="player" data-kind="kick" data-userid="${player.userid}" data-name="${esc(player.name)}">Kick</button>${!player.bot ? `<button class="button small danger" data-action="player" data-kind="ban" data-userid="${player.userid}" data-name="${esc(player.name)}">Ban</button>` : ""}</div></td></tr>`,
        )
        .join("")
    : `<tr><td colspan="5" class="empty">${filter ? "No players match your search." : "No connected players."}</td></tr>`;
  lockButtons();
}

function renderAccess() {
  if (document.activeElement?.closest("#accessForm")) return;
  document
    .querySelectorAll('input[name="visibility"]')
    .forEach((input) => (input.checked = input.value === state.visibility));
  $("passwordHint").textContent = state.password.has_password
    ? "A password is stored. Leave blank to keep it."
    : "Set a password before switching to private access.";
}

function renderVersions() {
  const labels = {
    metamod: "Metamod",
    counterstrikesharp: "CounterStrikeSharp",
    matchzy: "MatchZy",
    retakes: "Retakes",
  };
  $("versionGrid").innerHTML = Object.entries(labels)
    .map(
      ([key, label]) =>
        `<div class="version-cell"><span>${label}</span><strong>${esc(state.versions?.[key]?.version || "-")}</strong><small>${key === "metamod" || key === "counterstrikesharp" ? "PINNED FRAMEWORK" : "BUNDLED MODE PLUGIN"}</small></div>`,
    )
    .join("");
}

async function loadActivity() {
  const result = await api("audit");
  const items = (result.items || []).slice().reverse();
  $("recentActivity").innerHTML = items.length
    ? items
        .slice(0, 3)
        .map(
          (item) =>
            `<div class="activity-row"><span class="activity-marker">${icon("activity")}</span><span>${esc(item.action)}${item.target ? " · " + esc(state.mode_meta[item.target]?.label || item.target) : ""}</span><span class="badge ${["ok", "succeeded"].includes(item.result) ? "green" : "amber"}">${esc(item.result)}</span><span class="activity-time">${timeLabel(item.time)}</span></div>`,
        )
        .join("")
    : '<p class="empty">No activity yet. Server actions will appear here.</p>';
  $("auditBody").innerHTML = items.length
    ? items
        .map(
          (item) =>
            `<tr><td class="mono">${timeLabel(item.time)}</td><td>${esc(item.action)}</td><td>${esc(state.mode_meta[item.target]?.label || item.target || "-")}</td><td><span class="badge ${["ok", "succeeded"].includes(item.result) ? "green" : "amber"}">${esc(item.result)}</span></td><td>${esc(item.user)}</td></tr>`,
        )
        .join("")
    : '<tr><td colspan="5" class="empty">No actions recorded today.</td></tr>';
}

async function loadMaintenance() {
  const results = await Promise.allSettled([
    api("maintenance/backups"),
    api("maintenance/jobs"),
  ]);
  for (let index = 0; index < results.length; index++) {
    const result = results[index];
    if (result.status === "rejected") throw result.reason;
    if (index === 0) {
      const list = result.value.backups || [];
      $("backupsList").innerHTML = list.length
        ? list
            .map(
              (backup) =>
                `<div class="backup-row">${icon("disk")}<div><strong>${esc(backup.name)}</strong><small>${dateLabel(backup.created)}</small></div><button class="button small" data-action="restore" data-backup="${esc(backup.name)}">Restore</button></div>`,
            )
            .join("")
        : '<p class="empty">No configuration backups yet.</p>';
    } else {
      const jobs = result.value.jobs || [];
      $("jobsList").innerHTML = jobs.length
        ? jobs
            .map(
              (job) =>
                `<div class="job-row">${icon("tools")}<div><strong>${esc(job.type)}</strong><small>${dateLabel(job.start)}${job.step ? " · " + esc(job.step) + " (" + job.percent + "%)" : ""}${job.error ? " · " + esc(job.error) : ""}</small></div><span class="badge ${job.status === "Succeeded" ? "green" : job.status === "Failed" ? "red" : "amber"}">${esc(job.status)}</span><button class="text-button" data-action="view-job" data-job="${esc(job.id)}">View log</button></div>`,
            )
            .join("")
        : '<p class="empty">No maintenance jobs yet.</p>';
    }
  }
  if (selectedJob) await loadJob(selectedJob);
  lockButtons();
}

async function loadJob(id) {
  selectedJob = id;
  const result = await api("maintenance/jobs/" + encodeURIComponent(id));
  $("jobOutput").textContent =
    `${result.job.status} · ${result.job.step || "Queued"} (${result.job.percent}%)\n\n` +
    ((result.job.log || []).join("\n") || "Job is queued...");
  $("jobOutput").hidden = false;
}

async function maintenance(kind) {
  const label = {
    install: state?.installation?.ready
      ? "Repair installation"
      : "Install server",
    update: "Update CS2",
    validate: "Validate game files",
    "repair-metamod": "Repair Metamod",
  }[kind];
  if (
    !(await confirmAction(
      label + "?",
      kind === "install"
        ? "Download or reuse CS2 game files, install the required frameworks and prepare FaceIt and Retakes. Existing configuration is backed up first. The game is left stopped and the panel stays available."
        : "The game stops while this job runs. A configuration backup is created first. If verification succeeds, the previously running mode resumes.",
      kind === "install" ? label : "Start maintenance",
    ))
  )
    return;
  await run(async () => {
    const result = await api("maintenance/" + kind, {
      method: "POST",
      body: { confirm: "UPDATE CS2" },
    });
    selectedJob = result.job.id;
    location.hash = "maintenance";
  }, "Maintenance started. Follow progress in the job log.");
}

async function refresh() {
  if (refreshing || document.hidden) return;
  refreshing = true;
  try {
    const previousMode = activeMode();
    state = await api("status");
    if (previousMode !== activeMode() || !state.active) liveMap = null;
    connected = true;
    if (!selectedMode || !state.modes[selectedMode])
      loadDraft(
        state.active?.mode || state.server.last_mode || state.mode_order[0],
      );
    renderStatus();
    renderAccess();
    renderVersions();
    $("syncState").textContent =
      "Updated " + timeLabel(new Date().toISOString());
    $("syncState").className = "sync-state";
    const work = [];
    if (page === "dashboard" || previousMode !== activeMode())
      work.push(api("metrics").then((result) => renderMetrics(result.stats)));
    if (Date.now() - lastHealth > 20000 || previousMode !== activeMode()) {
      work.push(api("health").then(renderHealth));
      lastHealth = Date.now();
    }
    if (page === "dashboard" || page === "console") work.push(loadCommands());
    if (page === "console") work.push(loadLogs());
    if (page === "players") work.push(loadPlayers());
    if (page === "maintenance") work.push(loadMaintenance());
    if (
      page === "activity" ||
      (page === "dashboard" && Date.now() - lastActivity > 20000)
    ) {
      work.push(loadActivity());
      lastActivity = Date.now();
    }
    const results = await Promise.allSettled(work);
    const failure = results.find((result) => result.status === "rejected");
    if (failure) {
      message(failure.reason.message, "error");
    }
    // Never overwrite an in-progress configuration or focused form input.
    if (
      page === "modes" &&
      !dirty() &&
      !document.activeElement?.closest("#modeForm")
    )
      loadDraft(selectedMode);
  } catch (error) {
    connected = false;
    $("syncState").textContent = "Connection lost";
    $("syncState").className = "sync-state error";
    $("stateBadge").textContent = "Disconnected";
    $("stateBadge").className = "badge red";
    $("sideDot").className = "status-dot";
    message(error.message, "error");
    lockButtons();
  } finally {
    refreshing = false;
  }
}

function navigate() {
  const next = location.hash.slice(1) || "dashboard";
  page = Object.hasOwn(names, next) ? next : "dashboard";
  document
    .querySelectorAll(".page")
    .forEach((element) => (element.hidden = element.id !== "page-" + page));
  document.querySelectorAll(".nav-link").forEach((link) => {
    const active = link.hash === "#" + page;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  window.scrollTo({ top: 0, behavior: "instant" });
  $("pageLabel").textContent = names[page];
  document.title = names[page] + " | CS2 Control";
  document.body.classList.remove("sidebar-open");
  if (state) {
    const loader = {
      console: () => Promise.all([loadCommands(), loadLogs()]),
      players: loadPlayers,
      maintenance: loadMaintenance,
      activity: loadActivity,
    };
    if (loader[page])
      loader[page]().catch((error) => message(error.message, "error"));
    if (page === "modes") renderModeEditor();
    if (page === "settings") renderAccess();
  }
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button || button.disabled) return;
  const action = button.dataset.action;
  try {
    if (action === "menu") document.body.classList.toggle("sidebar-open");
    else if (action === "close-menu")
      document.body.classList.remove("sidebar-open");
    else if (action === "refresh") {
      lastHealth = 0;
      lastActivity = 0;
      await refresh();
    } else if (["start", "stop", "restart"].includes(action))
      await serverAction(action);
    else if (action === "copy-endpoint") await copy(endpoint());
    else if (action === "copy-connect") await copy("connect " + endpoint());
    else if (action === "select-mode") await selectMode(button.dataset.mode);
    else if (action === "configure-mode") {
      await selectMode(button.dataset.mode);
      location.hash = "modes";
    } else if (action === "format") {
      draft.format = button.dataset.format;
      renderModeEditor();
    } else if (action === "start-map") {
      const map = button.dataset.map;
      draft.map_pool = [map, ...draft.map_pool.filter((item) => item !== map)];
      renderMapPool();
      updateDraftFlag();
    } else if (action === "reset-draft") {
      loadDraft(selectedMode);
      $("validationMsg").textContent = "";
    } else if (action === "start-mode") await saveMode(true);
    else if (action === "command") {
      if (button.dataset.hint) {
        location.hash = "console";
        $("consoleInput").value = button.dataset.command + " ";
        $("consoleInput").focus();
        message("Complete the command argument: " + button.dataset.hint);
      } else
        await sendCommand(
          button.dataset.command,
          button.dataset.confirm === "1",
        );
    } else if (action === "map") {
      if (
        await confirmAction(
          "Switch map?",
          `Load ${mapLabel(button.dataset.map)}? Players will be disconnected during the map change.`,
          "Switch map",
        )
      )
        await run(
          () =>
            api("server/map", {
              method: "POST",
              body: { map: button.dataset.map },
            }),
          "Map change requested.",
        );
      lastHealth = 0;
    } else if (action === "player") {
      const ban = button.dataset.kind === "ban";
      if (
        await confirmAction(
          ban ? "Permanently ban player?" : "Kick player?",
          `${button.dataset.name}\n\n${ban ? "This player will be banned and disconnected." : "This player will be disconnected and may reconnect."}`,
          ban ? "Ban player" : "Kick player",
        )
      )
        await run(
          () =>
            api(`players/${button.dataset.userid}/${button.dataset.kind}`, {
              method: "POST",
              body: { userid: Number(button.dataset.userid), minutes: 0 },
            }),
          "Player action completed.",
        );
    } else if (action === "refresh-players") await loadPlayers();
    else if (action === "refresh-activity") await loadActivity();
    else if (action === "refresh-jobs") await loadMaintenance();
    else if (action === "view-job") await loadJob(button.dataset.job);
    else if (action === "maintenance") await maintenance(button.dataset.kind);
    else if (action === "backup")
      await run(async () => {
        const result = await api("maintenance/backup", { method: "POST" });
        selectedJob = result.job.id;
      }, "Configuration backup started.");
    else if (action === "restore") {
      if (
        await confirmAction(
          "Restore this backup?",
          `${button.dataset.backup}\n\nCurrent settings will be backed up, the server will stop and the saved configuration will be restored. Start a mode when you are ready.`,
          "Restore backup",
        )
      )
        await run(async () => {
          const result = await api("maintenance/restore", {
            method: "POST",
            body: { backup: button.dataset.backup, confirm: "UPDATE CS2" },
          });
          selectedJob = result.job.id;
        }, "Restore started. Follow the job log.");
    } else if (action === "verify") {
      const result = await api("maintenance/verify-mounts");
      const checks = result.checks || result.mounts || {};
      $("verification").innerHTML = Object.entries(checks)
        .map(
          ([name, ok]) =>
            `<span class="badge ${ok === true ? "green" : "red"}">${ok === true ? "OK" : "FAIL"} ${esc(name)}</span>`,
        )
        .join("");
      $("verification").hidden = false;
    }
  } catch (error) {
    message(error.message, "error");
  }
});

document.addEventListener("input", (event) => {
  if (event.target.dataset.field) {
    draft[event.target.dataset.field] = event.target.value;
    updateDraftFlag();
  }
  if (event.target.id === "playerSearch") renderPlayers();
});
document.addEventListener("change", (event) => {
  const map = event.target.dataset.map;
  if (map && event.target.matches("input[type=checkbox]")) {
    draft.map_pool = event.target.checked
      ? [...(draft.map_pool || []), map]
      : draft.map_pool.filter((item) => item !== map);
    renderMapPool();
    updateDraftFlag();
  }
  if (event.target.id === "logSource")
    loadLogs().catch((error) => message(error.message, "error"));
});
$("modeForm").addEventListener("submit", (event) => {
  event.preventDefault();
  saveMode().catch((error) => message(error.message, "error"));
});
$("consoleForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const command = $("consoleInput").value.trim();
  const known = commandCatalog
    .flatMap((group) => group.commands)
    .find(
      (item) =>
        command === item.cmd ||
        (item.arg_hint && command.startsWith(item.cmd + " ")),
    );
  sendCommand(
    command,
    known?.confirm ||
      /^(?:changelevel|mp_restartgame|kick|ban|css_endmatch|css_restart)\b/.test(
        command,
      ),
  ).catch((error) => message(error.message, "error"));
});
$("accessForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const visibility = document.querySelector(
    "input[name=visibility]:checked",
  ).value;
  const password = $("lobbyPassword").value;
  if (visibility === "private" && !password && !state?.password.has_password) {
    message("Set a lobby password before enabling private access.", "error");
    return;
  }
  await run(async () => {
    await api("server/visibility", {
      method: "PUT",
      body: { visibility, ...(password ? { password } : {}) },
    });
    $("lobbyPassword").value = "";
  }, "Lobby access updated.");
});
window.addEventListener("hashchange", navigate);
window.addEventListener("beforeunload", (event) => {
  if (dirty()) {
    event.preventDefault();
    event.returnValue = "";
  }
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
navigate();
refresh();
setInterval(refresh, 6000);
setInterval(updateUptime, 1000);
