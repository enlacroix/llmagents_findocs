"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = response.statusText;
    try { message = (await response.json()).detail || message; } catch {}
    throw new Error(message);
  }
  return response.json();
}

const ICONS = {
  ready: "iamready",
  ocr: "ocr working",
  extract: "llm is running",
  agent: "agent is running",
  good: "all is good",
  financial: "financial error",
  validation: "validation error",
  bad: "all is bad",
};
const icon = (key) => `/icons/${encodeURIComponent(ICONS[key])}.png`;

const TYPE_NAMES = {
  company_card: "Карточка предприятия",
  order: "Приказ",
  bank_statement: "Банковская выписка",
  branch_report: "Сводный отчет по филиалам",
  invoice: "Счет на оплату",
  transfer_document: "УПД",
  service_act: "Акт оказанных услуг",
  placement_registry: "Реестр к акту",
  contract: "Договор",
  contract_appendix: "Приложение к договору",
};

const STAGES = {
  render: { title: "Открываю документ…", icon: "ocr", step: 0 },
  ocr: { title: "Читаю скан (OCR)…", icon: "ocr", step: 0 },
  extract: { title: "Раскладываю данные по полям…", icon: "extract", step: 1 },
  agent: { title: "Агент проверяет документ…", icon: "agent", step: 2 },
};

const ISSUE_CODES = { schema: "схема", format: "формат", date: "дата", arithmetic: "арифметика" };

function verdictIcon(doc) {
  if (doc.status === "approved") return "good";
  const codes = new Set((doc.issues || []).map((i) => i.code));
  if (codes.has("arithmetic")) return "financial";
  if (codes.has("format") || codes.has("schema") || codes.has("date")) return "validation";
  return "financial";
}

const statusLabel = (status) => (status === "approved" ? "Одобрен" : "На проверку");
const typeName = (type) => TYPE_NAMES[type] || type;
const money = (value) => (value == null ? "—" : Number(value).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const pct = (value) => `${(value * 100).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;

function say(title, text, iconKey = "ready", busy = false) {
  $("#balloon").innerHTML = `<b>${esc(title)}</b><span title="${esc(text)}">${esc(text)}</span>`;
  const img = $("#assistant-img");
  img.src = icon(iconKey);
  img.classList.toggle("busy", busy);
}

function setStatus(text) { $("#status-text").textContent = text; }

let currentTab = "documents";
const TAB_TITLES = { documents: "Документы", queue: "На проверку", registry: "Справочник", metrics: "Метрики" };

function showTab(name) {
  currentTab = name;
  $$(".content .tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
  $$(".content .tabpanel").forEach((p) => { p.hidden = p.id !== `tab-${name}`; });
  $("#address").innerHTML = `Ревизор ▸ <b>${TAB_TITLES[name]}</b>`;
  if (name === "registry") loadRegistry();
  if (name === "metrics") loadMetrics();
}

$$(".content .tab").forEach((tab) => tab.addEventListener("click", () => showTab(tab.dataset.tab)));

let documents = [];

function documentRows(docs, withFields) {
  return docs.map((d) => `
    <tr data-id="${d.id}" tabindex="0">
      <td class="status-cell"><img src="${icon(verdictIcon(d))}" alt=""><span class="badge ${d.status}">${statusLabel(d.status)}</span></td>
      <td>${esc(d.source_file)}</td>
      <td class="num">${d.page}</td>
      <td>${esc(typeName(d.document_type))}</td>
      ${withFields ? `<td><div class="chips">${(d.review_fields || []).map((f) => `<span class="chip">${esc(f)}</span>`).join("")}</div></td>` : ""}
      <td class="reason"><div title="${esc(d.reason)}">${esc(d.reason)}</div></td>
    </tr>`).join("");
}

function renderList(container, docs, withFields, emptyText) {
  if (!docs.length) {
    container.innerHTML = `<div class="empty">${emptyText}</div>`;
    return;
  }
  container.innerHTML = `
    <table class="list">
      <thead><tr><th>Решение</th><th>Файл</th><th>Стр.</th><th>Тип документа</th>${withFields ? "<th>Спорные поля</th>" : ""}<th>Причина</th></tr></thead>
      <tbody>${documentRows(docs, withFields)}</tbody>
    </table>`;
  $$("tbody tr", container).forEach((row) => {
    const open = () => {
      $$("tr.selected").forEach((r) => r.classList.remove("selected"));
      row.classList.add("selected");
      openDetails(Number(row.dataset.id));
    };
    row.addEventListener("click", open);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  });
}

async function loadDocuments() {
  documents = await api("/api/documents");
  const review = documents.filter((d) => d.status === "needs_review");
  renderList($("#tab-documents"), documents, false,
    "Документов пока нет.<br>Выберите образец в панели слева или загрузите свой скан.");
  renderList($("#tab-queue"), review, true, "Очередь пуста: всё проверено без замечаний.");
  $("#queue-count").textContent = review.length || "";
  $("#t-total").textContent = documents.length;
  $("#t-ok").textContent = documents.length - review.length;
  $("#t-bad").textContent = review.length;
  $("#status-docs").textContent = `Документов: ${documents.length}`;
}

async function loadRegistry() {
  const panel = $("#tab-registry");
  const rows = await api("/api/counterparties");
  panel.innerHTML = `
    <p class="note">Контрагенты, с которыми сверяются реквизиты в документах.</p>
    <table class="list">
      <thead><tr><th>Наименование</th><th>ИНН</th><th>КПП</th><th>Адрес</th><th>Телефон</th><th>E-mail</th></tr></thead>
      <tbody>${rows.map((r) => `
        <tr>
          <td>${esc(r.name)}${r.is_own_company ? ' <span class="badge approved">наша компания</span>' : ""}</td>
          <td class="num">${esc(r.inn || "—")}</td>
          <td class="num">${esc(r.kpp || "—")}</td>
          <td>${esc(r.address || "—")}</td>
          <td>${esc(r.phone || "—")}</td>
          <td>${esc(r.email || "—")}</td>
        </tr>`).join("")}</tbody>
    </table>`;
}

function renderMetrics(report) {
  const panel = $("#tab-metrics");
  if (!report || !report.summary) {
    panel.innerHTML = `<div class="empty">Метрик пока нет. Обработайте образцы и нажмите «Пересчитать метрики».</div>`;
    return;
  }
  const s = report.summary;
  const card = (label, value, alarm = false) =>
    `<div class="metric${alarm ? " alarm" : ""}"><div class="label">${label}</div><div class="value">${value}</div></div>`;
  panel.innerHTML = `
    <div class="metric-grid">
      ${card("Точность полей", pct(s.accuracy))}
      ${card("Ошибки OCR", pct(s.ocr_error_rate), s.ocr_error_rate > 0.02)}
      ${card("Ошибки структуризации", pct(s.struct_error_rate), s.struct_error_rate > 0.02)}
      ${card("Галлюцинации", pct(s.hallucination_rate), s.hallucination_rate > 0.02)}
      ${card("Без участия человека (STP)", pct(s.stp_rate))}
      ${card("Время на документ", `${Math.round(s.avg_seconds_per_document)} с`)}
      ${card("Экономия оператора", `${(s.operator_seconds_saved_per_document / 60).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} мин`)}
      ${card("Токенов потрачено", Number(s.tokens).toLocaleString("ru-RU"))}
    </div>
    <p class="note">Сравнение с эталонной разметкой: документов ${s.documents}, полей ${s.fields}. Экономия посчитана из расчета ${Math.round(s.manual_seconds_per_document / 60)} мин ручной проверки на документ.</p>
    <table class="list">
      <thead><tr><th>Документ</th><th>Решение</th><th>Полей</th><th>Верно</th><th>OCR</th><th>Структура</th><th>Галлюц.</th><th>Время, с</th></tr></thead>
      <tbody>${report.documents.map((d) => `
        <tr>
          <td>${esc(d.document)}</td>
          <td><span class="badge ${d.status}">${statusLabel(d.status)}</span></td>
          <td class="num">${d.fields}</td>
          <td class="num">${d.correct || 0}</td>
          <td class="num">${d.ocr_error || 0}</td>
          <td class="num">${d.struct_error || 0}</td>
          <td class="num">${d.hallucinated || 0}</td>
          <td class="num">${d.seconds}</td>
        </tr>`).join("")}</tbody>
    </table>`;
}

async function loadMetrics() { renderMetrics(await api("/api/metrics")); }

$("#recompute").addEventListener("click", async () => {
  setStatus("Пересчитываю метрики…");
  try {
    renderMetrics(await api("/api/metrics", { method: "POST" }));
    showTab("metrics");
    setStatus("Метрики пересчитаны");
  } catch (error) {
    setStatus(`Ошибка: ${error.message}`);
  }
});

async function loadSamples() {
  const samples = await api("/api/samples");
  $("#samples").innerHTML = samples.map((s) => `
    <button class="task-link" data-sample="${esc(s.name)}"><span class="bullet">■</span><span class="name" title="${esc(s.name)}">${esc(s.name.replace(/\.pdf$/i, "").replace(/_/g, " "))}</span><small>${s.pages} стр.</small></button>`).join("");
  $$("[data-sample]").forEach((link) => link.addEventListener("click", () => {
    const fresh = $("#fresh-ocr").checked;
    runJob(link.dataset.sample, api(`/api/samples/${encodeURIComponent(link.dataset.sample)}/process?fresh_ocr=${fresh}`, { method: "POST" }));
  }));
}

const fileInput = $("#file-input");
["#open-file", "#open-file-2"].forEach((id) => $(id).addEventListener("click", () => fileInput.click()));
fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  runJob(file.name, api("/api/upload", { method: "POST", body }));
  fileInput.value = "";
});

let busy = false;

async function runJob(fileName, started) {
  if (busy) return;
  busy = true;
  const dialog = $("#progress-dialog");
  $("#progress-close").hidden = true;
  $("#progress-file").textContent = fileName;
  $("#progress-page").textContent = "";
  $("#progress-bar").style.width = "0";
  updateStage("render");
  openDialog(dialog);

  try {
    const { job_id: jobId } = await started;
    let job;
    do {
      await new Promise((r) => setTimeout(r, 700));
      job = await api(`/api/jobs/${jobId}`);
      if (job.state === "running") updateStage(job.stage, job.page, job.pages);
    } while (job.state === "running");

    if (job.state === "error") throw new Error(job.error);
    await finishJob(job);
  } catch (error) {
    $("#progress-img").src = icon("bad");
    $("#progress-stage").textContent = "Ревизия не удалась";
    $("#progress-page").textContent = error.message;
    $("#progress-close").hidden = false;
    say("Что-то пошло не так.", error.message, "bad");
    setStatus("Ошибка обработки");
  } finally {
    busy = false;
  }
}

function updateStage(stage, page = 0, pages = 0) {
  const info = STAGES[stage] || STAGES.render;
  $("#progress-img").src = icon(info.icon);
  $("#progress-stage").textContent = info.title;
  $("#progress-page").textContent = pages ? `Страница ${page} из ${pages}` : "";
  const done = pages ? ((page - 1) * 3 + info.step) / (pages * 3) : 0;
  $("#progress-bar").style.width = `${Math.max(4, done * 100)}%`;
  say(info.title, pages ? `Страница ${page} из ${pages}.` : "Минутку.", info.icon, true);
  setStatus(info.title);
}

async function finishJob(job) {
  $("#progress-bar").style.width = "100%";
  await loadDocuments();
  const processed = job.results.map((r) => documents.find((d) => d.source_file === job.file && d.page === r.page)).filter(Boolean);
  const bad = processed.filter((d) => d.status === "needs_review");
  closeDialog($("#progress-dialog"));

  if (bad.length) {
    say(`Нашел замечания: ${bad.length} из ${processed.length}.`,
      `${typeName(bad[0].document_type)}: ${bad[0].reason}`, verdictIcon(bad[0]));
  } else {
    say("Все чисто!", `Проверено страниц: ${processed.length}. Замечаний нет, документы одобрены.`, "good");
  }
  setStatus(`Готово: ${job.file}`);
  showTab("documents");
  if (processed.length) openDetails((bad[0] || processed[0]).id);
}

function renderTree(value, key = null, depth = 0) {
  const label = key === null ? "" : `<span class="k">${esc(key)}:</span> `;
  if (value && typeof value === "object") {
    const entries = Array.isArray(value) ? value.map((v, i) => [i, v]) : Object.entries(value);
    const size = Array.isArray(value) ? `[${value.length}]` : "{…}";
    if (!entries.length) return `<div class="leaf">${label}<span class="v-null">${Array.isArray(value) ? "[]" : "{}"}</span></div>`;
    return `<details ${depth < 2 ? "open" : ""}><summary>${label}<span class="muted">${size}</span></summary>${entries.map(([k, v]) => renderTree(v, k, depth + 1)).join("")}</details>`;
  }
  const cls = value === null ? "v-null" : typeof value === "number" ? "v-num" : "v-str";
  const text = value === null ? "null" : typeof value === "string" ? `«${value}»` : String(value);
  return `<div class="leaf">${label}<span class="${cls}">${esc(text)}</span></div>`;
}

function renderTrace(trace) {
  if (!trace.length) return `<div class="empty">Проверка не запускалась: документ не удалось разобрать.</div>`;
  return trace.map((step, i) => {
    const final = step.tool === "approve" || step.tool === "send_for_revision";
    const args = typeof step.arguments === "string" ? step.arguments : JSON.stringify(step.arguments, null, 0);
    return `
      <div class="trace-step${final ? " final" : ""}">
        <div class="call">${i + 1}. <b>${esc(step.tool)}</b>(${esc(args === "{}" ? "" : args)})</div>
        <pre>${esc(JSON.stringify(step.result, null, 2))}</pre>
      </div>`;
  }).join("");
}

async function openDetails(id) {
  const doc = await api(`/api/documents/${id}`);
  const verdict = verdictIcon(doc);
  const stats = doc.stats || {};
  const seconds = (stats.ocr_seconds || 0) + (stats.extract_seconds || 0) + (stats.agent_seconds || 0);
  const tokens = (stats.ocr_tokens || 0) + (stats.extract_tokens || 0) + (stats.agent_tokens || 0);
  const parties = (doc.data && doc.data.parties) || [];
  const totals = doc.data && doc.data.totals;

  $("#details-title").textContent = `Свойства: ${doc.source_file} — стр. ${doc.page}`;
  $("#address").innerHTML = `Ревизор ▸ ${TAB_TITLES[currentTab]} ▸ <b>${esc(doc.source_file)}, стр. ${doc.page}</b>`;

  $("#dtab-summary").innerHTML = `
    <div class="verdict">
      <img src="${icon(verdict)}" alt="">
      <div>
        <h3 class="${doc.status}">${doc.status === "approved" ? "Документ одобрен" : "Нужна проверка человеком"}</h3>
        <p>${esc(doc.reason)}</p>
        ${(doc.review_fields || []).length ? `<div class="chips">${doc.review_fields.map((f) => `<span class="chip">${esc(f)}</span>`).join("")}</div>` : ""}
      </div>
    </div>
    <hr class="groove">
    <dl class="props">
      <dt>Тип документа</dt><dd>${esc(typeName(doc.document_type))}</dd>
      <dt>Номер и дата</dt><dd>${esc(doc.data?.document_number || "—")}${doc.data?.document_date ? ` от ${esc(doc.data.document_date)}` : ""}</dd>
      <dt>Стороны</dt><dd>${parties.length ? parties.map((p) => `${esc(p.name)} <span class="muted">(${esc(p.role)}${p.inn ? `, ИНН ${esc(p.inn)}` : ""})</span>`).join("<br>") : "—"}</dd>
      <dt>Итого</dt><dd>${totals && totals.total != null ? `${money(totals.total)} ${esc(doc.data.currency || "")}` : "—"}</dd>
      <dt>Исправлено агентом</dt><dd>${Object.keys(doc.corrections || {}).length ? esc(JSON.stringify(doc.corrections)) : "ничего"}</dd>
      <dt>Обработка</dt><dd>${seconds.toFixed(1)} с · ${tokens.toLocaleString("ru-RU")} токенов · шагов агента: ${stats.agent_steps ?? "—"}</dd>
    </dl>`;

  $("#dtab-fields").innerHTML = `<div class="tree">${doc.data ? renderTree(doc.data) : '<div class="empty">Нет данных</div>'}</div>`;

  $("#dtab-checks").innerHTML = (doc.issues || []).length
    ? `<p class="note">Найденные ошибки:</p>${doc.issues.map((i) => `
        <div class="issue"><span class="code">${esc(ISSUE_CODES[i.code] || i.code)}</span><div>${esc(i.message)}<br><code>${esc(i.field)}</code></div></div>`).join("")}`
    : `<div class="empty">Ошибок в форматах, датах и суммах нет.${doc.status === "needs_review" ? "<br>Реквизиты расходятся со справочником, подробности на вкладке «Ход проверки»." : ""}</div>`;

  $("#dtab-trace").innerHTML = renderTrace(doc.agent_trace || []);
  $("#dtab-ocr").innerHTML = doc.ocr_text ? `<pre class="ocr">${esc(doc.ocr_text)}</pre>` : `<div class="empty">Текст OCR не найден</div>`;
  $("#dtab-scan").innerHTML = doc.has_image ? `<img class="scan" alt="Скан страницы" loading="lazy" src="/api/documents/${id}/image">` : `<div class="empty">Исходный PDF не найден</div>`;

  showDetailsTab("summary");
  openDialog($("#details-dialog"));
}

function showDetailsTab(name) {
  $$("#details-tabs .tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.dtab === name)));
  $$("#details-dialog .tabpanel").forEach((p) => { p.hidden = p.id !== `dtab-${name}`; });
}
$$("#details-tabs .tab").forEach((tab) => tab.addEventListener("click", () => showDetailsTab(tab.dataset.dtab)));

function openDialog(dialog) {
  dialog.hidden = false;
  const rect = dialog.getBoundingClientRect();
  dialog.style.left = `${Math.max(8, (innerWidth - rect.width) / 2)}px`;
  dialog.style.top = `${Math.max(8, (innerHeight - 34 - rect.height) / 2)}px`;
  const focusable = dialog.querySelector(".btn.default, .btn:not([hidden])");
  if (focusable) focusable.focus();
}

function closeDialog(dialog) {
  dialog.hidden = true;
  if (dialog.id === "details-dialog") {
    $("#address").innerHTML = `Ревизор ▸ <b>${TAB_TITLES[currentTab]}</b>`;
  }
}

$$("[data-close]").forEach((button) => button.addEventListener("click", () => closeDialog($(`#${button.dataset.close}`))));
$("#progress-close").addEventListener("click", () => closeDialog($("#progress-dialog")));
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  ["#details-dialog", "#about-dialog"].forEach((id) => { if (!$(id).hidden) closeDialog($(id)); });
});

$$(".dialog .titlebar").forEach((bar) => {
  bar.addEventListener("pointerdown", (event) => {
    if (event.target.closest("button")) return;
    const dialog = bar.closest(".dialog");
    const startX = event.clientX - dialog.offsetLeft;
    const startY = event.clientY - dialog.offsetTop;
    const move = (e) => {
      dialog.style.left = `${Math.min(innerWidth - 80, Math.max(0, e.clientX - startX))}px`;
      dialog.style.top = `${Math.min(innerHeight - 60, Math.max(0, e.clientY - startY))}px`;
    };
    const stop = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", stop); };
    addEventListener("pointermove", move);
    addEventListener("pointerup", stop);
  });
});

$$(".panel-toggle").forEach((toggle) => toggle.addEventListener("click", () => {
  toggle.setAttribute("aria-expanded", String(toggle.getAttribute("aria-expanded") !== "true"));
}));

$("#refresh").addEventListener("click", async () => {
  await loadDocuments();
  if (currentTab === "registry") await loadRegistry();
  if (currentTab === "metrics") await loadMetrics();
  setStatus("Обновлено");
});

const openAbout = () => openDialog($("#about-dialog"));
$("#about").addEventListener("click", openAbout);
$("#start").addEventListener("click", openAbout);

function tick() {
  $("#clock").textContent = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

async function init() {
  tick();
  setInterval(tick, 15000);
  try {
    const status = await api("/api/status");
    $("#status-model").textContent = status.model;
    $("#db-dot").className = `dot ${status.database ? "on" : "off"}`;
    if (!status.database) say("Нет связи с базой.", "Справочник и история проверок сейчас недоступны.", "bad");
    await Promise.all([loadSamples(), loadDocuments()]);
  } catch (error) {
    say("Не удалось загрузиться.", error.message, "bad");
  }
}

init();
