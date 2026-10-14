"use strict";

const form = document.getElementById("config-form");
const message = document.getElementById("form-message");
const saveState = document.getElementById("save-state");
const checksList = document.getElementById("checks");
const adapterSelect = document.getElementById("adapter");
const adapterHint = document.getElementById("adapter-hint");
const buttons = ["save-btn", "validate-btn", "run-btn", "reset-btn"].map((id) => document.getElementById(id));

const FIELDS = {
  executable: { label: "Compiler executable", required: true },
  args: { label: "Compiler flags" },
  compile_timeout: { label: "Compile timeout", min: 1, max: 3600 },
  source_dir: { label: "Source directory", required: true },
  source_file: { label: "Source file", required: true },
  build_dir: { label: "Build directory", required: true },
  report_dir: { label: "Report directory", required: true },
  tests_file: { label: "Test cases file", required: true },
  test_timeout: { label: "Default test timeout", min: 1, max: 3600 },
  max_output: { label: "Max captured output", min: 1024, max: 10485760 },
  project_name: { label: "Project name", required: true },
};

let saved = null;      // last saved payload from the server
let adapters = {};
let dirty = false;

function input(name) { return form.elements.namedItem(name); }

function fill(payload) {
  const c = payload.config;
  adapters = payload.adapters || adapters;
  adapterSelect.replaceChildren(...Object.keys(adapters).map((name) => el("option", { value: name, text: name })));
  adapterSelect.value = c.compiler.adapter;
  input("executable").value = c.compiler.executable;
  input("args").value = payload.args_text;
  input("compile_timeout").value = c.compiler.timeout_seconds;
  for (const key of ["source_dir", "source_file", "build_dir", "report_dir", "tests_file"]) input(key).value = c.paths[key];
  input("test_timeout").value = c.run.default_test_timeout_seconds;
  input("max_output").value = c.run.max_output_bytes;
  input("project_name").value = c.project_name;
  document.getElementById("config-file").textContent = payload.config_file;
  document.getElementById("command-preview").textContent =
    payload.command_preview ? payload.command_preview.map(quoteArg).join(" ") : "(paths invalid - no preview)";
  updateAdapterHint();
  for (const name of Object.keys(FIELDS)) input(name).removeAttribute("aria-invalid");
  setDirty(false);
}

function quoteArg(arg) {
  return /^[\w@%+=:,./-]+$/.test(arg) ? arg : `'${arg.replaceAll("'", "'\\''")}'`;
}

function updateAdapterHint() {
  adapterHint.textContent = adapters[adapterSelect.value] || "";
}

function setDirty(value) {
  dirty = value;
  saveState.replaceChildren();
  if (!saved) return;
  if (dirty) {
    saveState.append(el("span", { class: "dirty", text: "Unsaved changes. " }),
      "Save before running tests; runs always use the saved configuration.");
  } else {
    saveState.append("Showing the saved configuration from ", el("b", { text: saved.config_file }), ".");
  }
}

function collect() {
  return {
    project_name: input("project_name").value,
    compiler: {
      adapter: adapterSelect.value,
      executable: input("executable").value,
      args_text: input("args").value,
      timeout_seconds: input("compile_timeout").value,
    },
    paths: Object.fromEntries(["source_dir", "source_file", "build_dir", "report_dir", "tests_file"]
      .map((k) => [k, input(k).value])),
    run: {
      default_test_timeout_seconds: input("test_timeout").value,
      max_output_bytes: input("max_output").value,
    },
  };
}

// Client-side checks for quick feedback; the server validates everything again.
function clientValidate() {
  const errors = [];
  for (const [name, rule] of Object.entries(FIELDS)) {
    const field = input(name);
    const value = field.value.trim();
    let error = null;
    if (rule.required && !value) error = `${rule.label} is required`;
    if (rule.min !== undefined) {
      const n = Number(value);
      if (!value || !Number.isInteger(n) || n < rule.min || n > rule.max) {
        error = `${rule.label} must be a whole number between ${rule.min} and ${rule.max}`;
      }
    }
    field.setAttribute("aria-invalid", error ? "true" : "false");
    if (error) errors.push(error);
  }
  return errors;
}

function renderChecks(checks) {
  checksList.replaceChildren();
  if (!checks || !checks.length) {
    checksList.append(el("li", { class: "empty", text: "Not validated yet." }));
    return;
  }
  for (const c of checks) {
    checksList.append(el("li", {},
      el("span", {}, badge(c.status, "", c.status === "warning" ? "WARN" : c.status.toUpperCase())),
      el("div", {}, el("div", { class: "name", text: c.name }), el("div", { class: "detail", text: c.message }))));
  }
}

function busy(on) { buttons.forEach((b) => { b.disabled = on; }); }

async function load() {
  const res = await api("GET", "/api/config");
  if (!res.ok) {
    showMessage(message, "bad", res.data.error || "Could not load configuration", res.data.errors);
    saveState.textContent = "";
    return;
  }
  saved = res.data;
  fill(saved);
  renderChecks(null);
}

async function submit(kind) {
  showMessage(message);
  const clientErrors = clientValidate();
  if (clientErrors.length) {
    showMessage(message, "bad", "Please fix these fields:", clientErrors);
    return null;
  }
  busy(true);
  const res = await api("POST", kind === "save" ? "/api/config" : "/api/validate", { config: collect() });
  busy(false);
  renderChecks(res.data.checks);
  if (!res.ok) {
    showMessage(message, "bad", res.data.error || "Request failed", res.data.errors);
    return null;
  }
  const errors = (res.data.checks || []).filter((c) => c.status === "error");
  if (kind === "save") {
    saved = res.data;
    fill(saved);
  }
  const verb = kind === "save" ? "Configuration saved" : "Validation finished";
  if (errors.length) showMessage(message, "warn", `${verb}, with ${errors.length} problem(s) to fix before running:`,
    errors.map((c) => `${c.name}: ${c.message}`));
  else showMessage(message, "ok", `${verb}. All checks passed.`);
  return res.data;
}

form.addEventListener("submit", (event) => { event.preventDefault(); submit("save"); });
document.getElementById("validate-btn").addEventListener("click", () => submit("validate"));
document.getElementById("reset-btn").addEventListener("click", () => { if (saved) { fill(saved); showMessage(message); } });
document.getElementById("run-btn").addEventListener("click", async () => {
  if (dirty) {
    showMessage(message, "warn", "You have unsaved changes. Save the configuration first, or discard the changes.");
    return;
  }
  busy(true);
  const res = await api("POST", "/api/run", {});
  busy(false);
  if (res.ok || res.status === 409) {
    window.location.href = "/results" + (res.data.run_id ? `?run=${encodeURIComponent(res.data.run_id)}` : "");
  } else {
    showMessage(message, "bad", res.data.error || "Could not start the run", res.data.errors);
  }
});
form.addEventListener("input", () => setDirty(true));
adapterSelect.addEventListener("change", () => { updateAdapterHint(); setDirty(true); });

load();
