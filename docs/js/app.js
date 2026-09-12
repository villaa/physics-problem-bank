const state = {
  problems: [],
  filtered: [],
  worksheet: new Set(),
};

const grid = document.getElementById("grid");
const emptyState = document.getElementById("empty");
const searchInput = document.getElementById("search");
const subjectFilter = document.getElementById("subject-filter");
const difficultyFilter = document.getElementById("difficulty-filter");
const tray = document.getElementById("tray");
const trayCount = document.getElementById("tray-count");
const overlay = document.getElementById("overlay");
const modal = document.getElementById("modal");

async function loadProblems() {
  const res = await fetch("data/problems.json");
  state.problems = await res.json();
  populateSubjects();
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

function applyFilters() {
  const q = searchInput.value.trim().toLowerCase();
  const subject = subjectFilter.value;
  const difficulty = difficultyFilter.value;

  state.filtered = state.problems.filter((p) => {
    if (subject && p.subject !== subject) return false;
    if (difficulty && p.difficulty !== difficulty) return false;
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
    lock.textContent = p.protected ? "🔒 key required" : "";
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

function openDetail(problem) {
  overlay.hidden = false;
  if (problem.protected) {
    renderLockedDetail(problem);
  } else {
    renderUnlockedDetail(problem, problem.statement_pdf, problem.solutions);
  }
}

function renderLockedDetail(problem) {
  modal.innerHTML = `
    <div class="modal-header">
      <div>
        <h2>${escapeHtml(problem.topic)}</h2>
        <div style="color:var(--text-dim)">${escapeHtml(problem.subject)} · ${escapeHtml(problem.difficulty)}</div>
      </div>
      <button class="modal-close" id="close-btn">&times;</button>
    </div>
    <p>🔒 This problem requires an access key from your instructor.</p>
    <div class="unlock-box">
      <input type="text" id="key-input" placeholder="Enter access key" />
      <button id="unlock-btn">Unlock</button>
    </div>
    <div id="unlock-error" class="error-text"></div>
  `;
  modal.querySelector("#close-btn").addEventListener("click", closeDetail);
  modal.querySelector("#unlock-btn").addEventListener("click", () =>
    unlockProblem(problem)
  );
}

async function unlockProblem(problem) {
  const key = modal.querySelector("#key-input").value.trim();
  const errorEl = modal.querySelector("#unlock-error");
  errorEl.textContent = "";
  if (!key) {
    errorEl.textContent = "Enter a key first.";
    return;
  }
  try {
    const statementUrl = `${CONFIG.WORKER_URL}/problem/${encodeURIComponent(
      problem.id
    )}/statement.pdf?key=${encodeURIComponent(key)}`;
    const res = await fetch(statementUrl);
    if (!res.ok) {
      errorEl.textContent = res.status === 403 ? "Incorrect key." : "Could not load problem.";
      return;
    }
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);

    const solutions = (problem.solutions || []).map((s) => ({
      method: s.method,
      // solution files fetched lazily per-tab, same key reused
      fetchUrl: `${CONFIG.WORKER_URL}/problem/${encodeURIComponent(
        problem.id
      )}/${encodeURIComponent(s.pdf)}?key=${encodeURIComponent(key)}`,
    }));

    renderUnlockedDetail(problem, blobUrl, solutions, true);
  } catch (err) {
    errorEl.textContent = "Network error reaching the key server.";
  }
}

function renderUnlockedDetail(problem, statementSrc, solutions, isProtectedBlob = false) {
  modal.innerHTML = `
    <div class="modal-header">
      <div>
        <h2>${escapeHtml(problem.topic)}</h2>
        <div style="color:var(--text-dim)">${escapeHtml(problem.subject)} · ${escapeHtml(problem.difficulty)}</div>
      </div>
      <button class="modal-close" id="close-btn">&times;</button>
    </div>
    <div class="tabs" id="tabs"></div>
    <iframe class="pdf-frame" id="pdf-frame" src="${statementSrc}"></iframe>
  `;
  modal.querySelector("#close-btn").addEventListener("click", closeDetail);

  const tabs = modal.querySelector("#tabs");
  const frame = modal.querySelector("#pdf-frame");

  const statementBtn = document.createElement("button");
  statementBtn.className = "tab-btn active";
  statementBtn.textContent = "Problem statement";
  statementBtn.addEventListener("click", () => {
    setActiveTab(statementBtn);
    frame.src = statementSrc;
  });
  tabs.appendChild(statementBtn);

  for (const sol of solutions || []) {
    const btn = document.createElement("button");
    btn.className = "tab-btn";
    btn.textContent = sol.method;
    btn.addEventListener("click", async () => {
      setActiveTab(btn);
      if (isProtectedBlob) {
        const res = await fetch(sol.fetchUrl);
        if (res.ok) {
          const blob = await res.blob();
          frame.src = URL.createObjectURL(blob);
        }
      } else {
        frame.src = sol.pdf;
      }
    });
    tabs.appendChild(btn);
  }

  function setActiveTab(activeBtn) {
    tabs.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    activeBtn.classList.add("active");
  }
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

  const unprotectedSelected = selected.filter((p) => !p.protected);
  const skippedProtected = selected.length - unprotectedSelected.length;

  const statementDoc = await PDFLib.PDFDocument.create();
  const answerDoc = await PDFLib.PDFDocument.create();

  for (const p of unprotectedSelected) {
    await appendPdf(statementDoc, p.statement_pdf);
    for (const sol of p.solutions || []) {
      await appendPdf(answerDoc, sol.pdf);
    }
  }

  await downloadPdf(statementDoc, "worksheet-problems.pdf");
  await downloadPdf(answerDoc, "worksheet-answer-key.pdf");

  if (skippedProtected > 0) {
    alert(
      `${skippedProtected} protected problem(s) were skipped from the worksheet. ` +
        `Unlock them individually and add their PDFs by hand.`
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
