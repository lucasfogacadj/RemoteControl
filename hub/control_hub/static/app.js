const stateUrl = "/api/state";
const settingsUrl = "/api/settings";
const toggleUrl = "/api/toggle";

const els = {
  toggleButton: document.querySelector("#toggleButton"),
  agentBadge: document.querySelector("#agentBadge"),
  enabledBadge: document.querySelector("#enabledBadge"),
  agentId: document.querySelector("#agentId"),
  agentHeartbeat: document.querySelector("#agentHeartbeat"),
  agentMessage: document.querySelector("#agentMessage"),
  intervalSummary: document.querySelector("#intervalSummary"),
  targetSummary: document.querySelector("#targetSummary"),
  mouseSummary: document.querySelector("#mouseSummary"),
  commandSummary: document.querySelector("#commandSummary"),
  settingsForm: document.querySelector("#settingsForm"),
  routineList: document.querySelector("#routineList"),
  formMessage: document.querySelector("#formMessage"),
  refreshButton: document.querySelector("#refreshButton"),
  vscodeTargetFile: document.querySelector("#vscodeTargetFile"),
  vscodeTextLength: document.querySelector("#vscodeTextLength"),
  mouseClickX: document.querySelector("#mouseClickX"),
  mouseClickY: document.querySelector("#mouseClickY"),
  mouseClickButton: document.querySelector("#mouseClickButton"),
  mouseClickCount: document.querySelector("#mouseClickCount"),
  minInterval: document.querySelector("#minInterval"),
  maxInterval: document.querySelector("#maxInterval"),
  eventList: document.querySelector("#eventList"),
};

let currentSettings = null;
let formDirty = false;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Falha na requisicao.");
  }
  return payload;
}

function formatDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value));
}

function setBadge(element, text, mode) {
  element.textContent = text;
  element.className = `badge ${mode || ""}`.trim();
}

function renderRoutines(routines) {
  els.routineList.innerHTML = "";
  for (const routine of routines) {
    const row = document.createElement("div");
    row.className = "routine-row";
    row.dataset.routineId = routine.id;
    row.innerHTML = `
      <div class="routine-title">${routine.label}</div>
      <label>
        Percentual
        <input class="routine-percentage" type="number" min="0" max="100" value="${routine.percentage}" />
      </label>
      <label class="routine-switch">
        <input class="routine-enabled" type="checkbox" ${routine.enabled ? "checked" : ""} />
        Ativa
      </label>
    `;
    els.routineList.appendChild(row);
  }
}

function renderEvents(events) {
  els.eventList.innerHTML = "";
  for (const event of events) {
    const item = document.createElement("li");
    item.className = event.status;
    item.innerHTML = `
      <time>${formatDate(event.created_at)} - ${event.kind}${event.routine ? ` / ${event.routine}` : ""}</time>
      <strong>${event.message}</strong>
    `;
    els.eventList.appendChild(item);
  }
}

function renderStatus(state) {
  currentSettings = state.settings;
  const settings = state.settings;
  const agent = state.agent;

  els.toggleButton.textContent = settings.enabled ? "Desativar" : "Ativar";
  els.toggleButton.classList.toggle("enabled", settings.enabled);
  setBadge(els.enabledBadge, settings.enabled ? "Ativa" : "Pausada", settings.enabled ? "ok" : "warn");

  setBadge(els.agentBadge, agent.online ? "Online" : "Offline", agent.online ? "ok" : "danger");
  els.agentId.textContent = agent.agent_id || "-";
  els.agentHeartbeat.textContent = formatDate(agent.last_heartbeat);
  els.agentMessage.textContent = agent.last_message || "-";
  els.intervalSummary.textContent = `${settings.min_interval_seconds}s - ${settings.max_interval_seconds}s`;
  els.targetSummary.textContent = settings.vscode_target_file || "Nao configurado";
  els.mouseSummary.textContent = `${settings.mouse_click_button} (${settings.mouse_click_x}, ${settings.mouse_click_y}) x${settings.mouse_click_count}`;
  els.commandSummary.textContent = `${state.commands.length} recentes`;
  renderEvents(state.events);
}

function renderSettingsForm(settings) {
  els.vscodeTargetFile.value = settings.vscode_target_file || "";
  els.vscodeTextLength.value = settings.vscode_text_length;
  els.mouseClickX.value = settings.mouse_click_x;
  els.mouseClickY.value = settings.mouse_click_y;
  els.mouseClickButton.value = settings.mouse_click_button || "left";
  els.mouseClickCount.value = settings.mouse_click_count;
  els.minInterval.value = settings.min_interval_seconds;
  els.maxInterval.value = settings.max_interval_seconds;
  renderRoutines(settings.routines);
}

function renderState(state, options = {}) {
  renderStatus(state);
  if (!formDirty || options.forceForm) {
    renderSettingsForm(state.settings);
  }
}

async function refresh() {
  const state = await api(stateUrl);
  renderState(state);
}

function collectSettings() {
  const routines = [...els.routineList.querySelectorAll(".routine-row")].map((row) => ({
    id: row.dataset.routineId,
    label: row.querySelector(".routine-title").textContent,
    enabled: row.querySelector(".routine-enabled").checked,
    percentage: Number(row.querySelector(".routine-percentage").value),
  }));

  return {
    ...currentSettings,
    vscode_target_file: els.vscodeTargetFile.value.trim(),
    vscode_text_length: Number(els.vscodeTextLength.value),
    mouse_click_x: Number(els.mouseClickX.value),
    mouse_click_y: Number(els.mouseClickY.value),
    mouse_click_button: els.mouseClickButton.value,
    mouse_click_count: Number(els.mouseClickCount.value),
    min_interval_seconds: Number(els.minInterval.value),
    max_interval_seconds: Number(els.maxInterval.value),
    routines,
  };
}

els.settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  els.formMessage.textContent = "Salvando...";
  els.formMessage.classList.remove("error");
  try {
    await api(settingsUrl, {
      method: "PUT",
      body: JSON.stringify(collectSettings()),
    });
    formDirty = false;
    els.formMessage.textContent = "Configuracao salva.";
    const state = await api(stateUrl);
    renderState(state, { forceForm: true });
  } catch (error) {
    els.formMessage.textContent = error.message;
    els.formMessage.classList.add("error");
  }
});

els.toggleButton.addEventListener("click", async () => {
  if (!currentSettings) return;
  els.toggleButton.disabled = true;
  try {
    await api(toggleUrl, {
      method: "POST",
      body: JSON.stringify({ enabled: !currentSettings.enabled }),
    });
    await refresh();
  } finally {
    els.toggleButton.disabled = false;
  }
});

els.refreshButton.addEventListener("click", refresh);

els.settingsForm.addEventListener("input", () => {
  formDirty = true;
});

els.settingsForm.addEventListener("change", () => {
  formDirty = true;
});

els.settingsForm.addEventListener("focusin", () => {
  formDirty = true;
});

refresh().catch((error) => {
  els.formMessage.textContent = error.message;
  els.formMessage.classList.add("error");
});

window.setInterval(() => {
  refresh().catch(() => {});
}, 5000);
