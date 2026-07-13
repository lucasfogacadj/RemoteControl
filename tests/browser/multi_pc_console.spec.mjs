import { expect, test } from "@playwright/test";

const BASE_URL = "http://127.0.0.1:8768";
const AGENT_A = "e2e-agent-a";
const AGENT_B = "e2e-agent-b";
const XSS_NAME = '<img src=x onerror="window.__xssExecuted=true">';

async function onboardAgent(page, agentId, name) {
  await page.evaluate(
    ({ agentId, name }) => new Promise((resolve, reject) => {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(
        `${protocol}://${location.host}/ws/agent?token=playwright-token&agent_id=${encodeURIComponent(agentId)}`,
      );
      const timer = window.setTimeout(() => {
        socket.close();
        reject(new Error(`Timeout onboarding ${agentId}`));
      }, 5_000);
      socket.addEventListener("open", () => {
        socket.send(JSON.stringify({
          type: "hello",
          agent_id: agentId,
          name,
          version: "e2e-1",
          protocol: "2",
          dry_run: true,
          capabilities: ["open_gmail", "mouse_move"],
          execution_idle: true,
        }));
      });
      socket.addEventListener("message", (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "hello_ack") {
          window.clearTimeout(timer);
          socket.close();
          resolve();
        }
      });
      socket.addEventListener("error", () => {
        window.clearTimeout(timer);
        reject(new Error(`WebSocket onboarding failed for ${agentId}`));
      });
    }),
    { agentId, name },
  );
}

async function selectAgent(page, agentId) {
  const row = page.locator(`[data-agent-id="${agentId}"]`);
  await expect(row).toBeVisible();
  await row.click();
  await expect(page.locator("#agentId")).toHaveText(agentId);
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage();
  await page.goto(BASE_URL);
  await onboardAgent(page, AGENT_A, "E2E Agent A");
  await onboardAgent(page, AGENT_B, XSS_NAME);
  await expect.poll(async () => {
    const response = await page.request.get(`${BASE_URL}/api/fleet/state`);
    const payload = await response.json();
    return payload.agents.map((agent) => agent.agent_id);
  }).toEqual(expect.arrayContaining([AGENT_A, AGENT_B]));
  await page.close();
});

test("renders untrusted agent data as text and persists selection", async ({ page }) => {
  await page.goto("/");
  await selectAgent(page, AGENT_B);
  await expect(page.locator("#selectedTitle")).toHaveText(XSS_NAME);
  await expect(page.locator("#agentList img, #selectedTitle img")).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => window.__xssExecuted)).toBeUndefined();

  await page.reload();
  await expect(page.locator("#agentId")).toHaveText(AGENT_B);
  await expect(page.locator(`[data-agent-id="${AGENT_B}"]`)).toHaveAttribute("aria-selected", "true");
});

test("blocks silent PC changes while settings are dirty", async ({ page }) => {
  await page.goto("/");
  await selectAgent(page, AGENT_A);
  await page.locator("#vscodeTargetFile").fill("C:\\Temp\\local-edit.txt");

  await page.locator(`[data-agent-id="${AGENT_B}"]`).click();
  await expect(page.locator("#dirtySelectionDialog")).toBeVisible();
  await expect(page.locator("#dirtySelectionAgent")).toHaveText(XSS_NAME);
  await page.locator("#dirtySelectionCancelButton").click();
  await expect(page.locator("#agentId")).toHaveText(AGENT_A);
  await expect(page.locator("#vscodeTargetFile")).toHaveValue("C:\\Temp\\local-edit.txt");

  await page.locator(`[data-agent-id="${AGENT_B}"]`).click();
  await page.locator("#dirtySelectionDiscardButton").click();
  await expect(page.locator("#agentId")).toHaveText(AGENT_B);
});

test("preserves the original ETag while dirty and reports a lost update", async ({ page, request }) => {
  await page.goto("/");
  await selectAgent(page, AGENT_A);
  const original = await (await request.get(`/api/agents/${AGENT_A}/state`)).json();
  await page.locator("#vscodeTargetFile").fill("C:\\Temp\\stale-local-edit.txt");

  const externalLength = original.settings.vscode_text_length === 111 ? 112 : 111;
  const external = { ...original.settings, vscode_text_length: externalLength };
  const externalResponse = await request.put(`/api/agents/${AGENT_A}/settings`, {
    headers: { "If-Match": `"${original.settings_revision}"` },
    data: external,
  });
  expect(externalResponse.ok()).toBeTruthy();

  await page.locator("#refreshButton").click();
  await expect(page.locator("#detailMessage")).toContainText("não foi recarregado");
  await expect(page.locator("#vscodeTargetFile")).toHaveValue("C:\\Temp\\stale-local-edit.txt");
  await page.locator("#saveButton").click();
  await expect(page.locator("#formMessage")).toContainText("mudou no servidor");

  const serverState = await (await request.get(`/api/agents/${AGENT_A}/state`)).json();
  expect(serverState.settings.vscode_text_length).toBe(externalLength);
  expect(serverState.settings.vscode_target_file).not.toBe("C:\\Temp\\stale-local-edit.txt");
});

test("toggles fleet and PC independently and exposes cancellation", async ({ page, request }) => {
  await page.goto("/");
  await selectAgent(page, AGENT_B);
  const initialAgent = await (await request.get(`/api/agents/${AGENT_B}/state`)).json();
  const initialFleet = await (await request.get("/api/fleet/state")).json();

  await page.locator("#agentToggleButton").click();
  await expect(page.locator("#agentToggleButton")).toHaveAttribute(
    "aria-pressed",
    String(!initialAgent.settings.enabled),
  );
  await page.locator("#cancelButton").click();
  await expect(page.locator("#cancelButton")).toBeEnabled();
  await page.locator("#agentToggleButton").click();
  await expect(page.locator("#agentToggleButton")).toHaveAttribute(
    "aria-pressed",
    String(initialAgent.settings.enabled),
  );

  await page.locator("#fleetToggleButton").click();
  await expect(page.locator("#fleetToggleButton")).toHaveAttribute(
    "aria-pressed",
    String(!initialFleet.fleet.enabled),
  );
  await page.locator("#fleetToggleButton").click();
  await expect(page.locator("#fleetToggleButton")).toHaveAttribute(
    "aria-pressed",
    String(initialFleet.fleet.enabled),
  );
});

test("shows an API error and recovers through the visible refresh action", async ({ page }) => {
  await page.route("**/api/fleet/state", (route) => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: "E2E fleet unavailable" }),
  }));
  await page.goto("/");
  await expect(page.locator("#fleetMessage")).toContainText("E2E fleet unavailable");
  await page.unroute("**/api/fleet/state");
  await page.locator("#refreshButton").click();
  await expect(page.locator("#fleetCount")).not.toHaveText("-");
  await expect(page.locator("#fleetMessage")).toHaveText("");
});

test("suspends polling while hidden and resumes when visible", async ({ page }) => {
  let fleetRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/fleet/state") fleetRequests += 1;
  });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const requestsWhenHidden = fleetRequests;
  await page.waitForTimeout(5_500);
  expect(fleetRequests).toBe(requestsWhenHidden);

  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => fleetRequests).toBeGreaterThan(requestsWhenHidden);
});

for (const viewport of [
  { width: 375, height: 812, label: "mobile" },
  { width: 768, height: 1024, label: "tablet" },
  { width: 1440, height: 900, label: "desktop" },
]) {
  test(`fits ${viewport.label} viewport without horizontal overflow`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/");
    await expect(page.locator("#fleetToggleButton")).toBeVisible();
    await expect(page.locator("#refreshButton")).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    for (const selector of ["#fleetToggleButton", "#refreshButton", "#agentToggleButton", "#cancelButton"]) {
      const box = await page.locator(selector).boundingBox();
      expect(box?.height || 0).toBeGreaterThanOrEqual(44);
    }
    await page.screenshot({ path: testInfo.outputPath(`viewport-${viewport.width}.png`), fullPage: true });
  });
}
