"use strict";

const $ = (id) => document.getElementById(id);
let currentRunId = new URLSearchParams(window.location.search).get("run");
let pollTimer = null;

function dl(container, rows) {
  container.replaceChildren();
  for (const [key, value] of rows) {
    container.append(el("dt", { text: key }), el("dd", {}, value instanceof Node ? value : String(value ?? "-")));
  }
}

function logBlock(title, text, open) {
  const body = text && text.trim() ? text : "(empty)";
  return el("details", { open: open || false }, el("summary", { text: title }), el("pre", { text: body }));
}

function expectedText(t) {
  const parts = [];
  if (t.expected.stdout !== null && t.expected.stdout !== undefined) parts.push(`stdout [${t.compare}]: ${t.expected.stdout}`);
  if (t.expected.exit_code !== null && t.expected.exit_code !== undefined) parts.push(`exit code: ${t.expected.exit_code}`);
  return parts.join("\n");
}

function actualText(t) {
  if (!t.actual) return "-";
  const out = (t.actual.stdout || "").trimEnd();
  const code = t.actual.exit_code === null ? "n/a" : t.actual.exit_code;
  return (out ? out + "\n" : "") + `exit code: ${code}`;
}

function renderRun(run) {
  $("empty-card").hidden = true;
  for (const id of ["run-card", "build-card", "tests-card"]) $(id).hidden = false;
  $("run-id").textContent = run.run_id;
  $("run-status").replaceChildren(badge(run.status, "big"));

  const report = $("report-link");
  if (run.report_available) {
    report.href = `/reports/${encodeURIComponent(run.run_id)}`;
    report.removeAttribute("aria-disabled");
    report.hidden = false;
  } else {
    report.hidden = true;
  }

  dl($("run-meta"), [
    ["Project", run.project_name],
    ["Test suite", run.suite || "not loaded"],
    ["Started", fmtTime(run.started_at)],
    ["Ended", fmtTime(run.ended_at)],
    ["Compiler", run.environment.compiler_version || "not recorded"],
    ["Platform", run.environment.platform],
  ]);

  const s = run.summary;
  $("tiles").replaceChildren(...[["Total", s.total], ["Passed", s.passed], ["Failed", s.failed],
    ["Errors", s.errors], ["Not run", s.not_run]].map(([label, n]) =>
    el("div", { class: "tile" }, el("b", { text: n }), el("span", { text: label }))));

  const notes = [...(run.notes || []),
    ...(run.checks || []).filter((c) => c.status === "error").map((c) => `${c.name}: ${c.message}`)];
  $("notes").replaceChildren();
  if (notes.length) {
    const kind = ["PASSED", "PASSED_WITH_SKIPS"].includes(run.status) ? "info" : "warn";
    showMessage($("notes"), kind, "Notes and diagnostics", notes);
  }

  const b = run.build;
  dl($("build-meta"), [
    ["Status", badge(b.status)],
    ["Exit code", b.exit_code === null ? "n/a" : b.exit_code],
    ["Duration", b.duration_ms === null ? "-" : `${b.duration_ms} ms`],
    ["Command", b.command ? el("code", { text: b.command.join(" ") }) : "not run"],
    ...(b.error ? [["Error", b.error]] : []),
  ]);
  const buildFailed = b.status !== "SUCCESS";
  $("build-logs").replaceChildren(
    logBlock("Compiler stdout", b.stdout, false),
    logBlock("Compiler stderr", b.stderr, buildFailed && Boolean(b.stderr)));

  const body = $("tests-body");
  body.replaceChildren();
  const logs = [];
  if (!run.tests.length) {
    body.append(el("tr", {}, el("td", { colspan: "6", class: "empty", text: "No test cases were loaded for this run." })));
  }
  for (const t of run.tests) {
    const bad = t.status === "FAIL" || t.status === "ERROR";
    const reasons = (t.reasons || []).map((r) => el("div", { class: `reason ${bad ? "" : "muted"}`, text: r }));
    body.append(el("tr", { class: bad ? "fail" : "" },
      el("td", {}, el("code", { text: t.id })),
      el("td", {}, t.description, el("div", { class: "hint", text: `${t.category || ""}  input: ${JSON.stringify(t.input)}` })),
      el("td", {}, el("pre", { text: expectedText(t) })),
      el("td", {}, el("pre", { text: actualText(t) }), reasons),
      el("td", {}, badge(t.status)),
      el("td", { text: t.duration_ms === null ? "-" : `${t.duration_ms} ms` })));
    if (t.actual) {
      logs.push(el("details", { open: bad && Boolean(t.actual.stderr) },
        el("summary", {}, `${t.id} output `, badge(t.status)),
        el("pre", { text: `--- stdout ---\n${t.actual.stdout || "(empty)"}\n--- stderr ---\n${t.actual.stderr || "(empty)"}` })));
    }
  }
  $("test-logs").replaceChildren(...(logs.length ? [el("h2", { text: "Program output per test" })] : []), ...logs);
}

async function loadHistory() {
  const res = await api("GET", "/api/runs");
  const list = $("history");
  list.replaceChildren();
  const runs = res.ok ? res.data.runs : [];
  if (!res.ok) showMessage($("page-message"), "bad", res.data.error || "Could not load run history");
  if (!runs.length) list.append(el("li", { class: "empty", text: "No runs recorded." }));
  for (const r of runs) {
    list.append(el("li", {}, el("button", {
      type: "button", "data-run": r.run_id, "aria-current": r.run_id === currentRunId ? "true" : "false",
      onclick: () => selectRun(r.run_id),
    }, el("span", { class: "when", text: fmtTime(r.started_at) }), badge(r.status))));
  }
  return runs;
}

async function selectRun(runId) {
  currentRunId = runId;
  history.replaceState(null, "", `/results?run=${encodeURIComponent(runId)}`);
  const res = await api("GET", `/api/runs/${encodeURIComponent(runId)}`);
  if (!res.ok) {
    showMessage($("page-message"), "bad", res.data.error || "Could not load the run");
    return;
  }
  showMessage($("page-message"));
  renderRun(res.data);
  document.querySelectorAll(".history button").forEach((b) => {
    b.setAttribute("aria-current", b.dataset.run === runId ? "true" : "false");
  });
}

async function poll() {
  const res = await api("GET", "/api/status");
  const box = $("progress");
  if (res.ok && res.data.running) {
    box.replaceChildren(el("span", { class: "spinner", "aria-hidden": "true" }), " ",
      `Run ${res.data.run_id} in progress: ${res.data.message}`);
    box.hidden = false;
    setButtons(true);
    pollTimer = setTimeout(poll, 700);
    return;
  }
  box.hidden = true;
  setButtons(false);
  pollTimer = null;
  if (res.ok && res.data.error) showMessage($("page-message"), "bad", res.data.error);
  await refresh(res.ok ? res.data.run_id : null);
}

function setButtons(disabled) {
  for (const id of ["rerun-btn", "first-run-btn"]) $(id).disabled = disabled;
}

async function startRun() {
  showMessage($("page-message"));
  setButtons(true);
  const res = await api("POST", "/api/run", {});
  if (!res.ok && res.status !== 409) {
    setButtons(false);
    showMessage($("page-message"), "bad", res.data.error || "Could not start the run", res.data.errors);
    return;
  }
  if (res.data.run_id) currentRunId = res.data.run_id;
  if (!pollTimer) poll();
}

async function refresh(preferId) {
  const runs = await loadHistory();
  const ids = runs.map((r) => r.run_id);
  const target = [currentRunId, preferId, ids[0]].find((id) => id && ids.includes(id));
  if (target) await selectRun(target);
  else if (!runs.length) {
    for (const id of ["run-card", "build-card", "tests-card"]) $(id).hidden = true;
    $("empty-card").hidden = false;
  }
}

$("rerun-btn").addEventListener("click", startRun);
$("first-run-btn").addEventListener("click", startRun);
poll();
