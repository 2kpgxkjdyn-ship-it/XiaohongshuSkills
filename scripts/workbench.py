"""Local web workbench for Xiaohongshu semi-auto workflows."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parents[1]
QUEUE_FILE = BASE_DIR / "review_queue.csv"
STATUS_FILE = BASE_DIR / "run_status.log"
CONFIG_FILE = BASE_DIR / "config" / "semi_auto_comment.json"
DEFAULT_LOG_FILE = BASE_DIR / "comment_log.csv"
SEMI_AUTO_SCRIPT = BASE_DIR / "semi_auto_comment.py"
CDP_SCRIPT = BASE_DIR / "scripts" / "cdp_publish.py"
CHROME_SCRIPT = BASE_DIR / "scripts" / "chrome_launcher.py"

QUEUE_FIELDNAMES = [
    "approve",
    "keyword",
    "note_id",
    "note_url",
    "xsec_token",
    "score",
    "suggested_comment",
    "status",
    "last_error",
    "created_at",
    "published_at",
]

JOB_LOCK = threading.Lock()
CURRENT_JOB: dict[str, Any] | None = None
JOB_HISTORY: list[dict[str, Any]] = []
MAX_JOB_LOG_LINES = 500
MAX_STATUS_LINES = 160


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>小红书自动化工作台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --surface: #ffffff;
      --surface-2: #eef3f6;
      --text: #172026;
      --muted: #68737d;
      --line: #d8e0e6;
      --accent: #d83f5f;
      --accent-2: #0f766e;
      --warn: #a16207;
      --danger: #b42318;
      --ok: #137333;
      --shadow: 0 12px 28px rgba(23, 32, 38, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-width: 320px;
      background: var(--bg);
      color: var(--text);
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      letter-spacing: 0;
    }
    button, input, textarea, select { font: inherit; }
    button {
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--text);
      min-height: 36px;
      padding: 0 12px;
      border-radius: 6px;
      cursor: pointer;
    }
    button:hover { border-color: #9fb0bd; }
    button:disabled { cursor: not-allowed; opacity: 0.55; }
    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }
    button.green {
      border-color: var(--accent-2);
      background: var(--accent-2);
      color: white;
    }
    button.danger {
      border-color: var(--danger);
      color: var(--danger);
    }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      background: white;
      color: var(--text);
      border-radius: 6px;
      padding: 9px 10px;
      outline: none;
    }
    textarea {
      min-height: 74px;
      resize: vertical;
      line-height: 1.5;
    }
    input:focus, textarea:focus, select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(216, 63, 95, 0.12);
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto auto 1fr;
    }
    header {
      background: var(--surface);
      border-bottom: 1px solid var(--line);
    }
    .header-inner {
      max-width: 1500px;
      margin: 0 auto;
      padding: 18px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      line-height: 1.2;
    }
    .subtle {
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }
    .toolbar {
      max-width: 1500px;
      margin: 0 auto;
      padding: 16px 20px;
      display: grid;
      grid-template-columns: minmax(220px, 2fr) 110px auto auto auto;
      gap: 10px;
      align-items: end;
    }
    .field label {
      display: block;
      margin: 0 0 5px;
      font-size: 12px;
      color: var(--muted);
    }
    .check {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 36px;
      color: var(--muted);
      font-size: 13px;
    }
    .check input { width: 16px; height: 16px; }
    main {
      max-width: 1500px;
      width: 100%;
      margin: 0 auto;
      padding: 0 20px 24px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 420px;
      gap: 16px;
    }
    section {
      min-width: 0;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .section-head {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .section-head h2 {
      margin: 0;
      font-size: 16px;
    }
    .actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      padding: 12px 16px;
      background: var(--surface-2);
      border-bottom: 1px solid var(--line);
    }
    .stat {
      min-height: 56px;
      background: white;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
    }
    .stat b {
      display: block;
      font-size: 18px;
    }
    .stat span {
      display: block;
      margin-top: 2px;
      color: var(--muted);
      font-size: 12px;
    }
    .notice {
      margin: 0 0 12px;
      padding: 11px 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      color: var(--text);
      line-height: 1.45;
      font-size: 13px;
    }
    .notice strong {
      display: block;
      margin-bottom: 3px;
      font-size: 14px;
    }
    .notice.warn {
      border-color: rgba(161, 98, 7, 0.35);
      background: #fff8e6;
      color: #6f4505;
    }
    .notice.ok {
      border-color: rgba(19, 115, 51, 0.28);
      background: #edf7ee;
      color: #0f4f24;
    }
    .notice.info {
      border-color: rgba(15, 118, 110, 0.25);
      background: #eef9f7;
      color: #0b514b;
    }
    .notice.hidden { display: none; }
    .queue {
      display: grid;
      gap: 10px;
      padding: 12px 16px 16px;
    }
    .row {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: white;
      overflow: hidden;
    }
    .row-head {
      display: grid;
      grid-template-columns: 28px minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
    }
    .row-head input { width: 18px; height: 18px; }
    .note-title {
      min-width: 0;
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .note-title a {
      color: var(--text);
      font-weight: 650;
      text-decoration: none;
      overflow-wrap: anywhere;
    }
    .meta {
      color: var(--muted);
      font-size: 12px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--surface-2);
      font-size: 12px;
      white-space: nowrap;
    }
    .badge.ok { color: var(--ok); border-color: rgba(19, 115, 51, 0.25); background: #edf7ee; }
    .badge.warn { color: var(--warn); border-color: rgba(161, 98, 7, 0.25); background: #fff8e6; }
    .badge.danger { color: var(--danger); border-color: rgba(180, 35, 24, 0.25); background: #fff1f0; }
    .row-body {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 176px;
      gap: 10px;
      padding: 10px 12px 12px;
      align-items: start;
    }
    .row-actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .side {
      display: grid;
      gap: 16px;
      align-content: start;
    }
    .panel-body { padding: 12px 16px 16px; }
    .mini-grid {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 8px;
    }
    .publish-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 10px;
    }
    pre {
      margin: 0;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 420px;
      padding: 12px;
      border-radius: 6px;
      border: 1px solid var(--line);
      background: #101820;
      color: #dce7ef;
      font: 12px/1.55 Consolas, "Courier New", monospace;
    }
    .empty {
      padding: 26px 16px;
      color: var(--muted);
      text-align: center;
    }
    .job {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 13px;
    }
    .dot {
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: var(--ok);
    }
    .dot.running {
      background: var(--accent);
      animation: pulse 1s infinite alternate;
    }
    @keyframes pulse { from { opacity: 0.35; } to { opacity: 1; } }
    @media (max-width: 980px) {
      .toolbar { grid-template-columns: 1fr 90px; }
      .toolbar .check, .toolbar button { align-self: stretch; }
      main { grid-template-columns: 1fr; }
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .row-body { grid-template-columns: 1fr; }
    }
    @media (max-width: 560px) {
      .header-inner { align-items: flex-start; flex-direction: column; }
      .toolbar { grid-template-columns: 1fr; }
      .stats { grid-template-columns: 1fr; }
      .section-head { align-items: flex-start; flex-direction: column; }
      .row-head { grid-template-columns: 24px minmax(0, 1fr); }
      .row-head > .badge { grid-column: 2; width: max-content; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div class="header-inner">
        <div>
          <h1>小红书自动化工作台</h1>
          <div class="subtle">关键词生成、人工审批、确认发布和运行状态集中在这里</div>
        </div>
        <div class="job"><span id="jobDot" class="dot"></span><span id="jobText">正在读取状态</span></div>
      </div>
    </header>

    <div class="toolbar">
      <div class="field">
        <label for="keyword">关键词</label>
        <input id="keyword" value="找品" />
      </div>
      <div class="field">
        <label for="limit">候选数</label>
        <input id="limit" type="number" min="1" max="200" value="10" />
      </div>
      <label class="check"><input id="appendQueue" type="checkbox" />追加队列</label>
      <label class="check"><input id="allowRepeat" type="checkbox" />允许重复</label>
      <button id="makeQueue" class="primary">生成待审队列</button>
    </div>

    <main>
      <section>
        <div class="section-head">
          <h2>待审队列</h2>
          <div class="actions">
            <button id="refresh">刷新</button>
            <button id="approveSelected" class="green">批准选中</button>
            <button id="skipSelected">跳过选中</button>
            <button id="approveAll">批准全部待审</button>
          </div>
        </div>
        <div id="stats" class="stats"></div>
        <div id="queue" class="queue"></div>
      </section>

      <div class="side">
        <section>
          <div class="section-head">
            <h2>发布控制</h2>
          </div>
          <div class="panel-body">
            <div id="notice" class="notice hidden"></div>
            <div class="publish-grid">
              <div class="field">
                <label for="waitMin">最小间隔秒</label>
                <input id="waitMin" type="number" min="0" value="120" />
              </div>
              <div class="field">
                <label for="waitMax">最大间隔秒</label>
                <input id="waitMax" type="number" min="0" value="300" />
              </div>
            </div>
            <label class="check"><input id="noWait" type="checkbox" />不等待下一条</label>
            <div class="actions" style="margin-top:10px">
              <button id="publishApproved" class="primary">发布已批准</button>
              <button id="stopJob" class="danger">停止任务</button>
            </div>
          </div>
        </section>

        <section>
          <div class="section-head">
            <h2>浏览器</h2>
          </div>
          <div class="panel-body">
            <div class="mini-grid">
              <button data-chrome="start">启动</button>
              <button data-chrome="restart">重启</button>
              <button data-chrome="kill">关闭</button>
            </div>
            <div class="actions" style="margin-top:10px">
              <button id="checkLogin">检查登录</button>
            </div>
          </div>
        </section>

        <section>
          <div class="section-head">
            <h2>任务输出</h2>
          </div>
          <div class="panel-body"><pre id="jobLog"></pre></div>
        </section>

        <section>
          <div class="section-head">
            <h2>运行状态</h2>
          </div>
          <div class="panel-body"><pre id="statusLog"></pre></div>
        </section>
      </div>
    </main>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    const selectedRows = new Set();
    let state = null;

    async function api(path, options = {}) {
      const init = { headers: { "Content-Type": "application/json" }, ...options };
      if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
      const res = await fetch(path, init);
      const data = await res.json();
      if (!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
      return data;
    }

    function statusBadge(row) {
      const status = (row.status || "pending").toLowerCase();
      if (status === "success") return ["已成功", "ok"];
      if (status === "failed") return ["失败", "danger"];
      if (status === "skipped") return ["已跳过", "warn"];
      if (row.approve === "1") return ["已批准", "ok"];
      return ["待审", "warn"];
    }

    function renderNotice(notice, quota) {
      const box = $("notice");
      if (!box) return;
      if (!notice) {
        box.className = "notice hidden";
        box.innerHTML = "";
        return;
      }
      const quotaText = quota?.daily_limit > 0
        ? `今日成功 ${quota.today_success}/${quota.daily_limit}，剩余 ${quota.remaining}`
        : "今日发布上限未设置";
      box.className = `notice ${notice.tone || "info"}`;
      box.innerHTML = `<strong>${escapeHtml(notice.title)}</strong><div>${escapeHtml(notice.message)}</div><div>${escapeHtml(quotaText)}</div>`;
    }

    function renderStats(stats) {
      const items = [
        ["total", "全部"],
        ["pending", "待审"],
        ["approved", "已批准待发布"],
        ["success", "成功"],
        ["failed", "失败"],
      ];
      $("stats").innerHTML = items.map(([key, label]) =>
        `<div class="stat"><b>${stats[key] ?? 0}</b><span>${label}</span></div>`
      ).join("");
    }

    function renderQueue(rows) {
      if (!rows.length) {
        $("queue").innerHTML = '<div class="empty">还没有队列。输入关键词后点击“生成待审队列”。</div>';
        return;
      }
      $("queue").innerHTML = rows.map((row) => {
        const [label, tone] = statusBadge(row);
        const index = row._index;
        const checked = selectedRows.has(index) ? "checked" : "";
        const note = row.note_id || `第 ${index + 1} 条`;
        const url = row.note_url || "#";
        const keyword = row.keyword || "";
        const err = row.last_error ? ` · ${escapeHtml(row.last_error)}` : "";
        const finishedAt = row.published_at ? ` · ${escapeHtml(row.published_at)}` : "";
        return `
          <article class="row">
            <div class="row-head">
              <input type="checkbox" data-select="${index}" ${checked} />
              <div class="note-title">
                <a href="${escapeAttr(url)}" target="_blank" rel="noreferrer">${escapeHtml(note)}</a>
                <span class="meta">${escapeHtml(keyword)}${finishedAt}${err}</span>
              </div>
              <span class="badge ${tone}">${label}</span>
            </div>
            <div class="row-body">
              <textarea data-comment="${index}">${escapeHtml(row.suggested_comment || "")}</textarea>
              <div class="row-actions">
                <button class="green" data-action="approve" data-index="${index}">批准</button>
                <button data-action="save" data-index="${index}">保存</button>
                <button data-action="skip" data-index="${index}">跳过</button>
                <button data-action="pending" data-index="${index}">待审</button>
              </div>
            </div>
          </article>
        `;
      }).join("");
    }

    function renderJob(job) {
      const dot = $("jobDot");
      const text = $("jobText");
      dot.classList.toggle("running", !!job?.running);
      if (!job) {
        text.textContent = "空闲";
        $("jobLog").textContent = "";
        return;
      }
      text.textContent = job.running ? `运行中：${job.name}` : `最近任务：${job.name}（${job.returncode ?? "结束"}）`;
      $("jobLog").textContent = (job.log || []).join("");
    }

    function render(data) {
      state = data;
      renderStats(data.stats);
      renderQueue(data.queue);
      renderJob(data.job);
      renderNotice(data.notice, data.quota);
      $("statusLog").textContent = (data.status_log || []).join("");
      const busy = !!data.job?.running;
      document.querySelectorAll("button").forEach((btn) => {
        if (btn.id === "stopJob" || btn.id === "refresh") return;
        btn.disabled = busy;
      });
      $("stopJob").disabled = !busy;
    }

    async function refresh() {
      try {
        render(await api("/api/state"));
      } catch (err) {
        $("jobText").textContent = err.message;
      }
    }

    async function startJob(path, body) {
      try {
        await api(path, { method: "POST", body });
        await refresh();
      } catch (err) {
        alert(err.message);
      }
    }

    function getSelectedIndexes() {
      return Array.from(selectedRows);
    }

    function getComment(index) {
      const textarea = document.querySelector(`[data-comment="${index}"]`);
      return textarea ? textarea.value : "";
    }

    async function updateRow(index, patch) {
      await api("/api/queue/update", { method: "POST", body: { index, ...patch } });
      await refresh();
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[char]));
    }

    function escapeAttr(value) {
      return escapeHtml(value).replace(/`/g, "&#96;");
    }

    $("makeQueue").addEventListener("click", () => startJob("/api/make-queue", {
      keyword: $("keyword").value.trim(),
      limit: Number($("limit").value || 10),
      appendQueue: $("appendQueue").checked,
      allowRepeat: $("allowRepeat").checked,
    }));
    $("publishApproved").addEventListener("click", () => startJob("/api/publish-approved", {
      waitMin: Number($("waitMin").value || 0),
      waitMax: Number($("waitMax").value || 0),
      noWait: $("noWait").checked,
    }));
    $("refresh").addEventListener("click", refresh);
    $("stopJob").addEventListener("click", () => startJob("/api/job/stop", {}));
    $("checkLogin").addEventListener("click", () => startJob("/api/check-login", {}));

    document.querySelectorAll("[data-chrome]").forEach((button) => {
      button.addEventListener("click", () => startJob("/api/chrome", { action: button.dataset.chrome }));
    });

    $("queue").addEventListener("change", (event) => {
      const index = event.target.dataset.select;
      if (index === undefined) return;
      const numeric = Number(index);
      if (event.target.checked) selectedRows.add(numeric);
      else selectedRows.delete(numeric);
    });

    $("queue").addEventListener("click", async (event) => {
      const action = event.target.dataset.action;
      if (!action) return;
      const index = Number(event.target.dataset.index);
      try {
        if (action === "approve") await updateRow(index, { approve: "1", status: "pending", suggested_comment: getComment(index), last_error: "" });
        if (action === "save") await updateRow(index, { suggested_comment: getComment(index) });
        if (action === "skip") await updateRow(index, { approve: "0", status: "skipped", last_error: "workbench_skipped" });
        if (action === "pending") await updateRow(index, { approve: "0", status: "pending", last_error: "" });
      } catch (err) {
        alert(err.message);
      }
    });

    $("approveSelected").addEventListener("click", () => startJob("/api/queue/bulk", { action: "approve", indexes: getSelectedIndexes() }));
    $("skipSelected").addEventListener("click", () => startJob("/api/queue/bulk", { action: "skip", indexes: getSelectedIndexes() }));
    $("approveAll").addEventListener("click", () => startJob("/api/queue/bulk", { action: "approve_all_pending" }));

    refresh();
    setInterval(refresh, 2500);
  </script>
</body>
</html>
"""


def decode_csv_line(raw_line: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return raw_line.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw_line.decode("utf-8", errors="replace"), "mixed-replace"


def read_mixed_encoding_csv(path: Path) -> list[dict[str, str]]:
    raw_lines = [line for line in path.read_bytes().splitlines() if line.strip()]
    if not raw_lines:
        return []
    header_text, _ = decode_csv_line(raw_lines[0])
    header = next(csv.reader([header_text]))
    rows: list[dict[str, str]] = []
    for raw_line in raw_lines[1:]:
        line_text, _ = decode_csv_line(raw_line)
        values = next(csv.reader([line_text]))
        rows.append({key: values[index] if index < len(values) else "" for index, key in enumerate(header)})
    return rows


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            with path.open("r", encoding=encoding, newline="") as file:
                return list(csv.DictReader(file))
        except UnicodeDecodeError:
            continue
    return read_mixed_encoding_csv(path)


def read_queue_rows() -> list[dict[str, str]]:
    return read_csv_rows(QUEUE_FILE)


def write_queue_rows(rows: list[dict[str, str]]) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    extra_fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in QUEUE_FIELDNAMES and key not in extra_fields and not key.startswith("_"):
                extra_fields.append(key)
    fieldnames = QUEUE_FIELDNAMES + extra_fields
    with QUEUE_FILE.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def read_status_tail() -> list[str]:
    if not STATUS_FILE.exists():
        return []
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            lines = STATUS_FILE.read_text(encoding=encoding).splitlines(True)
            return lines[-MAX_STATUS_LINES:]
        except UnicodeDecodeError:
            continue
    return STATUS_FILE.read_text(encoding="utf-8", errors="replace").splitlines(True)[-MAX_STATUS_LINES:]


def build_stats(rows: list[dict[str, str]]) -> dict[str, int]:
    stats = {"total": len(rows), "pending": 0, "approved": 0, "success": 0, "failed": 0, "skipped": 0}
    for row in rows:
        status = (row.get("status") or "pending").strip().lower()
        approve = (row.get("approve") or "").strip().lower()
        is_approved = approve in {"1", "yes", "y", "true", "approved"}
        if status in {"", "pending"} and not is_approved:
            stats["pending"] += 1
        if status == "success":
            stats["success"] += 1
        if status == "failed":
            stats["failed"] += 1
        if status == "skipped":
            stats["skipped"] += 1
        if is_approved and status in {"", "pending"}:
            stats["approved"] += 1
    return stats


def read_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def resolve_comment_log_file(config: dict[str, Any]) -> Path:
    value = str(config.get("log_file") or "").strip()
    if not value:
        return DEFAULT_LOG_FILE
    path = Path(value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def count_today_success(rows: list[dict[str, str]]) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    success_statuses = {"confirmed", "success", "成功"}
    count = 0
    for row in rows:
        timestamp = str(row.get("timestamp") or "").strip()
        status = str(row.get("status") or "").strip().lower()
        if timestamp.startswith(today) and status in success_statuses:
            count += 1
    return count


def build_quota() -> dict[str, Any]:
    config = read_config()
    try:
        daily_limit = int(config.get("daily_success_limit") or 0)
    except (TypeError, ValueError):
        daily_limit = 0
    log_file = resolve_comment_log_file(config)
    today_success = count_today_success(read_csv_rows(log_file))
    remaining = None if daily_limit <= 0 else max(0, daily_limit - today_success)
    return {
        "daily_limit": daily_limit,
        "today_success": today_success,
        "remaining": remaining,
        "reached": daily_limit > 0 and today_success >= daily_limit,
        "log_file": str(log_file),
    }


def build_notice(stats: dict[str, int], quota: dict[str, Any], job: dict[str, Any] | None) -> dict[str, str]:
    approved = stats.get("approved", 0)
    pending = stats.get("pending", 0)
    if job and job.get("running"):
        return {
            "tone": "info",
            "title": f"任务运行中：{job.get('name')}",
            "message": "可以在任务输出里查看实时日志，队列状态会自动刷新。",
        }
    if quota.get("reached"):
        return {
            "tone": "warn",
            "title": f"今日发布上限已达 {quota.get('today_success')}/{quota.get('daily_limit')}",
            "message": f"当前还有 {approved} 条已批准待发布，不会丢失；等额度恢复后再点发布即可。",
        }
    if approved > 0:
        remaining = quota.get("remaining")
        if remaining is None:
            limit_text = "当前未设置每日上限"
        else:
            limit_text = f"今天还可发布 {remaining} 条"
        return {
            "tone": "ok",
            "title": f"有 {approved} 条已批准待发布",
            "message": f"{limit_text}，点击“发布已批准”后会按队列继续执行。",
        }
    if pending > 0:
        return {
            "tone": "info",
            "title": f"还有 {pending} 条待审",
            "message": "批准后才会进入发布队列；未批准的不会被发布。",
        }
    return {
        "tone": "info",
        "title": "没有可发布任务",
        "message": "队列为空，或当前队列都已经成功、失败、跳过。",
    }


def get_public_job() -> dict[str, Any] | None:
    with JOB_LOCK:
        job = CURRENT_JOB or (JOB_HISTORY[-1] if JOB_HISTORY else None)
        if not job:
            return None
        return {
            "id": job["id"],
            "name": job["name"],
            "running": job["running"],
            "started_at": job["started_at"],
            "finished_at": job.get("finished_at"),
            "returncode": job.get("returncode"),
            "log": list(job["log"][-MAX_JOB_LOG_LINES:]),
        }


def make_state() -> dict[str, Any]:
    rows = read_queue_rows()
    stats = build_stats(rows)
    quota = build_quota()
    job = get_public_job()
    visible_rows: list[dict[str, str | int]] = []
    for index, row in enumerate(rows):
        copy: dict[str, str | int] = {key: value for key, value in row.items()}
        copy["_index"] = index
        visible_rows.append(copy)
    return {
        "ok": True,
        "queue": visible_rows,
        "stats": stats,
        "quota": quota,
        "notice": build_notice(stats, quota, job),
        "status_log": read_status_tail(),
        "job": job,
    }


def append_job_log(job: dict[str, Any], line: str) -> None:
    with JOB_LOCK:
        job["log"].append(line)
        if len(job["log"]) > MAX_JOB_LOG_LINES:
            job["log"] = job["log"][-MAX_JOB_LOG_LINES:]


def run_job(name: str, command: list[str]) -> dict[str, Any]:
    global CURRENT_JOB
    with JOB_LOCK:
        if CURRENT_JOB and CURRENT_JOB["running"]:
            raise RuntimeError(f"已有任务正在运行：{CURRENT_JOB['name']}")
        job = {
            "id": f"{int(time.time())}-{len(JOB_HISTORY) + 1}",
            "name": name,
            "command": command,
            "running": True,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
            "returncode": None,
            "process": None,
            "log": [],
        }
        CURRENT_JOB = job
        JOB_HISTORY.append(job)

    thread = threading.Thread(target=_run_job_thread, args=(job,), daemon=True)
    thread.start()
    return job


def _run_job_thread(job: dict[str, Any]) -> None:
    global CURRENT_JOB
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    append_job_log(job, f"$ {' '.join(job['command'])}\n")
    try:
        process = subprocess.Popen(
            job["command"],
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        with JOB_LOCK:
            job["process"] = process
        assert process.stdout is not None
        for line in process.stdout:
            append_job_log(job, line)
        returncode = process.wait()
    except Exception as exc:
        append_job_log(job, f"\n[workbench] 任务启动失败：{exc}\n")
        returncode = -1

    with JOB_LOCK:
        job["returncode"] = returncode
        job["finished_at"] = datetime.now().isoformat(timespec="seconds")
        job["running"] = False
        job["process"] = None
        if CURRENT_JOB is job:
            CURRENT_JOB = None
    append_job_log(job, f"\n[workbench] 任务结束，退出码：{returncode}\n")


def stop_current_job() -> bool:
    with JOB_LOCK:
        job = CURRENT_JOB
        process = job.get("process") if job else None
    if not job or not process:
        return False
    process.terminate()
    append_job_log(job, "\n[workbench] 已请求停止任务\n")
    return True


def require_int(value: Any, default: int, minimum: int = 0, maximum: int = 10000) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


class WorkbenchHandler(BaseHTTPRequestHandler):
    server_version = "XHSWorkbench/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[workbench] {timestamp} {format % args}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_html(INDEX_HTML)
            return
        if path == "/api/state":
            self.send_json(make_state())
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/make-queue":
                self.handle_make_queue(payload)
            elif path == "/api/publish-approved":
                self.handle_publish_approved(payload)
            elif path == "/api/queue/update":
                self.handle_queue_update(payload)
            elif path == "/api/queue/bulk":
                self.handle_queue_bulk(payload)
            elif path == "/api/chrome":
                self.handle_chrome(payload)
            elif path == "/api/check-login":
                self.handle_check_login()
            elif path == "/api/job/stop":
                stopped = stop_current_job()
                self.send_json({"ok": True, "stopped": stopped})
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_make_queue(self, payload: dict[str, Any]) -> None:
        keyword = str(payload.get("keyword") or "").strip()
        if not keyword:
            raise ValueError("关键词不能为空")
        limit = require_int(payload.get("limit"), 10, minimum=1, maximum=200)
        command = [
            sys.executable,
            str(SEMI_AUTO_SCRIPT),
            "--make-queue",
            "--keyword",
            keyword,
            "--limit",
            str(limit),
        ]
        if payload.get("appendQueue"):
            command.append("--append-queue")
        if payload.get("allowRepeat"):
            command.append("--allow-repeat")
        run_job(f"生成队列：{keyword}", command)
        self.send_json({"ok": True})

    def handle_publish_approved(self, payload: dict[str, Any]) -> None:
        wait_min = require_int(payload.get("waitMin"), 120, minimum=0, maximum=86400)
        wait_max = require_int(payload.get("waitMax"), 300, minimum=0, maximum=86400)
        if wait_max < wait_min:
            wait_max = wait_min
        command = [
            sys.executable,
            str(SEMI_AUTO_SCRIPT),
            "--publish-approved",
            "--wait-min",
            str(wait_min),
            "--wait-max",
            str(wait_max),
        ]
        if payload.get("noWait"):
            command.append("--no-wait")
        run_job("发布已批准队列", command)
        self.send_json({"ok": True})

    def handle_queue_update(self, payload: dict[str, Any]) -> None:
        rows = read_queue_rows()
        index = require_int(payload.get("index"), -1, minimum=-1, maximum=max(len(rows) - 1, -1))
        if index < 0 or index >= len(rows):
            raise ValueError("队列行不存在")
        allowed = {"approve", "suggested_comment", "status", "last_error"}
        for key in allowed:
            if key in payload:
                rows[index][key] = str(payload.get(key) or "")
        write_queue_rows(rows)
        self.send_json({"ok": True})

    def handle_queue_bulk(self, payload: dict[str, Any]) -> None:
        rows = read_queue_rows()
        action = str(payload.get("action") or "")
        indexes = payload.get("indexes")
        if indexes is None:
            target_indexes = range(len(rows))
        else:
            target_indexes = [int(index) for index in indexes if 0 <= int(index) < len(rows)]

        changed = 0
        if action == "approve":
            for index in target_indexes:
                approve = (rows[index].get("approve") or "").strip().lower()
                if (rows[index].get("status") or "pending").lower() in {"", "pending"} and approve not in {"1", "yes", "y", "true", "approved"}:
                    rows[index]["approve"] = "1"
                    rows[index]["status"] = "pending"
                    rows[index]["last_error"] = ""
                    changed += 1
        elif action == "skip":
            for index in target_indexes:
                rows[index]["approve"] = "0"
                rows[index]["status"] = "skipped"
                rows[index]["last_error"] = "workbench_skipped"
                changed += 1
        elif action == "approve_all_pending":
            for row in rows:
                approve = (row.get("approve") or "").strip().lower()
                if (row.get("status") or "pending").lower() in {"", "pending"} and approve not in {"1", "yes", "y", "true", "approved"}:
                    row["approve"] = "1"
                    row["last_error"] = ""
                    changed += 1
        else:
            raise ValueError("未知批量操作")
        write_queue_rows(rows)
        self.send_json({"ok": True, "changed": changed})

    def handle_chrome(self, payload: dict[str, Any]) -> None:
        action = str(payload.get("action") or "start")
        command = [sys.executable, str(CHROME_SCRIPT)]
        if action == "restart":
            command.append("--restart")
        elif action == "kill":
            command.append("--kill")
        elif action != "start":
            raise ValueError("未知浏览器操作")
        run_job(f"Chrome {action}", command)
        self.send_json({"ok": True})

    def handle_check_login(self) -> None:
        command = [sys.executable, str(CDP_SCRIPT), "--reuse-existing-tab", "check-login"]
        run_job("检查登录", command)
        self.send_json({"ok": True})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动小红书自动化本地工作台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8766, help="监听端口，默认 8766")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), WorkbenchHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"[workbench] 控制台已启动：{url}")
    print("[workbench] 按 Ctrl+C 退出")
    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("[workbench] 正在关闭")
    finally:
        stop_current_job()
        server.server_close()


if __name__ == "__main__":
    main()
