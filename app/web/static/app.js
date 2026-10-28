"use strict";

const PHASE_NAMES = {
  preprocess: "Preproceso",
  ingest: "Ingesta",
  triage: "Triage",
  rca: "Causa Raiz",
  resolution: "Resolucion",
  communication: "Comunicacion",
};

const PHASE_ORDER = ["preprocess", "ingest", "triage", "rca", "resolution", "communication"];

let selectedFiles = [];
let currentCaseId = null;
let eventSource = null;

// ---------------------------------------------------------------------------
// Drag & drop
// ---------------------------------------------------------------------------

const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const fileList = document.getElementById("file-list");

dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  handleFiles(e.dataTransfer.files);
});
fileInput.addEventListener("change", () => handleFiles(fileInput.files));

function handleFiles(files) {
  for (const f of files) {
    const ext = f.name.split(".").pop().toLowerCase();
    if (ext !== "log" && ext !== "txt") {
      alert("Solo se permiten archivos .log y .txt");
      continue;
    }
    selectedFiles.push(f);
  }
  renderFileList();
  fileInput.value = "";
}

function renderFileList() {
  fileList.innerHTML = "";
  selectedFiles.forEach((f, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>${f.name} (${(f.size / 1024).toFixed(1)} KB)</span>`;
    const rm = document.createElement("span");
    rm.className = "remove";
    rm.textContent = "x";
    rm.onclick = () => { selectedFiles.splice(i, 1); renderFileList(); };
    li.appendChild(rm);
    fileList.appendChild(li);
  });
}

// ---------------------------------------------------------------------------
// Submit form
// ---------------------------------------------------------------------------

const form = document.getElementById("case-form");
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (selectedFiles.length === 0) {
    alert("Selecciona al menos un archivo de log");
    return;
  }

  const fd = new FormData();
  selectedFiles.forEach((f) => fd.append("files", f));
  fd.append("ticket_id", document.getElementById("ticket_id").value);
  fd.append("application", document.getElementById("application").value);
  fd.append("description", document.getElementById("description").value);
  fd.append("recent_changes", document.getElementById("recent_changes").value);
  fd.append("environment", document.getElementById("environment").value);
  fd.append("business_rules", document.getElementById("business_rules").value);

  const btn = document.getElementById("submit-btn");
  btn.disabled = true;
  btn.textContent = "Creando...";

  try {
    const resp = await fetch("/cases", { method: "POST", body: fd });
    const data = await resp.json();
    if (!resp.ok) {
      alert("Error: " + (data.error || "desconocido") + "\n" + (data.detail || ""));
      return;
    }
    currentCaseId = data.case_id;
    document.getElementById("case-id-display").textContent = currentCaseId;
    document.getElementById("progress-section").classList.remove("hidden");
    document.getElementById("form-section").classList.add("hidden");
    document.getElementById("stop-btn").style.display = "inline-block";
    startRun(currentCaseId);
  } catch (err) {
    alert("Error de red: " + err);
  } finally {
    btn.disabled = false;
    btn.textContent = "Analizar";
  }
});

// ---------------------------------------------------------------------------
// Run case
// ---------------------------------------------------------------------------

async function startRun(caseId) {
  try {
    const resp = await fetch(`/cases/${caseId}/run`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) {
      showError(data.error + ": " + (data.detail || ""));
      return;
    }
    document.getElementById("stop-btn").style.display = "inline-block";
    connectSSE(caseId);
  } catch (err) {
    showError("Error: " + err);
  }
}

// ---------------------------------------------------------------------------
// Stop case
// ---------------------------------------------------------------------------

document.getElementById("stop-btn").addEventListener("click", async () => {
  if (!currentCaseId) return;
  if (!confirm("Detener el analisis del caso " + currentCaseId + "?")) return;
  try {
    const resp = await fetch(`/cases/${currentCaseId}/stop`, { method: "POST" });
    if (resp.ok) {
      if (eventSource) { eventSource.close(); eventSource = null; }
      document.getElementById("stop-btn").style.display = "none";
      updatePhasesFromServer();
      showError("Analisis detenido. Puedes reanudar desde la ultima fase exitosa.");
    }
  } catch (err) {
    alert("Error al detener: " + err);
  }
});

// ---------------------------------------------------------------------------
// SSE
// ---------------------------------------------------------------------------

function connectSSE(caseId) {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/cases/${caseId}/events`);

  eventSource.onmessage = (e) => {
    let ev;
    try { ev = JSON.parse(e.data); } catch { return; }
    handleEvent(ev);
  };

  eventSource.onerror = () => {
    // Reconnect might happen automatically; if not, poll
  };
}

function handleEvent(ev) {
  if (ev.phase === "done") {
    document.getElementById("stop-btn").style.display = "none";
    updatePhasesFromServer();
    if (ev.status === "completed" || ev.status === "failed") {
      showResults(ev.status);
    }
    return;
  }
  if (ev.phase === "error") {
    document.getElementById("stop-btn").style.display = "none";
    showError(ev.message || "Error desconocido");
    return;
  }
  if (ev.phase === "stopped") {
    document.getElementById("stop-btn").style.display = "none";
    updatePhasesFromServer();
    showError("Analisis detenido por el usuario");
    return;
  }

  const item = document.querySelector(`.phase-item[data-phase="${ev.phase}"]`);
  if (item) {
    const statusEl = item.querySelector(".phase-status");
    statusEl.className = "phase-status badge-" + ev.status;
    statusEl.textContent = statusLabel(ev.status);
    const metaEl = item.querySelector(".phase-meta");
    let meta = ev.message || "";
    if (ev.percent) meta += ` (${ev.percent}%)`;
    metaEl.textContent = meta;
  }
}

function statusLabel(s) {
  const labels = {
    pending: "pendiente", running: "en curso", ok: "ok",
    degraded: "degradado", failed: "error", skipped: "omitido",
    waiting: "esperando", "": "",
  };
  return labels[s] || s;
}

// ---------------------------------------------------------------------------
// Poll case status
// ---------------------------------------------------------------------------

async function updatePhasesFromServer() {
  if (!currentCaseId) return;
  try {
    const resp = await fetch(`/cases/${currentCaseId}`);
    if (!resp.ok) return;
    const data = await resp.json();

    for (const name of PHASE_ORDER) {
      const ph = data.phases[name];
      if (!ph) continue;
      const item = document.querySelector(`.phase-item[data-phase="${name}"]`);
      if (!item) continue;
      const statusEl = item.querySelector(".phase-status");
      statusEl.className = "phase-status badge-" + ph.status;
      statusEl.textContent = statusLabel(ph.status);
      const metaEl = item.querySelector(".phase-meta");
      let meta = "";
      if (ph.duration) meta += `${ph.duration.toFixed(2)}s`;
      if (ph.tokens && ph.tokens.total) meta += ` | ${ph.tokens.total} tokens`;
      if (ph.error) meta += ` | ${ph.error}`;
      metaEl.textContent = meta;
    }

    if (data.needs_review) {
      showReviewPanel(data);
    } else if (data.status === "completed" || data.status === "failed") {
      showResults(data.status);
    }
  } catch {}
}

// ---------------------------------------------------------------------------
// Review panel
// ---------------------------------------------------------------------------

function showReviewPanel(data) {
  const panel = document.getElementById("review-panel");
  panel.classList.remove("hidden");
  const hyp = document.getElementById("review-hypothesis");
  if (data.top_hypothesis) {
    hyp.innerHTML = `
      <p><strong>Causa probable:</strong> ${data.top_hypothesis.root_cause || ""}</p>
      <p><strong>Hipotesis:</strong> ${data.top_hypothesis.title || ""} 
      <span class="badge badge-${data.top_hypothesis.confidence === "High" ? "ok" : data.top_hypothesis.confidence === "Medium" ? "degraded" : "failed"}">${data.top_hypothesis.confidence || ""}</span></p>
    `;
  }
}

document.getElementById("approve-btn").addEventListener("click", async () => {
  const comment = document.getElementById("review-comment").value;
  const fd = new FormData();
  fd.append("approved", "true");
  fd.append("comment", comment);
  try {
    const resp = await fetch(`/cases/${currentCaseId}/review`, { method: "POST", body: fd });
    if (resp.ok) {
      document.getElementById("review-panel").classList.add("hidden");
      connectSSE(currentCaseId);
    }
  } catch (err) {
    showError("Error: " + err);
  }
});

document.getElementById("reject-btn").addEventListener("click", async () => {
  const comment = document.getElementById("review-comment").value;
  const fd = new FormData();
  fd.append("approved", "false");
  fd.append("comment", comment);
  try {
    const resp = await fetch(`/cases/${currentCaseId}/review`, { method: "POST", body: fd });
    if (resp.ok) {
      document.getElementById("review-panel").classList.add("hidden");
      updatePhasesFromServer();
      showResults("failed");
    }
  } catch (err) {
    showError("Error: " + err);
  }
});

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

function showResults(status) {
  if (status === "failed") {
    showError("El caso termino con error. Revisa el estado de las fases.");
    return;
  }
  const links = document.getElementById("result-links");
  links.classList.remove("hidden");
  document.getElementById("report-link").href = `/cases/${currentCaseId}/report`;
  document.getElementById("export-link").href = `/cases/${currentCaseId}/export`;
}

function showError(msg) {
  const el = document.getElementById("error-message");
  el.textContent = msg;
  el.classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// Cases list
// ---------------------------------------------------------------------------

document.getElementById("refresh-cases").addEventListener("click", loadCases);

async function loadCases() {
  try {
    const resp = await fetch("/cases");
    if (!resp.ok) return;
    const data = await resp.json();
    const tbody = document.getElementById("cases-tbody");
    tbody.innerHTML = "";
    for (const c of data.cases || []) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${c.case_id}</td>
        <td>${c.ticket_id || ""}</td>
        <td>${c.application || ""}</td>
        <td><span class="phase-status badge-${c.status === "completed" ? "ok" : c.status === "running" ? "running" : c.status === "failed" ? "failed" : c.status === "waiting_review" ? "waiting" : "pending"}">${c.status}</span></td>
        <td>${c.severity || ""}</td>
        <td>${c.created_at || ""}</td>
        <td>
          <a class="action-link" onclick="viewCase('${c.case_id}')">Ver</a>
          ${c.status === "completed" || c.status === "degraded" ? `| <a class="action-link" href="/cases/${c.case_id}/report" target="_blank">Reporte</a>` : ""}
          ${c.status === "failed" || c.status === "created" ? `| <a class="action-link" onclick="rerunCase('${c.case_id}')">${c.status === "failed" ? "Reanudar" : "Ejecutar"}</a>` : ""}
          | <a class="action-link action-danger" onclick="deleteCase('${c.case_id}')">Borrar</a>
        </td>
      `;
      tbody.appendChild(tr);
    }
  } catch {}
}

window.viewCase = function(caseId) {
  window.open(`/cases/${caseId}/report`, "_blank");
};

window.rerunCase = async function(caseId) {
  if (!confirm("Re-ejecutar el caso " + caseId + "?")) return;
  try {
    const resp = await fetch(`/cases/${caseId}/run`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) {
      alert("Error: " + (data.error || "") + "\n" + (data.detail || ""));
      return;
    }
    currentCaseId = caseId;
    document.getElementById("case-id-display").textContent = caseId;
    document.getElementById("progress-section").classList.remove("hidden");
    document.getElementById("form-section").classList.add("hidden");
    document.getElementById("result-links").classList.add("hidden");
    document.getElementById("error-message").classList.add("hidden");
    document.getElementById("review-panel").classList.add("hidden");
    document.getElementById("stop-btn").style.display = "inline-block";
    for (const name of PHASE_ORDER) {
      const item = document.querySelector(`.phase-item[data-phase="${name}"]`);
      if (item) {
        item.querySelector(".phase-status").className = "phase-status badge-pending";
        item.querySelector(".phase-status").textContent = "pendiente";
        item.querySelector(".phase-meta").textContent = "";
      }
    }
    connectSSE(caseId);
  } catch (err) {
    alert("Error: " + err);
  }
};

window.deleteCase = async function(caseId) {
  if (!confirm("Borrar el caso " + caseId + "? Esta accion no se puede deshacer.")) return;
  try {
    const resp = await fetch(`/cases/${caseId}`, { method: "DELETE" });
    if (!resp.ok) {
      const data = await resp.json();
      alert("Error: " + (data.error || "") + "\n" + (data.detail || ""));
      return;
    }
    loadCases();
  } catch (err) {
    alert("Error: " + err);
  }
};

// Load cases on startup
loadCases();
