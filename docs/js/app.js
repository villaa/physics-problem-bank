const state = {
  problems: [],
  filtered: [],
  worksheet: new Set(),
  activeTags: new Set(),
};

const grid = document.getElementById("grid");
const emptyState = document.getElementById("empty");
const searchInput = document.getElementById("search");
const subjectFilter = document.getElementById("subject-filter");
const difficultyFilter = document.getElementById("difficulty-filter");
const tagFilter = document.getElementById("tag-filter");
const tray = document.getElementById("tray");
const trayCount = document.getElementById("tray-count");
const overlay = document.getElementById("overlay");
const modal = document.getElementById("modal");

async function loadProblems() {
  const res = await fetch("data/problems.json");
  state.problems = await res.json();
  populateSubjects();
  populateTags();
  applyFilters();
}

function populateSubjects() {
  const subjects = [...new Set(state.problems.map((p) => p.subject))].sort();
  for (const s of subjects) {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    subjectFilter.appendChild(opt);
  }
}

function populateTags() {
  const tags = [...new Set(state.problems.flatMap((p) => p.tags || []))].sort();
  tagFilter.innerHTML = "";
  for (const t of tags) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "tag-chip";
    chip.textContent = t;
    chip.addEventListener("click", () => {
      if (state.activeTags.has(t)) state.activeTags.delete(t);
      else state.activeTags.add(t);
      chip.classList.toggle("active");
      applyFilters();
    });
    tagFilter.appendChild(chip);
  }
}

function applyFilters() {
  const q = searchInput.value.trim().toLowerCase();
  const subject = subjectFilter.value;
  const difficulty = difficultyFilter.value;

  state.filtered = state.problems.filter((p) => {
    if (subject && p.subject !== subject) return false;
    if (difficulty && p.difficulty !== difficulty) return false;
    if (state.activeTags.size && !(p.tags || []).some((t) => state.activeTags.has(t))) {
      return false;
    }
    if (q) {
      const haystack = [p.id, p.subject, p.topic, p.source, ...(p.tags || [])]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });
  render();
}

function render() {
  grid.innerHTML = "";
  emptyState.hidden = state.filtered.length > 0;

  for (const p of state.filtered) {
    const card = document.createElement("div");
    card.className = "card";

    const top = document.createElement("div");
    top.className = "card-top";
    top.innerHTML = `
      <h3>${escapeHtml(p.topic)}</h3>
      <span class="badge">${escapeHtml(p.difficulty)}</span>
    `;
    card.appendChild(top);

    const subjectLine = document.createElement("div");
    subjectLine.textContent = p.subject;
    subjectLine.style.color = "var(--text-dim)";
    subjectLine.style.fontSize = "0.85rem";
    card.appendChild(subjectLine);

    const tags = document.createElement("div");
    tags.className = "tags";
    tags.innerHTML = (p.tags || [])
      .map((t) => `<span class="tag">${escapeHtml(t)}</span>`)
      .join("");
    card.appendChild(tags);

    const footer = document.createElement("div");
    footer.className = "card-footer";

    const lock = document.createElement("span");
    lock.className = "lock-icon";
    lock.textContent = p.protected ? "🔒 solutions locked" : "";
    footer.appendChild(lock);

    const label = document.createElement("label");
    label.className = "worksheet-toggle";
    label.innerHTML = `<input type="checkbox" data-id="${p.id}" ${
      state.worksheet.has(p.id) ? "checked" : ""
    } /> worksheet`;
    label.addEventListener("click", (e) => e.stopPropagation());
    label.querySelector("input").addEventListener("change", (e) => {
      if (e.target.checked) state.worksheet.add(p.id);
      else state.worksheet.delete(p.id);
      updateTray();
    });
    footer.appendChild(label);

    card.appendChild(footer);
    card.addEventListener("click", () => openDetail(p));
    grid.appendChild(card);
  }
}

function updateTray() {
  const n = state.worksheet.size;
  tray.hidden = n === 0;
  trayCount.textContent = `${n} selected`;
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

// ---- Detail modal ----

function publicPdfUrl(problem, relPath) {
  return `problems/${problem.id}/${relPath}`;
}

function openDetail(problem) {
  overlay.hidden = false;
  // The statement is always public, protected or not - only solutions
  // ever require a key.
  const statementUrl = publicPdfUrl(problem, problem.statement_pdf);

  modal.innerHTML = `
    <div class="modal-header">
      <div>
        <h2>${escapeHtml(problem.topic)}</h2>
        <div style="color:var(--text-dim)">${escapeHtml(problem.subject)} · ${escapeHtml(problem.difficulty)}</div>
      </div>
      <button class="modal-close" id="close-btn">&times;</button>
    </div>
    <div class="tabs" id="tabs"></div>
    <iframe class="pdf-frame" id="pdf-frame" src="${statementUrl}"></iframe>
    <div id="lock-area"></div>
  `;
  modal.querySelector("#close-btn").addEventListener("click", closeDetail);

  const tabs = modal.querySelector("#tabs");
  const frame = modal.querySelector("#pdf-frame");

  const statementBtn = document.createElement("button");
  statementBtn.className = "tab-btn active";
  statementBtn.textContent = "Problem statement";
  statementBtn.addEventListener("click", () => {
    setActiveTab(tabs, statementBtn);
    frame.src = statementUrl;
  });
  tabs.appendChild(statementBtn);

  if (problem.protected) {
    renderLockArea(problem, tabs, frame);
  } else {
    for (const sol of problem.solutions || []) {
      addSolutionTab(tabs, frame, sol.method, publicPdfUrl(problem, sol.pdf));
    }
  }
}

function addSolutionTab(tabs, frame, method, src) {
  const btn = document.createElement("button");
  btn.className = "tab-btn";
  btn.textContent = method;
  btn.addEventListener("click", () => {
    setActiveTab(tabs, btn);
    frame.src = src;
  });
  tabs.appendChild(btn);
}

function setActiveTab(tabs, activeBtn) {
  tabs.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
  activeBtn.classList.add("active");
}

function renderLockArea(problem, tabs, frame) {
  const lockArea = modal.querySelector("#lock-area");
  lockArea.innerHTML = `
    <p style="margin-top:16px;">🔒 Solutions require a one-time key from your instructor.</p>
    <div class="unlock-box">
      <input type="text" id="key-input" placeholder="Enter your one-time key" />
      <button id="unlock-btn">Unlock solutions</button>
    </div>
    <div id="unlock-error" class="error-text"></div>
  `;
  lockArea.querySelector("#unlock-btn").addEventListener("click", () =>
    unlockSolutions(problem, tabs, frame, lockArea)
  );
}

async function unlockSolutions(problem, tabs, frame, lockArea) {
  const key = lockArea.querySelector("#key-input").value.trim();
  const errorEl = lockArea.querySelector("#unlock-error");
  errorEl.textContent = "";
  if (!key) {
    errorEl.textContent = "Enter a key first.";
    return;
  }

  const files = (problem.solutions || []).map((s) => s.pdf);
  try {
    const res = await fetch(
      `${CONFIG.WORKER_URL}/problem/${encodeURIComponent(problem.id)}/redeem`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, files }),
      }
    );
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      errorEl.textContent =
        data.error === "expired_key"
          ? "This key has expired - ask your instructor for a new one."
          : res.status === 403
          ? "Incorrect key, or it's already been used - keys work once."
          : res.status === 404
          ? "No keys are available for this problem yet."
          : "Could not reach the key server.";
      return;
    }
    const data = await res.json();

    lockArea.innerHTML =
      '<p style="color:var(--text-dim); margin-top:16px;">Solutions unlocked for this session.</p>';

    for (const sol of problem.solutions || []) {
      const base64 = data.files && data.files[sol.pdf];
      if (!base64) continue;
      addSolutionTab(tabs, frame, sol.method, base64ToBlobUrl(base64));
    }
  } catch (err) {
    errorEl.textContent = "Network error reaching the key server.";
  }
}

function base64ToBlobUrl(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
}

function closeDetail() {
  overlay.hidden = true;
  modal.innerHTML = "";
}

overlay.addEventListener("click", (e) => {
  if (e.target === overlay) closeDetail();
});

// ---- Worksheet builder ----

document.getElementById("tray-clear").addEventListener("click", () => {
  state.worksheet.clear();
  updateTray();
  render();
});

document.getElementById("tray-build").addEventListener("click", buildWorksheet);

async function buildWorksheet() {
  const selected = state.problems.filter((p) => state.worksheet.has(p.id));
  if (selected.length === 0) return;

  // Statements are always public, so every selected problem contributes
  // one - only a protected problem's solutions need a per-student key,
  // so those are left out of the shared answer-key packet.
  const protectedSelected = selected.filter((p) => p.protected);

  const statementDoc = await PDFLib.PDFDocument.create();
  const answerDoc = await PDFLib.PDFDocument.create();

  for (const p of selected) {
    await appendPdf(statementDoc, publicPdfUrl(p, p.statement_pdf));
    if (!p.protected) {
      for (const sol of p.solutions || []) {
        await appendPdf(answerDoc, publicPdfUrl(p, sol.pdf));
      }
    }
  }

  await downloadPdf(statementDoc, "worksheet-problems.pdf");
  await downloadPdf(answerDoc, "worksheet-answer-key.pdf");

  if (protectedSelected.length > 0) {
    alert(
      `${protectedSelected.length} problem(s) have key-protected solutions - ` +
        `their statements are included above, but their answer keys need to be unlocked individually.`
    );
  }
}

async function appendPdf(targetDoc, url) {
  const bytes = await fetch(url).then((r) => r.arrayBuffer());
  const srcDoc = await PDFLib.PDFDocument.load(bytes);
  const pages = await targetDoc.copyPages(srcDoc, srcDoc.getPageIndices());
  pages.forEach((page) => targetDoc.addPage(page));
}

async function downloadPdf(doc, filename) {
  if (doc.getPageCount() === 0) return;
  const bytes = await doc.save();
  const blob = new Blob([bytes], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ---- Wire up filters ----

searchInput.addEventListener("input", applyFilters);
subjectFilter.addEventListener("change", applyFilters);
difficultyFilter.addEventListener("change", applyFilters);

loadProblems();
