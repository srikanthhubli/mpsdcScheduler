const screens = ["overview", "verifications", "jobs", "run"];
const state = { screen: "overview", status: null, verifications: {}, jobs: {}, detail: null, message: "", token: sessionStorage.getItem("tdrToken") || "", runs: { phase2: null, phase3: null }, runTimer: 0 };

const apiBaseInput = document.querySelector("#apiBase");
const health = document.querySelector("#health");
const main = document.querySelector("#main");
const loginView = document.querySelector("#loginView");
const appView = document.querySelector("#appView");

apiBaseInput.value = localStorage.getItem("tdrApiBase") || (location.protocol.startsWith("http") ? location.origin : "http://127.0.0.1:8088");

document.querySelector("#connect").addEventListener("submit", (event) => {
  event.preventDefault();
  localStorage.setItem("tdrApiBase", apiBaseInput.value.replace(/\/$/, ""));
  refresh();
});

document.querySelector("#logout").addEventListener("click", async () => {
  try { await api("/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); } catch (_error) { /* signed out locally */ }
  state.token = "";
  sessionStorage.removeItem("tdrToken");
  showApp(false);
});

document.querySelector("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.querySelector("#loginError");
  error.hidden = true;
  const form = new FormData(event.target);
  try {
    const result = await api("/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: form.get("username"), password: form.get("password") })
    }, true);
    state.token = result.token;
    sessionStorage.setItem("tdrToken", result.token);
    showApp(true);
    refresh();
  } catch (err) {
    error.hidden = false;
    error.textContent = explain(err);
  }
});

document.querySelector("nav").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  state.screen = button.dataset.screen;
  state.detail = null;
  document.querySelectorAll("nav button").forEach((item) => item.classList.toggle("active", item === button));
  render();
});

function headers() {
  const value = { Accept: "application/json" };
  if (state.token) value.Authorization = `Bearer ${state.token}`;
  return value;
}

function showApp(signedIn) {
  loginView.hidden = signedIn;
  appView.hidden = !signedIn;
}

function baseUrl() {
  return apiBaseInput.value.replace(/\/$/, "");
}

function explain(error) {
  const message = error && error.message ? error.message : String(error);
  if (message === "Failed to fetch" || /NetworkError|ECONNREFUSED|Load failed/i.test(message)) {
    return `Cannot reach the scheduler at ${baseUrl()}. Start it with "python3 -m schedulermp serve" from the scheduler folder, then open http://127.0.0.1:8088/ . The dashboard is served by that same process.`;
  }
  return message;
}

function showNotice(message) {
  const notice = document.querySelector("#notice");
  if (!message) {
    notice.hidden = true;
    notice.textContent = "";
    return;
  }
  notice.hidden = false;
  notice.textContent = message;
}

async function api(path, options = {}, open) {
  let response;
  try {
    response = await fetch(baseUrl() + path, {
      ...options,
      headers: { ...(open ? { Accept: "application/json" } : headers()), ...(options.headers || {}) }
    });
  } catch (error) {
    throw new Error(explain(error));
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.message || body.error || response.statusText || "request failed";
    const retry = body.retryable ? " This call can be retried." : "";
    throw new Error((body.status ? `${body.status}: ${detail}` : detail) + retry);
  }
  return body;
}

function count(map, key) {
  return (map && map[key]) || 0;
}

function pill(value) {
  return `<span class="pill ${value || ""}">${value || "—"}</span>`;
}

function render() {
  if (state.runTimer && state.screen !== "run") {
    clearInterval(state.runTimer);
    state.runTimer = 0;
  }
  if (state.screen === "overview") renderOverview();
  if (state.screen === "verifications") renderVerifications();
  if (state.screen === "jobs") renderJobs();
  if (state.screen === "run") renderRun();
}

function renderOverview() {
  const verifications = state.status?.verifications || {};
  const jobs = state.status?.jobs || {};
  const rows = Object.values(state.verifications);
  const actions = actionCounts(rows);
  main.innerHTML = `
    <section class="cards">
      <article class="card"><span>DRC match</span><strong>${count(verifications, "MATCH")}</strong></article>
      <article class="card"><span>DRC mismatch</span><strong>${count(verifications, "MISMATCH")}</strong></article>
      <article class="card"><span>API failure</span><strong>${count(verifications, "API_FAILURE")}</strong></article>
      <article class="card"><span>Jobs failed</span><strong>${count(jobs, "FAILED")}</strong></article>
    </section>
    <section class="charts">
      <article class="panel">${barChart("Phase 1 results", [
        ["Match", count(verifications, "MATCH"), "ok"],
        ["Mismatch", count(verifications, "MISMATCH"), "bad"],
        ["Not found", count(verifications, "NOT_FOUND"), "bad"],
        ["API failure", count(verifications, "API_FAILURE"), "warn"]
      ])}</article>
      <article class="panel">${barChart("DRC flag on chain", [
        ["Generate", actions.generate, "ok"],
        ["Update", actions.update, "warn"],
        ["Unclassified", actions.other, ""]
      ])}</article>
    </section>
    <section class="panel">
      <h2>Phases</h2>
      <p>Phase 1 check: ${state.status?.phase1_enabled ? "on" : "off"}. Legacy daily: ${state.status?.phase2_enabled ? "on" : "off"}.</p>
      <p class="muted">Dry run: ${state.status?.dry_run ? "on" : "off"}. The legacy daily time is set on Run. Generate means FIRST_OWNER or TRANSFEREE_OWNER. Update means TRANSFER_OWNER or UTILIZATION_OWNER.</p>
      <p>${state.message ? escapeHtml(state.message) : ""}</p>
    </section>`;
}

function renderVerifications() {
  const rows = Object.values(state.verifications);
  const filter = state.verificationFilter || "";
  const visible = rows.filter((row) => !filter || `${row.certificate_no} ${row.status} ${row.application_id || ""}`.toLowerCase().includes(filter.toLowerCase()));
  main.innerHTML = `
    <div class="row">
      <label>Filter<input id="vfilter" value="${escapeAttr(filter)}" placeholder="certificate or status" /></label>
      <button type="button" id="reload" class="secondary">Reload</button>
      <button type="button" id="exportAll" class="secondary">Export all</button>
      <button type="button" id="exportChain" class="secondary">Export on chain</button>
    </div>
    <section class="panel">${barChart("This list", [
      ["Match", visible.filter((row) => row.status === "MATCH").length, "ok"],
      ["Mismatch", visible.filter((row) => row.status === "MISMATCH").length, "bad"],
      ["Not found", visible.filter((row) => row.status === "NOT_FOUND").length, "bad"],
      ["API failure", visible.filter((row) => row.status === "API_FAILURE").length, "warn"]
    ])}</section>
    <div class="table-wrap"><table>
      <thead><tr><th>Certificate</th><th>Application</th><th>Flag</th><th>Chain</th><th>Status</th><th>Message</th><th>Checked</th><th></th></tr></thead>
      <tbody>
        ${visible.map((row) => `<tr>
          <td>${escapeHtml(row.certificate_no)}</td>
          <td>${escapeHtml(row.application_id || "")}</td>
          <td>${escapeHtml(row.flg || "")}</td>
          <td>${escapeHtml(chainWord(row))}</td>
          <td>${pill(row.status)}</td>
          <td>${escapeHtml(row.message || "")}</td>
          <td>${escapeHtml(row.checked_at || "")}</td>
          <td><button type="button" class="secondary" data-cert="${escapeAttr(row.certificate_no)}">Diff</button></td>
        </tr>`).join("") || `<tr><td colspan="8">No verifications yet.</td></tr>`}
      </tbody>
    </table></div>
    <section class="panel" id="vdetail"></section>`;
  document.querySelector("#vfilter").addEventListener("change", (event) => {
    state.verificationFilter = event.target.value;
    render();
  });
  document.querySelector("#reload").addEventListener("click", refresh);
  document.querySelector("#exportAll").addEventListener("click", () => downloadVerifications(false));
  document.querySelector("#exportChain").addEventListener("click", () => downloadVerifications(true));
  main.querySelectorAll("[data-cert]").forEach((button) => {
    button.addEventListener("click", () => showVerification(button.dataset.cert));
  });
  if (state.detail) document.querySelector("#vdetail").innerHTML = `<h2>${escapeHtml(state.detail.certificate_no)}</h2><p>${escapeHtml(state.detail.message || "")}</p><pre>${escapeHtml(JSON.stringify(state.detail.diffs || [], null, 2))}</pre>`;
}

function chainWord(row) {
  const action = row.chain_action || chainAction(row.flg);
  const stored = row.on_chain || row.status === "MATCH" ? "on chain" : "not on chain";
  return action ? `${action}, ${stored}` : stored;
}

function chainAction(flg) {
  const value = String(flg || "").toUpperCase();
  if (value === "TRANSFER_OWNER" || value === "UTILIZATION_OWNER") return "update";
  if (value === "FIRST_OWNER" || value === "TRANSFEREE_OWNER") return "generate";
  return "";
}

function actionCounts(rows) {
  const counts = { generate: 0, update: 0, other: 0 };
  rows.forEach((row) => {
    if (!(row.on_chain || row.status === "MATCH")) return;
    const action = row.chain_action || chainAction(row.flg);
    if (action === "generate" || action === "update") counts[action] += 1;
    else counts.other += 1;
  });
  return counts;
}

function barChart(title, series) {
  const max = Math.max(1, ...series.map((item) => item[1]));
  const bars = series.map(([label, value, tone]) => `
    <div class="bar-row">
      <span>${escapeHtml(label)}</span>
      <span class="bar"><span class="bar-fill ${tone}" style="width:${Math.round((value / max) * 100)}%"></span></span>
      <strong>${value}</strong>
    </div>`).join("");
  return `<h2>${escapeHtml(title)}</h2><div class="bars">${bars}</div>`;
}

async function downloadVerifications(onChainOnly) {
  const response = await fetch(baseUrl() + (onChainOnly ? "/verifications.csv?onChain=1" : "/verifications.csv"), { headers: headers() });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    showNotice(body.message || body.error || "Export failed");
    return;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = onChainOnly ? "phase1-on-chain.csv" : "phase1-verifications.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function showVerification(certificate) {
  state.detail = state.verifications[certificate];
  render();
}

function renderJobs() {
  const rows = Object.values(state.jobs);
  main.innerHTML = `
    <div class="row">
      <label>Mode<select id="mode"><option>all</option><option>legacy</option><option>live</option></select></label>
      <button type="button" id="reload" class="secondary">Reload</button>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Application</th><th>Mode</th><th>Status</th><th>Stage</th><th>Error</th><th></th></tr></thead>
      <tbody id="jobbody"></tbody>
    </table></div>
    <section class="panel" id="jdetail"></section>`;
  const draw = () => {
    const mode = document.querySelector("#mode").value;
    const visible = rows.filter((row) => mode === "all" || row.mode === mode);
    document.querySelector("#jobbody").innerHTML = visible.map((row) => `<tr>
      <td>${escapeHtml(row.application_id)}</td>
      <td>${escapeHtml(row.mode)}</td>
      <td>${pill(row.status)}</td>
      <td>${escapeHtml(row.last_successful_stage || row.current_stage || "")}</td>
      <td>${escapeHtml(row.last_error || "")}</td>
      <td><button type="button" class="secondary" data-job="${escapeAttr(row.mode + ":" + row.application_id)}">Stages</button></td>
    </tr>`).join("") || `<tr><td colspan="6">No jobs yet.</td></tr>`;
    document.querySelectorAll("[data-job]").forEach((button) => {
      button.addEventListener("click", () => {
        const job = state.jobs[button.dataset.job];
        document.querySelector("#jdetail").innerHTML = `<h2>${escapeHtml(job.application_id)}</h2><pre>${escapeHtml(JSON.stringify(job.stages || {}, null, 2))}</pre>`;
      });
    });
  };
  document.querySelector("#mode").addEventListener("change", draw);
  document.querySelector("#reload").addEventListener("click", refresh);
  draw();
}

function renderRun() {
  const saved = state.schedule?.schedule || {};
  const legacy = saved.legacy || { enabled: false, start: "01:00", hours: 4, stopWhenComplete: true, message: "Loading the daily schedule." };
  main.innerHTML = `
    <section class="panel">
      <h2>Legacy records, once a day</h2>
      <p class="muted">Starts at the chosen time and keeps going only for the number of hours you set. The next day continues applications that are not on the blockchain yet. When every application has succeeded, the schedule turns off.</p>
      <form id="legacySchedule" class="grid">
        <label><input id="legacyOn" name="enabled" type="checkbox" ${legacy.enabled ? "checked" : ""} /> Enable the daily legacy run</label>
        <label>Start time<input id="legacyStart" name="start" type="time" value="${escapeAttr(legacy.start || "01:00")}" required /></label>
        <label>Hours it may run<input id="legacyHours" name="hours" type="number" min="1" max="12" value="${escapeAttr(legacy.hours || 4)}" required /></label>
        <label><input id="legacyComplete" name="stopWhenComplete" type="checkbox" ${legacy.stopWhenComplete === false ? "" : "checked"} /> Turn off when the whole list is complete</label>
        <button type="submit">Save legacy schedule</button>
      </form>
      <p id="legacyMsg">${escapeHtml(legacy.message || "")}</p>
    </section>
    <section class="panel run-live" id="live2"></section>
    <section class="panel run-live" id="live3"></section>
    <section class="panel">
      <h2>Phase 1 — DRC verification</h2>
      <form id="p1" class="grid">
        <label>Certificate<input name="certificate" placeholder="blank checks the full list" /></label>
        <label>Limit<input name="limit" type="number" min="0" value="0" /></label>
        <button type="submit">Run phase 1</button>
      </form>
    </section>
    <section class="panel">
      <h2>Phase 2 — legacy migration</h2>
      <form id="p2" class="grid">
        <label>Application id<input name="applicationId" placeholder="blank walks the application list" /></label>
        <label>Limit<input name="limit" type="number" min="0" value="0" /></label>
        <label><input name="force" type="checkbox" /> Force a completed job</label>
        <label><input name="oneShot" type="checkbox" /> Run this list once and turn the daily legacy schedule off</label>
        <button type="submit">Run phase 2</button>
      </form>
    </section>
    <section class="panel">
      <h2>Phase 3 — live sync</h2>
      <form id="p3" class="grid">
        <label>Application id<input name="applicationId" /></label>
        <label>Owner ids<input name="ownerIds" placeholder="comma separated" /></label>
        <label>Certificates<input name="certificateNos" placeholder="comma separated" /></label>
        <label><input name="force" type="checkbox" /> Force</label>
        <button type="submit">Run phase 3</button>
      </form>
    </section>
    <section class="panel"><pre id="runout">Phase 2 and phase 3 keep this screen open and list every application id. Pause and Stop take effect after the current step.</pre></section>`;
  paintRun(2, state.runs.phase2);
  paintRun(3, state.runs.phase3);
  if (!main.dataset.runBound) {
    main.addEventListener("click", onRunAction);
    main.dataset.runBound = "1";
  }
  document.querySelector("#p1").addEventListener("submit", (event) => submitRun(event, "/run/phase1"));
  document.querySelector("#p2").addEventListener("submit", (event) => submitRun(event, "/run/phase2"));
  document.querySelector("#p3").addEventListener("submit", (event) => submitRun(event, "/run/phase3", true));
  document.querySelector("#legacySchedule").addEventListener("submit", saveLegacySchedule);
  if (!state.runTimer) {
    state.runTimer = setInterval(pollRuns, 1000);
    pollRuns();
  }
}

function onRunAction(event) {
  const button = event.target.closest("[data-run]");
  if (!button || button.disabled) return;
  api(`/runs/phase${button.dataset.phase}/${button.dataset.run}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
    .then(pollRuns)
    .catch((error) => showNotice(explain(error)));
}

async function saveLegacySchedule(event) {
  event.preventDefault();
  try {
    state.schedule = await api("/schedule", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        legacy: {
          enabled: document.querySelector("#legacyOn").checked,
          start: document.querySelector("#legacyStart").value,
          hours: Number(document.querySelector("#legacyHours").value),
          stopWhenComplete: document.querySelector("#legacyComplete").checked
        }
      })
    });
    paintSchedule();
  } catch (error) {
    showNotice(explain(error));
  }
}

function paintSchedule() {
  const saved = state.schedule?.schedule;
  if (!saved) return;
  const form = document.querySelector("#legacySchedule");
  if (form && !form.dataset.filled) {
    document.querySelector("#legacyOn").checked = !!saved.legacy.enabled;
    document.querySelector("#legacyStart").value = saved.legacy.start || "01:00";
    document.querySelector("#legacyHours").value = saved.legacy.hours || 4;
    document.querySelector("#legacyComplete").checked = saved.legacy.stopWhenComplete !== false;
    form.dataset.filled = "1";
  }
  const legacyMsg = document.querySelector("#legacyMsg");
  if (legacyMsg) legacyMsg.textContent = saved.legacy?.message || "";
}

async function pollRuns() {
  if (state.screen !== "run") return;
  try {
    const body = await api("/runs");
    state.runs = body.runs || state.runs;
    paintRun(2, state.runs.phase2);
    paintRun(3, state.runs.phase3);
    state.schedule = await api("/schedule");
    paintSchedule();
  } catch (error) {
    const message = explain(error);
    showNotice(message);
    if (/Login required/i.test(message)) {
      state.token = "";
      sessionStorage.removeItem("tdrToken");
      showApp(false);
    }
  }
}

function paintRun(phase, run) {
  const root = document.querySelector(`#live${phase}`);
  if (!root) return;
  const data = run || { status: "IDLE", message: "No run yet", items: [], log: [], counts: {}, total: 0, index: 0, current: "", stage: "", detail: "" };
  const scroll = root.querySelector(".run-list")?.scrollTop || 0;
  const active = ["EXTRACTING", "RUNNING", "PAUSED", "STOPPING"].includes(data.status);
  const counts = data.counts || {};
  const title = phase === 2 ? "Phase 2 — legacy migration" : "Phase 3 — live sync";
  const progress = data.total ? `${data.index || 0} of ${data.total}` : "0 extracted";
  const summary = data.total
    ? `${counts.SUCCESS || 0} succeeded · ${counts.FAILED || 0} failed · ${counts.SKIPPED || 0} skipped · ${counts.STOPPED || 0} stopped · ${counts.PENDING || 0} waiting · ${counts.NOT_STARTED || 0} not started`
    : "";
  const items = (data.items || []).map((item) => `<li>
      <span>${escapeHtml(item.applicationId)}</span>
      <span>${pill(item.status)}</span>
      <span>${escapeHtml(stageLabel(item.stage))} ${escapeHtml(item.message || "")}</span>
    </li>`).join("") || `<li><span>No application ids yet.</span></li>`;
  const log = (data.log || []).slice(-12).map((line) => `<div>${escapeHtml(line)}</div>`).join("");
  root.innerHTML = `
    <div class="run-head">
      <div>
        <h2>${title}</h2>
        <p class="run-current">${pill(data.status)} ${escapeHtml(progress)}${data.current ? ` · ${escapeHtml(data.current)}` : ""}</p>
        <p>${escapeHtml(data.message || "")}</p>
        <p class="muted">${escapeHtml(summary)}</p>
      </div>
      <div class="run-actions">
        <button type="button" class="secondary" data-phase="${phase}" data-run="pause" ${active && data.status !== "PAUSED" && data.status !== "STOPPING" ? "" : "disabled"}>Pause</button>
        <button type="button" class="secondary" data-phase="${phase}" data-run="resume" ${data.status === "PAUSED" ? "" : "disabled"}>Resume</button>
        <button type="button" class="secondary" data-phase="${phase}" data-run="stop" ${active ? "" : "disabled"}>Stop</button>
      </div>
    </div>
    <ol class="run-list">${items}</ol>
    <div class="run-log">${log}</div>`;
  const list = root.querySelector(".run-list");
  if (list) list.scrollTop = scroll;
}

function stageLabel(stage) {
  return {
    LOAD: "Reading TDR",
    GENERATING_AREA: "Generating area",
    OWNER_DETAIL: "Owners",
    DRC_UPLOAD: "DRC upload",
    TRANSFER: "Transfer"
  }[stage] || stage || "";
}

async function submitRun(event, path, splitLists) {
  event.preventDefault();
  const form = new FormData(event.target);
  const body = Object.fromEntries(form.entries());
  body.limit = Number(body.limit || 0);
  body.force = event.target.force?.checked || false;
  body.oneShot = event.target.oneShot?.checked || false;
  if (splitLists) {
    body.ownerIds = split(body.ownerIds);
    body.certificateNos = split(body.certificateNos);
  }
  const out = document.querySelector("#runout");
  const phase23 = path.endsWith("phase2") || path.endsWith("phase3");
  out.textContent = phase23 ? "Started. The list above fills as application ids are extracted." : "Running…";
  try {
    const result = await api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (phase23) {
      out.textContent = result.run?.message || `Finished ${result.count || 0} application(s)`;
      await pollRuns();
      return;
    }
    out.textContent = JSON.stringify(result.summary || { count: result.count, jobs: (result.jobs || []).map((job) => ({ application_id: job.application_id, status: job.status, last_error: job.last_error })) }, null, 2);
    await refresh();
    state.screen = "verifications";
    document.querySelectorAll("nav button").forEach((item) => item.classList.toggle("active", item.dataset.screen === state.screen));
    render();
  } catch (error) {
    const message = explain(error);
    out.textContent = message;
    showNotice(message);
  }
}

function split(value) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[char]));
}
function escapeAttr(value) { return escapeHtml(value); }

async function refresh() {
  try {
    await api("/health");
    health.textContent = "online";
    health.className = "pill ok";
    state.status = await api("/status");
    state.verifications = (await api("/verifications")).verifications || {};
    state.jobs = (await api("/jobs")).jobs || {};
    state.message = "";
    showNotice("");
  } catch (error) {
    health.textContent = "offline";
    health.className = "pill bad";
    state.message = explain(error);
    showNotice(state.message);
    if (/Login required|Invalid username or password/i.test(state.message)) {
      state.token = "";
      sessionStorage.removeItem("tdrToken");
      showApp(false);
    }
  }
  render();
}

if (state.token) {
  showApp(true);
  refresh();
} else {
  showApp(false);
}
