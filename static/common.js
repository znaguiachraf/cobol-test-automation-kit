// Shared helpers. All dynamic text is inserted with textContent (never innerHTML).
"use strict";

const STATUS_CLASS = {
  PASS: "ok", PASSED: "ok", SUCCESS: "ok", ok: "ok",
  PASSED_WITH_SKIPS: "warn", NO_TESTS_RUN: "warn", warning: "warn",
  FAIL: "bad", FAILED: "bad", ERROR: "bad", BUILD_FAILED: "bad", error: "bad",
};

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function badge(status, extraClass, label) {
  const text = label ?? String(status ?? "UNKNOWN").replaceAll("_", " ");
  return el("span", { class: `badge ${STATUS_CLASS[status] || ""} ${extraClass || ""}`.trim(), text });
}

async function api(method, url, body) {
  const options = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, options);
  } catch (err) {
    return { ok: false, status: 0, data: { error: "Cannot reach the local server. Is it still running?", errors: [] } };
  }
  let data = {};
  try { data = await response.json(); } catch (err) { data = { error: `Unexpected response (${response.status})` }; }
  return { ok: response.ok, status: response.status, data };
}

function showMessage(container, kind, title, items) {
  container.replaceChildren();
  if (!title) { container.hidden = true; return; }
  const box = el("div", { class: `msg ${kind}`, role: kind === "bad" ? "alert" : "status" }, el("b", { text: title }));
  if (items && items.length) box.append(el("ul", {}, items.map((t) => el("li", { text: t }))));
  container.append(box);
  container.hidden = false;
}

function fmtTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}
