const screens = ["overview", "verifications", "jobs", "run"];
const state = { screen: "overview", status: null, verifications: {}, jobs: {}, detail: null, message: "", token: sessionStorage.getItem("tdrToken") || "", runs: { phase1: null, phase2: null, phase3: null }, runTimer: 0, seenRuns: {}, jobMode: "all" };

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
  if (signedIn) ensureRunTimer();
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
      <thead><tr><th>Certificate</th><th>Application</th><th>Flag</th><th>Chain</th><th>Status</th><th>Mismatch</th><th>Checked</th><th></th></tr></thead>
      <tbody>
        ${visible.map((row) => `<tr class="${problemClass(row.status)}">
          <td>${escapeHtml(row.certificate_no)}</td>
          <td>${escapeHtml(row.application_id || "")}</td>
          <td>${escapeHtml(row.flg || "")}</td>
          <td>${escapeHtml(chainWord(row))}</td>
          <td>${pill(row.status)}</td>
          <td class="${problemClass(row.status)}">${verificationReport(row)}</td>
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
  document.querySelector("#reload").addEventListener("click", (event) => {
    event.preventDefault();
    refresh();
  });
  document.querySelector("#exportAll").addEventListener("click", (event) => {
    event.preventDefault();
    downloadVerifications(false);
  });
  document.querySelector("#exportChain").addEventListener("click", (event) => {
    event.preventDefault();
    downloadVerifications(true);
  });
  main.querySelectorAll("[data-cert]").forEach((button) => {
    button.addEventListener("click", () => showVerification(button.dataset.cert));
  });
  if (state.detail) document.querySelector("#vdetail").innerHTML = `<h2>${escapeHtml(state.detail.certificate_no)} ${pill(state.detail.status)}</h2><p>${escapeHtml(state.detail.message || "")}</p>${verificationReport(state.detail)}`;
}

function failedStage(row) {
  const stages = row.stages || {};
  for (const name of ["LOAD", "GENERATING_AREA", "OWNER_DETAIL", "DRC_UPLOAD", "TRANSFER"]) {
    const stage = stages[name];
    if (stage && ["MISMATCH", "FAILED", "API_FAILURE"].includes(stage.status)) return name;
  }
  return row.current_stage || row.last_successful_stage || "";
}

function problemClass(status) {
  return ["MISMATCH", "FAILED", "API_FAILURE"].includes(status) ? "problem" : "";
}

function mismatchDiffs(row) {
  const found = [];
  Object.values(row.stages || {}).forEach((stage) => {
    if (stage && stage.status === "MISMATCH" && Array.isArray(stage.diffs)) found.push(...stage.diffs);
  });
  return found;
}

function receivedCell(diff, side) {
  const receivedKey = side === "tdr" ? "tdr_received" : "blockchain_received";
  const fallbackKey = side === "tdr" ? "tdr" : "blockchain";
  const fieldKey = side === "tdr" ? "tdr_field" : "blockchain_field";
  const raw = Object.prototype.hasOwnProperty.call(diff, receivedKey) ? diff[receivedKey] : diff[fallbackKey];
  const shown = raw === undefined || raw === null || raw === "" ? "blank" : String(raw);
  const field = diff[fieldKey] ? `<div class="diff-key">${escapeHtml(diff[fieldKey])}</div>` : "";
  return `<td>${field}${escapeHtml(shown)}</td>`;
}

function verificationReport(row) {
  if (Array.isArray(row.records) && row.records.length) return phase1Table(row);
  return `${escapeHtml(row.message || "")}${diffTable(row.diffs || [])}`;
}

function phase1Table(row) {
  const records = row.records || [];
  const body = records.map((record) => {
    const diffs = Array.isArray(record.diffs) ? record.diffs : [];
    if (!diffs.length) {
      return `<tr class="${problemClass(record.status)}">
        <td>${escapeHtml(record.kind || "")}</td>
        <td>${escapeHtml(record.label || "")}</td>
        <td>${pill(record.status)}</td>
        <td colspan="5">${escapeHtml(record.message || "")}</td>
      </tr>`;
    }
    return diffs.map((diff) => `<tr class="${problemClass(record.status)}">
        <td>${escapeHtml(record.kind || "")}</td>
        <td>${escapeHtml(record.label || "")}</td>
        <td>${pill(record.status)}</td>
        <td>${escapeHtml(diff.field || "")}</td>
        ${receivedCell(diff, "tdr")}
        <td>${escapeHtml(diff.tdr_api || record.tdr_api || "")}</td>
        ${receivedCell(diff, "blockchain")}
        <td>${escapeHtml(diff.blockchain_api || record.blockchain_api || "")}</td>
      </tr>`).join("");
  }).join("");
  return `<div class="table-wrap"><table class="diff-table"><thead><tr>
      <th>Record</th><th>Id</th><th>Status</th><th>Field</th>
      <th>Received from TDR</th><th>TDR API</th>
      <th>Received from blockchain</th><th>Blockchain API</th>
    </tr></thead><tbody>${body}</tbody></table></div>`;
}

function itemRecords(item) {
  if (Array.isArray(item.records) && item.records.length) return item.records;
  const saved = state.verifications[item.applicationId];
  if (saved && Array.isArray(saved.records) && saved.records.length) return saved.records;
  if (saved && Array.isArray(saved.diffs) && saved.diffs.length) {
    return [{
      kind: "DRC",
      label: saved.certificate_no || item.applicationId,
      status: saved.status || item.status,
      message: "",
      diffs: saved.diffs,
      tdr_api: saved.tdr_api || "",
      blockchain_api: saved.blockchain_api || "",
    }];
  }
  return [];
}

function runSummary(item) {
  const records = itemRecords(item);
  if (!records.length) return runLine(item);
  const differed = records.filter((record) => ["MISMATCH", "FAILED", "API_FAILURE", "NOT_FOUND"].includes(record.status));
  if (!differed.length) return `${records.length} record(s) match`;
  return `${differed.length} of ${records.length} record(s) differ`;
}

function diffTable(diffs) {
  if (!diffs || !diffs.length) return "";
  return `<table class="diff-table"><thead><tr><th>Field</th><th>Received from TDR</th><th>TDR API</th><th>Received from blockchain</th><th>Blockchain API</th></tr></thead><tbody>${diffs.map((diff) => `<tr class="mismatch">
      <td>${escapeHtml(diff.field)}</td>
      ${receivedCell(diff, "tdr")}
      <td>${escapeHtml(diff.tdr_api || "")}</td>
      ${receivedCell(diff, "blockchain")}
      <td>${escapeHtml(diff.blockchain_api || "")}</td>
    </tr>`).join("")}</tbody></table>`;
}

function stageReport(job) {
  const stages = job.stages || {};
  const blocks = Object.entries(stages).map(([name, stage]) => {
    const table = diffTable(Array.isArray(stage.diffs) ? stage.diffs : []);
    return `<section class="stage-block ${problemClass(stage.status)}">
      <h3>${escapeHtml(name)} ${pill(stage.status)}</h3>
      <p>${escapeHtml(stage.message || "")}</p>
      ${table}
    </section>`;
  }).join("");
  return blocks || "<p>No stage detail stored.</p>";
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
  const button = document.querySelector(onChainOnly ? "#exportChain" : "#exportAll");
  if (button) button.disabled = true;
  try {
    const response = await fetch(baseUrl() + (onChainOnly ? "/verifications.csv?onChain=1" : "/verifications.csv"), { headers: headers(), cache: "no-store" });
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
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showNotice(onChainOnly ? "On-chain export downloaded." : "Verification export downloaded.");
  } catch (error) {
    showNotice(explain(error));
  } finally {
    if (button) button.disabled = false;
  }
}

function showVerification(certificate) {
  state.detail = state.verifications[certificate];
  render();
}

function renderJobs() {
  const rows = Object.values(state.jobs);
  main.innerHTML = `
    <div class="row">
      <label>Mode<select id="mode">
        <option value="all" ${state.jobMode === "all" ? "selected" : ""}>all</option>
        <option value="legacy" ${state.jobMode === "legacy" ? "selected" : ""}>legacy</option>
        <option value="live" ${state.jobMode === "live" ? "selected" : ""}>live</option>
      </select></label>
      <button type="button" id="reload" class="secondary">Reload</button>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Application</th><th>Mode</th><th>Status</th><th>Stage</th><th>Mismatch</th><th></th></tr></thead>
      <tbody id="jobbody"></tbody>
    </table></div>
    <section class="panel" id="jdetail"></section>`;
  const draw = () => {
    const mode = document.querySelector("#mode").value;
    state.jobMode = mode;
    const visible = rows.filter((row) => mode === "all" || row.mode === mode);
    document.querySelector("#jobbody").innerHTML = visible.map((row) => `<tr>
      <td>${escapeHtml(row.application_id)}</td>
      <td>${escapeHtml(row.mode)}</td>
      <td>${pill(row.status)}</td>
      <td>${escapeHtml(failedStage(row))}</td>
      <td class="${problemClass(row.status)}">${escapeHtml(row.last_error || "")}${diffTable(mismatchDiffs(row))}</td>
      <td><button type="button" class="secondary" data-job="${escapeAttr(row.mode + ":" + row.application_id)}">Stages</button></td>
    </tr>`).join("") || `<tr><td colspan="6">No jobs yet.</td></tr>`;
    document.querySelectorAll("[data-job]").forEach((button) => {
      button.addEventListener("click", () => {
        const job = state.jobs[button.dataset.job];
        document.querySelector("#jdetail").innerHTML = `<h2>${escapeHtml(job.application_id)}</h2>${stageReport(job)}`;
      });
    });
  };
  document.querySelector("#mode").addEventListener("change", draw);
  document.querySelector("#reload").addEventListener("click", (event) => {
    event.preventDefault();
    refresh();
  });
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
    <section class="panel run-live" id="live1"></section>
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
    <section class="panel"><pre id="runout">Each phase lists its records here while it runs. Pause, Resume, and Stop stay available. A phase returns as soon as it has started, and the completion line appears here when it ends.</pre></section>`;
  paintRun(1, state.runs.phase1);
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
  ensureRunTimer();
  pollRuns();
}

function ensureRunTimer() {
  if (state.runTimer) return;
  state.runTimer = setInterval(pollRuns, 2000);
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
  if (!state.token) return;
  try {
    const body = await api("/runs");
    const runs = body.runs || {};
    noteTransitions(runs);
    state.runs = runs;
    if (state.screen === "run") {
      const phase1Items = (runs.phase1 && runs.phase1.items) || [];
      if (phase1Items.some((item) => item.status && item.status !== "PENDING" && item.status !== "RUNNING")) {
        try {
          state.verifications = (await api("/verifications")).verifications || {};
        } catch (_error) {
          /* the run row still paints from /runs */
        }
      }
      paintRun(1, runs.phase1);
      paintRun(2, runs.phase2);
      paintRun(3, runs.phase3);
    }
  } catch (error) {
    const message = explain(error);
    if (/Login required/i.test(message)) {
      state.token = "";
      sessionStorage.removeItem("tdrToken");
      showApp(false);
      return;
    }
    if (state.screen === "run") showNotice(message);
  }
}

function noteTransitions(runs) {
  [1, 2, 3].forEach((phase) => {
    const data = runs[`phase${phase}`] || {};
    const key = `${data.status}|${data.finishedAt || ""}|${data.message || ""}`;
    const previous = state.seenRuns[phase];
    state.seenRuns[phase] = key;
    if (!previous || previous === key) return;
    if (!["COMPLETED", "STOPPED", "FAILED"].includes(data.status)) return;
    const text = data.message || `Phase ${phase} ${data.status}`;
    showNotice(text);
    const out = document.querySelector("#runout");
    if (out) out.textContent = text;
    refreshData();
  });
}

async function refreshData() {
  try {
    state.status = await api("/status");
    state.verifications = (await api("/verifications")).verifications || {};
    state.jobs = (await api("/jobs")).jobs || {};
    if (state.screen !== "run") render();
  } catch (_error) {
    /* the run notice already explains the outcome */
  }
}

function paintRun(phase, run) {
  const root = document.querySelector(`#live${phase}`);
  if (!root) return;
  const data = run || { status: "IDLE", message: "No run yet", items: [], log: [], counts: {}, total: 0, index: 0, current: "", stage: "", detail: "" };
  if (!root.dataset.ready) {
    const title = phase === 1 ? "Phase 1 progress" : phase === 2 ? "Phase 2 progress" : "Phase 3 progress";
    root.innerHTML = `
      <div class="run-head">
        <div>
          <h2>${title}</h2>
          <p class="run-current"></p>
          <p class="run-message"></p>
          <p class="muted run-summary"></p>
        </div>
        <div class="run-actions">
          <button type="button" class="secondary" data-phase="${phase}" data-run="pause">Pause</button>
          <button type="button" class="secondary" data-phase="${phase}" data-run="resume">Resume</button>
          <button type="button" class="secondary" data-phase="${phase}" data-run="stop">Stop</button>
        </div>
      </div>
      <ol class="run-list"></ol>
      <div class="run-detail"></div>
      <div class="run-log"></div>`;
    root.dataset.ready = "1";
  }
  const active = ["EXTRACTING", "RUNNING", "PAUSED", "STOPPING"].includes(data.status);
  const counts = data.counts || {};
  const noun = phase === 1 ? "certificate" : "application";
  const progress = data.total ? `${data.index || 0} of ${data.total}` : `0 ${noun}s`;
  const summary = data.total
    ? `${counts.SUCCESS || 0} succeeded · ${counts.MATCH || 0} match · ${counts.MISMATCH || 0} mismatch · ${counts.FAILED || 0} failed · ${counts.API_FAILURE || 0} api failure · ${counts.NOT_FOUND || 0} not found · ${counts.SKIPPED || 0} skipped · ${counts.STOPPED || 0} stopped · ${counts.PENDING || 0} waiting · ${counts.NOT_STARTED || 0} not started`
    : "Nothing running.";
  root.querySelector(".run-current").innerHTML = `${pill(data.status)} ${escapeHtml(progress)}${data.current ? ` · ${escapeHtml(data.current)}` : ""}`;
  root.querySelector(".run-message").textContent = data.message || "";
  root.querySelector(".run-summary").textContent = summary;
  root.querySelector('[data-run="pause"]').disabled = !(active && data.status !== "PAUSED" && data.status !== "STOPPING");
  root.querySelector('[data-run="resume"]').disabled = data.status !== "PAUSED";
  root.querySelector('[data-run="stop"]').disabled = !active;
  const form = document.querySelector(`#p${phase}`);
  const submit = form ? form.querySelector("button[type=submit]") : null;
  if (submit) submit.disabled = active;
  const list = root.querySelector(".run-list");
  const atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 8;
  list.innerHTML = (data.items || []).map((item) => `<li class="${problemClass(item.status)}">
      <div class="run-row">
        <span>${escapeHtml(item.applicationId)}</span>
        <span>${pill(item.status)}</span>
        <span>${escapeHtml(runSummary(item))}</span>
      </div>
    </li>`).join("") || `<li><span>No ${noun}s yet.</span></li>`;
  if (atBottom) list.scrollTop = list.scrollHeight;
  const detail = root.querySelector(".run-detail");
  if (detail) detail.innerHTML = runDetail(data.items || []);
  root.querySelector(".run-log").textContent = (data.log || []).slice(-40).join("\n");
}

function runDetail(items) {
  const blocks = items.map((item) => {
    const records = itemRecords(item);
    if (!records.length) return "";
    return `<section class="stage-block ${problemClass(item.status)}">
      <h3>${escapeHtml(item.applicationId)} ${pill(item.status)}</h3>
      ${phase1Table({ records })}
    </section>`;
  }).join("");
  return blocks;
}

function runLine(item) {
  const label = stageLabel(item.stage);
  const message = item.message || "";
  if (!label) return message;
  if (message.toLowerCase().startsWith(label.toLowerCase())) return message;
  return `${label} ${message}`.trim();
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
  body.background = true;
  if (splitLists) {
    body.ownerIds = split(body.ownerIds);
    body.certificateNos = split(body.certificateNos);
  }
  const out = document.querySelector("#runout");
  const submit = event.target.querySelector("button[type=submit]");
  if (submit) submit.disabled = true;
  out.textContent = "Started. The progress panel above lists each record. Pause, Resume, and Stop stay usable.";
  try {
    const result = await api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    out.textContent = result.message || "Started.";
    showNotice(result.message || "Phase started.");
    await pollRuns();
  } catch (error) {
    const message = explain(error);
    out.textContent = message;
    showNotice(message);
    if (submit) submit.disabled = false;
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
