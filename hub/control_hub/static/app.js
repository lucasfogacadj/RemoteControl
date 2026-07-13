const els = {
  fleetToggleButton: document.querySelector("#fleetToggleButton"),
  fleetMessage: document.querySelector("#fleetMessage"),
  fleetBadge: document.querySelector("#fleetBadge"),
  fleetCount: document.querySelector("#fleetCount"),
  fleetOnlineCount: document.querySelector("#fleetOnlineCount"),
  schedulerStatus: document.querySelector("#schedulerStatus"),
  agentBadge: document.querySelector("#agentBadge"),
  agentId: document.querySelector("#agentId"),
  agentHeartbeat: document.querySelector("#agentHeartbeat"),
  agentSession: document.querySelector("#agentSession"),
  workSummary: document.querySelector("#workSummary"),
  agentList: document.querySelector("#agentList"),
  agentListMessage: document.querySelector("#agentListMessage"),
  refreshButton: document.querySelector("#refreshButton"),
  selectedTitle: document.querySelector("#selectedTitle"),
  agentToggleButton: document.querySelector("#agentToggleButton"),
  cancelButton: document.querySelector("#cancelButton"),
  detailMessage: document.querySelector("#detailMessage"),
  settingsForm: document.querySelector("#settingsForm"),
  saveButton: document.querySelector("#saveButton"),
  formMessage: document.querySelector("#formMessage"),
  dirtySelectionDialog: document.querySelector("#dirtySelectionDialog"),
  dirtySelectionAgent: document.querySelector("#dirtySelectionAgent"),
  dirtySelectionError: document.querySelector("#dirtySelectionError"),
  dirtySelectionCancelButton: document.querySelector("#dirtySelectionCancelButton"),
  dirtySelectionDiscardButton: document.querySelector("#dirtySelectionDiscardButton"),
  dirtySelectionSaveButton: document.querySelector("#dirtySelectionSaveButton"),
  routineList: document.querySelector("#routineList"),
  eventList: document.querySelector("#eventList"),
  commandList: document.querySelector("#commandList"),
  vscodeTargetFile: document.querySelector("#vscodeTargetFile"),
  vscodeTextLength: document.querySelector("#vscodeTextLength"),
  vscodeTypingInterval: document.querySelector("#vscodeTypingInterval"),
  codeLanguage: document.querySelector("#codeLanguage"),
  typoRate: document.querySelector("#typoRate"),
  thinkingPauseChance: document.querySelector("#thinkingPauseChance"),
  mouseClickButton: document.querySelector("#mouseClickButton"),
  mouseClickCount: document.querySelector("#mouseClickCount"),
  mouseClickMargin: document.querySelector("#mouseClickMargin"),
  mouseMoveDuration: document.querySelector("#mouseMoveDuration"),
  mouseOvershootChance: document.querySelector("#mouseOvershootChance"),
  minInterval: document.querySelector("#minInterval"),
  maxInterval: document.querySelector("#maxInterval"),
  workStart: document.querySelector("#workStart"),
  workEnd: document.querySelector("#workEnd"),
  timezone: document.querySelector("#timezone"),
  profile: document.querySelector("#profile"),
  lunchStart: document.querySelector("#lunchStart"),
  lunchEnd: document.querySelector("#lunchEnd"),
  lunchJitter: document.querySelector("#lunchJitter"),
  coffeeBreakCount: document.querySelector("#coffeeBreakCount"),
  workStartJitter: document.querySelector("#workStartJitter"),
  scenarioType: document.querySelector("#scenarioType"),
};

const state = {
  fleet: null,
  selectedAgentId: localStorage.getItem("control.selectedAgentId") || null,
  detail: null,
  settings: null,
  revision: null,
  dirty: false,
  pendingAgentId: null,
  fleetAbort: null,
  detailAbort: null,
  fleetTimer: null,
  detailTimer: null,
};

function clear(element) { while (element.firstChild) element.removeChild(element.firstChild); }
function text(element, value) { element.textContent = value == null || value === "" ? "-" : String(value); }
function number(value) { return Number(value); }
function setMessage(element, message, isError = false) { element.textContent = message || ""; element.classList.toggle("error", Boolean(isError)); }
function setBadge(element, label, mode) { element.textContent = label; element.className = `badge ${mode || ""}`.trim(); }
function formatDate(value) { return value ? new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value)) : "-"; }

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const raw = await response.text();
  let payload = {};
  try { payload = raw ? JSON.parse(raw) : {}; } catch { payload = { detail: raw }; }
  if (!response.ok) {
    const detail = typeof payload.detail === "object" ? payload.detail.message : payload.detail;
    const error = new Error(detail || "Falha na requisição.");
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return { payload, response };
}

function button(label, className = "") {
  const element = document.createElement("button");
  element.type = "button";
  element.className = className;
  element.textContent = label;
  return element;
}

function renderFleet(fleetState) {
  state.fleet = fleetState;
  const fleet = fleetState.fleet;
  const agents = fleetState.agents || [];
  const online = agents.filter((agent) => agent.online).length;
  setBadge(els.fleetBadge, fleet.enabled ? "Ativa" : "Pausada", fleet.enabled ? "ok" : "warn");
  text(els.fleetCount, agents.length);
  text(els.fleetOnlineCount, online);
  text(els.schedulerStatus, fleetState.scheduler?.task_running ? "Ativo" : "Indisponível");
  els.fleetToggleButton.textContent = fleet.enabled ? "Pausar todos" : "Retomar todos";
  els.fleetToggleButton.setAttribute("aria-pressed", String(fleet.enabled));
  clear(els.agentList);
  for (const agent of agents) {
    const row = button("", "agent-row");
    row.dataset.agentId = agent.agent_id;
    row.setAttribute("role", "option");
    row.setAttribute("aria-selected", String(agent.agent_id === state.selectedAgentId));
    if (agent.agent_id === state.selectedAgentId) row.classList.add("selected");
    const title = document.createElement("strong");
    title.textContent = agent.name || agent.agent_id;
    const subtitle = document.createElement("span");
    subtitle.textContent = `${agent.agent_id} · ${agent.online ? "online" : "offline"} · ${agent.enabled ? "ativo" : "desativado"}`;
    row.append(title, subtitle);
    row.addEventListener("click", () => selectAgent(agent.agent_id));
    els.agentList.appendChild(row);
  }
  if (!agents.length) setMessage(els.agentListMessage, "Nenhum PC conectado ainda. Novos PCs aparecem desativados.");
  else setMessage(els.agentListMessage, "");
}

function renderRoutines(routines) {
  clear(els.routineList);
  for (const routine of routines || []) {
    const row = document.createElement("div");
    row.className = "routine-row";
    row.dataset.routineId = routine.id;
    const title = document.createElement("strong");
    title.className = "routine-title";
    title.textContent = routine.label;
    const percentageLabel = document.createElement("label");
    percentageLabel.textContent = "Percentual";
    const percentage = document.createElement("input");
    percentage.type = "number";
    percentage.min = "0";
    percentage.max = "100";
    percentage.className = "routine-percentage";
    percentage.value = String(routine.percentage);
    percentageLabel.appendChild(percentage);
    const enabledLabel = document.createElement("label");
    enabledLabel.className = "routine-switch";
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.className = "routine-enabled";
    enabled.checked = Boolean(routine.enabled);
    enabledLabel.append(enabled, document.createTextNode("Ativa"));
    row.append(title, percentageLabel, enabledLabel);
    els.routineList.appendChild(row);
  }
}

function renderHistory(list, values, formatter) {
  clear(list);
  for (const value of values || []) {
    const item = document.createElement("li");
    item.className = value.status || "";
    const time = document.createElement("time");
    const title = document.createElement("strong");
    time.textContent = formatter(value).time;
    title.textContent = formatter(value).message;
    item.append(time, title);
    list.appendChild(item);
  }
}

function renderAgentToggle(enabled) {
  els.agentToggleButton.textContent = enabled ? "Desativar PC" : "Ativar PC";
  els.agentToggleButton.setAttribute("aria-pressed", String(enabled));
}

function renderDetail(detail) {
  state.detail = detail;
  state.settings = detail.settings;
  state.revision = detail.settings_revision;
  const agent = detail.agent || {};
  const enabled = Boolean(detail.settings?.enabled);
  setBadge(els.agentBadge, agent.online ? "Online" : "Offline", agent.online ? "ok" : "danger");
  text(els.agentId, agent.agent_id);
  text(els.agentHeartbeat, formatDate(agent.last_heartbeat));
  text(els.agentSession, agent.session_id);
  text(els.workSummary, `${detail.settings.work_start}–${detail.settings.work_end} · ${detail.settings.timezone}`);
  els.selectedTitle.textContent = agent.name || agent.agent_id || "PC selecionado";
  els.agentToggleButton.disabled = false;
  els.cancelButton.disabled = false;
  els.saveButton.disabled = false;
  renderAgentToggle(enabled);
  if (!state.dirty) renderSettings(detail.settings);
  renderHistory(els.eventList, detail.events, (event) => ({ time: `${formatDate(event.created_at)} · ${event.kind}${event.routine ? ` / ${event.routine}` : ""}`, message: event.message }));
  renderHistory(els.commandList, detail.commands, (command) => ({ time: `${formatDate(command.created_at)} · ${command.type} · ${command.status}`, message: command.result_message || "Sem resultado" }));
}

function renderSettings(settings) {
  els.vscodeTargetFile.value = settings.vscode_target_file || "";
  els.vscodeTextLength.value = settings.vscode_text_length;
  els.vscodeTypingInterval.value = settings.vscode_typing_interval_seconds;
  els.codeLanguage.value = settings.code_language;
  els.typoRate.value = settings.typo_rate;
  els.thinkingPauseChance.value = settings.thinking_pause_chance;
  els.mouseClickButton.value = settings.mouse_click_button;
  els.mouseClickCount.value = settings.mouse_click_count;
  els.mouseClickMargin.value = settings.mouse_click_margin;
  els.mouseMoveDuration.value = settings.mouse_move_duration_seconds;
  els.mouseOvershootChance.value = settings.mouse_overshoot_chance;
  els.minInterval.value = settings.min_interval_seconds;
  els.maxInterval.value = settings.max_interval_seconds;
  els.workStart.value = settings.work_start;
  els.workEnd.value = settings.work_end;
  els.timezone.value = settings.timezone;
  els.profile.value = settings.profile;
  els.lunchStart.value = settings.lunch_start;
  els.lunchEnd.value = settings.lunch_end;
  els.lunchJitter.value = settings.lunch_jitter_minutes;
  els.coffeeBreakCount.value = settings.coffee_break_count;
  els.workStartJitter.value = settings.work_start_jitter_minutes;
  els.scenarioType.value = settings.scenario_type;
  renderRoutines(settings.routines);
}

function collectSettings() {
  const routines = [...els.routineList.querySelectorAll(".routine-row")].map((row) => ({
    id: row.dataset.routineId,
    enabled: row.querySelector(".routine-enabled").checked,
    percentage: number(row.querySelector(".routine-percentage").value),
  }));
  return {
    ...state.settings,
    vscode_target_file: els.vscodeTargetFile.value.trim(),
    vscode_text_length: number(els.vscodeTextLength.value),
    vscode_typing_interval_seconds: number(els.vscodeTypingInterval.value),
    code_language: els.codeLanguage.value,
    typo_rate: number(els.typoRate.value),
    thinking_pause_chance: number(els.thinkingPauseChance.value),
    mouse_click_button: els.mouseClickButton.value,
    mouse_click_count: number(els.mouseClickCount.value),
    mouse_click_margin: number(els.mouseClickMargin.value),
    mouse_move_duration_seconds: number(els.mouseMoveDuration.value),
    mouse_overshoot_chance: number(els.mouseOvershootChance.value),
    min_interval_seconds: number(els.minInterval.value),
    max_interval_seconds: number(els.maxInterval.value),
    work_start: els.workStart.value,
    work_end: els.workEnd.value,
    timezone: els.timezone.value.trim(),
    profile: els.profile.value,
    lunch_start: els.lunchStart.value,
    lunch_end: els.lunchEnd.value,
    lunch_jitter_minutes: number(els.lunchJitter.value),
    coffee_break_count: number(els.coffeeBreakCount.value),
    work_start_jitter_minutes: number(els.workStartJitter.value),
    scenario_type: els.scenarioType.value,
    routines,
  };
}

async function changeSelectedAgent(agentId) {
  state.dirty = false;
  state.selectedAgentId = agentId;
  state.detail = null;
  localStorage.setItem("control.selectedAgentId", agentId);
  renderFleet(state.fleet);
  await loadDetail();
}

function requestAgentSelection(agentId) {
  state.pendingAgentId = agentId;
  const agent = state.fleet?.agents?.find((candidate) => candidate.agent_id === agentId);
  text(els.dirtySelectionAgent, agent?.name || agentId);
  setMessage(els.dirtySelectionError, "");
  if (!els.dirtySelectionDialog.open) els.dirtySelectionDialog.showModal();
  els.dirtySelectionCancelButton.focus();
}

function closeAgentSelectionDialog() {
  state.pendingAgentId = null;
  if (els.dirtySelectionDialog.open) els.dirtySelectionDialog.close();
}

async function selectAgent(agentId) {
  if (agentId === state.selectedAgentId) return;
  if (state.dirty) {
    requestAgentSelection(agentId);
    return;
  }
  await changeSelectedAgent(agentId);
}

async function loadFleet() {
  state.fleetAbort?.abort();
  state.fleetAbort = new AbortController();
  try {
    const { payload } = await api("/api/fleet/state", { signal: state.fleetAbort.signal });
    renderFleet(payload);
    const agents = payload.agents || [];
    if (!state.selectedAgentId) {
      if (agents[0]) await changeSelectedAgent(agents[0].agent_id);
    } else if (!agents.some((agent) => agent.agent_id === state.selectedAgentId)) {
      const fallbackAgentId = agents[0]?.agent_id || null;
      if (fallbackAgentId) await selectAgent(fallbackAgentId);
    }
    renderFleet(payload);
    if (state.selectedAgentId && !state.detail) await loadDetail();
    setMessage(els.fleetMessage, "");
  } catch (error) {
    if (error.name !== "AbortError") setMessage(els.fleetMessage, error.message, true);
  }
}

async function loadDetail() {
  if (!state.selectedAgentId || document.hidden) return;
  if (state.dirty) {
    setMessage(els.detailMessage, "Há alterações não salvas. Salve ou descarte antes de atualizar o detalhe.");
    return;
  }
  state.detailAbort?.abort();
  const agentId = state.selectedAgentId;
  state.detailAbort = new AbortController();
  try {
    const { payload } = await api(`/api/agents/${encodeURIComponent(agentId)}/state`, { signal: state.detailAbort.signal });
    if (state.selectedAgentId !== agentId) return;
    if (state.dirty) {
      setMessage(els.detailMessage, "O servidor mudou enquanto você editava. Salve para validar a revisão ou descarte as alterações.");
      return;
    }
    renderDetail(payload);
    setMessage(els.detailMessage, "");
  } catch (error) {
    if (error.name !== "AbortError") setMessage(els.detailMessage, error.message, true);
  }
}

async function saveSettings() {
  if (!state.selectedAgentId || !state.settings) return false;
  els.saveButton.disabled = true;
  setMessage(els.formMessage, "Salvando…");
  try {
    const { payload } = await api(`/api/agents/${encodeURIComponent(state.selectedAgentId)}/settings`, {
      method: "PUT",
      headers: { "If-Match": `"${state.revision}"` },
      body: JSON.stringify(collectSettings()),
    });
    state.dirty = false;
    state.settings = payload.settings;
    state.revision = payload.revision;
    setMessage(els.formMessage, "Configuração salva.");
    await Promise.all([loadFleet(), loadDetail()]);
    return true;
  } catch (error) {
    setMessage(els.formMessage, error.status === 412 ? "A configuração mudou no servidor. Revise antes de sobrescrever." : error.message, true);
    return false;
  } finally {
    els.saveButton.disabled = false;
  }
}

async function submitSettings(event) {
  event.preventDefault();
  await saveSettings();
}

async function discardAndSwitchAgent() {
  const agentId = state.pendingAgentId;
  closeAgentSelectionDialog();
  if (agentId) await changeSelectedAgent(agentId);
}

async function saveAndSwitchAgent() {
  const agentId = state.pendingAgentId;
  if (!agentId) return;
  els.dirtySelectionCancelButton.disabled = true;
  els.dirtySelectionDiscardButton.disabled = true;
  els.dirtySelectionSaveButton.disabled = true;
  const saved = await saveSettings();
  if (saved && state.pendingAgentId === agentId) {
    closeAgentSelectionDialog();
    await changeSelectedAgent(agentId);
  } else if (!saved) {
    setMessage(els.dirtySelectionError, "Não foi possível salvar. Revise a configuração antes de trocar de PC.", true);
  }
  els.dirtySelectionCancelButton.disabled = false;
  els.dirtySelectionDiscardButton.disabled = false;
  els.dirtySelectionSaveButton.disabled = false;
}

async function toggleFleet() {
  if (!state.fleet) return;
  els.fleetToggleButton.disabled = true;
  try { await api("/api/toggle", { method: "POST", body: JSON.stringify({ enabled: !state.fleet.fleet.enabled }) }); await loadFleet(); }
  catch (error) { setMessage(els.fleetMessage, error.message, true); }
  finally { els.fleetToggleButton.disabled = false; }
}

async function toggleAgent() {
  if (!state.selectedAgentId || !state.settings) return;
  els.agentToggleButton.disabled = true;
  try {
    const { payload } = await api(`/api/agents/${encodeURIComponent(state.selectedAgentId)}/toggle`, {
      method: "POST",
      body: JSON.stringify({ enabled: !state.settings.enabled }),
    });
    state.settings = { ...state.settings, enabled: payload.enabled };
    renderAgentToggle(payload.enabled);
    await loadFleet();
    if (state.dirty) setMessage(els.detailMessage, "Estado do PC atualizado; suas alterações não salvas foram preservadas.");
    else await loadDetail();
  }
  catch (error) { setMessage(els.detailMessage, error.message, true); }
  finally { els.agentToggleButton.disabled = false; }
}

async function cancelAgent() {
  if (!state.selectedAgentId) return;
  els.cancelButton.disabled = true;
  try {
    await api(`/api/agents/${encodeURIComponent(state.selectedAgentId)}/cancel`, { method: "POST", body: "{}" });
    if (state.dirty) setMessage(els.detailMessage, "Cancelamento enviado; suas alterações não salvas foram preservadas.");
    else await loadDetail();
  }
  catch (error) { setMessage(els.detailMessage, error.message, true); }
  finally { els.cancelButton.disabled = false; }
}

function startPolling() {
  stopPolling();
  if (document.hidden) return;
  state.fleetTimer = window.setInterval(() => { loadFleet(); }, 5000);
  state.detailTimer = window.setInterval(() => { if (!state.dirty) loadDetail(); }, 7000);
}
function stopPolling() { window.clearInterval(state.fleetTimer); window.clearInterval(state.detailTimer); state.fleetTimer = null; state.detailTimer = null; }

els.settingsForm.addEventListener("submit", submitSettings);
els.settingsForm.addEventListener("input", () => { if (state.settings) state.dirty = true; });
els.fleetToggleButton.addEventListener("click", toggleFleet);
els.agentToggleButton.addEventListener("click", toggleAgent);
els.cancelButton.addEventListener("click", cancelAgent);
els.refreshButton.addEventListener("click", async () => {
  await loadFleet();
  if (state.dirty) setMessage(els.detailMessage, "Frota atualizada; o detalhe não foi recarregado porque há alterações não salvas.");
  else await loadDetail();
});
els.dirtySelectionCancelButton.addEventListener("click", closeAgentSelectionDialog);
els.dirtySelectionDiscardButton.addEventListener("click", discardAndSwitchAgent);
els.dirtySelectionSaveButton.addEventListener("click", saveAndSwitchAgent);
els.dirtySelectionDialog.addEventListener("cancel", () => { state.pendingAgentId = null; });
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { stopPolling(); state.fleetAbort?.abort(); state.detailAbort?.abort(); }
  else { loadFleet(); loadDetail(); startPolling(); }
});

loadFleet().then(startPolling).catch(() => {});
