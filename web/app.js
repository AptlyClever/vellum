const $ = (id) => document.getElementById(id);

function formatDeadline(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return (
      d.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "America/Los_Angeles",
      }) + " PT"
    );
  } catch {
    return String(iso);
  }
}

function makePill(window) {
  const span = document.createElement("span");
  const kind = window === "open" || window === "expired" ? window : "unknown";
  span.className = `pill ${kind}`;
  span.textContent =
    kind === "open" ? "Open" : kind === "expired" ? "Expired" : "Unknown";
  return span;
}

function makeAvailabilityCell(av) {
  const cell = document.createElement("td");
  cell.className = "availability";
  const state = (av && av.state) || "need_download";
  const label = (av && av.label) || "Need download";
  const detail = (av && av.detail) || "";
  const pill = document.createElement("span");
  pill.className = `pill avail-${state}`;
  pill.textContent = label;
  cell.appendChild(pill);
  if (detail) {
    const sub = document.createElement("span");
    sub.className = "deadline";
    sub.textContent = detail;
    cell.appendChild(sub);
  }
  return cell;
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json();
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

let captureWatchTimer = null;

function stopCaptureWatch() {
  if (captureWatchTimer != null) {
    clearInterval(captureWatchTimer);
    captureWatchTimer = null;
  }
}

function humanPhaseFromProgressLog(log) {
  const messages = [];
  for (const line of String(log || "").split("\n")) {
    if (line.startsWith("  |") || line.trim() === "---" || !line.trim()) continue;
    const bar = line.indexOf(" | ");
    if (bar < 0) continue;
    messages.push(line.slice(bar + 3).trim());
  }
  return messages.length ? messages[messages.length - 1] : "Waiting for agent…";
}

function recentPhasesFromProgressLog(log, limit = 8) {
  const messages = [];
  for (const line of String(log || "").split("\n")) {
    if (line.startsWith("  |") || line.trim() === "---" || !line.trim()) continue;
    const bar = line.indexOf(" | ");
    if (bar < 0) continue;
    const msg = line.slice(bar + 3).trim();
    if (!msg) continue;
    if (messages.length && messages[messages.length - 1] === msg) continue;
    messages.push(msg);
  }
  return messages.slice(-limit);
}

function renderLookdevGrid(lookdevHost, outputs, { emptyText, limit = 24 } = {}) {
  clear(lookdevHost);
  const list = Array.isArray(outputs) ? outputs : [];
  if (!list.length) {
    const empty = document.createElement("p");
    empty.className = "fit";
    empty.textContent =
      emptyText ||
      "No derived stills yet. Requires staged pack with png/jpg textures.";
    lookdevHost.appendChild(empty);
    return;
  }
  for (const out of list.slice(0, limit)) {
    const card = document.createElement("figure");
    card.className = "lookdev-card";
    if (out.kind === "niagara-render") card.classList.add("lookdev-card-live");
    const img = document.createElement("img");
    img.src = `/api/lookdev/outputs/${encodeURIComponent(out.id)}/file`;
    img.alt = `${out.lane} ${out.kind}`;
    img.loading = "lazy";
    card.appendChild(img);
    const cap = document.createElement("figcaption");
    const note = (out.note || "").replace(/\s+/g, " ").trim();
    const shortNote =
      note.length > 42 ? `${note.slice(0, 40)}…` : note;
    cap.textContent = shortNote
      ? `${out.lane} · ${shortNote}`
      : `${out.lane} · ${out.kind}`;
    card.appendChild(cap);

    const actions = document.createElement("div");
    actions.className = "lookdev-attach-actions";
    const targets = [
      { id: "hail", label: "Use in Hail" },
      { id: "lcard", label: "Use in LCARD" },
      { id: "bandit", label: "Use in Bandit" },
    ];
    for (const t of targets) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-secondary btn-tiny";
      btn.textContent = t.label;
      btn.onclick = async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        btn.disabled = true;
        const prev = btn.textContent;
        btn.textContent = "Attaching…";
        try {
          const res = await fetch("/api/attach", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              derived_output_id: out.id,
              target: t.id,
              register_glyph: true,
            }),
          });
          const body = await res.json().catch(() => ({}));
          if (!res.ok) {
            throw new Error(body.detail || res.statusText || "attach_failed");
          }
          const att = body.attachment || body;
          btn.textContent = "Attached";
          if (att.deep_link) {
            window.open(att.deep_link, "_blank", "noopener");
          }
        } catch (err) {
          btn.disabled = false;
          btn.textContent = prev;
          alert(`Attach failed: ${err.message || err}`);
          console.error(err);
        }
      };
      actions.appendChild(btn);
    }
    card.appendChild(actions);
    lookdevHost.appendChild(card);
  }
}

function startCaptureWatch({
  assetId,
  jobId,
  liveRoot,
  phaseEl,
  metaEl,
  feedEl,
  lookdevHost,
  captureBtn,
  cancelBtn,
  onIdle,
}) {
  stopCaptureWatch();
  liveRoot.hidden = false;
  let lastOutputCount = -1;
  let ticksAfterDone = 0;
  let watchingJobId = jobId;

  if (cancelBtn) {
    cancelBtn.hidden = false;
    cancelBtn.disabled = false;
    cancelBtn.onclick = async () => {
      cancelBtn.disabled = true;
      cancelBtn.textContent = "Cancelling…";
      try {
        await cancelJob(watchingJobId, "operator_cancelled");
        phaseEl.textContent = "Cancelled — you can start Capture again";
        liveRoot.dataset.state = "cancelled";
        if (captureBtn) {
          captureBtn.disabled = false;
          captureBtn.textContent = "Capture entire pack";
        }
        cancelBtn.textContent = "Cancelled";
        stopCaptureWatch();
        if (onIdle) onIdle();
      } catch (err) {
        cancelBtn.disabled = false;
        cancelBtn.textContent = "Cancel job";
        phaseEl.textContent = `Cancel failed: ${err.message || err}`;
        console.error(err);
      }
    };
  }

  const tick = async () => {
    try {
      const [job, progress, derived] = await Promise.all([
        fetchJson(`/api/jobs/${encodeURIComponent(watchingJobId)}`),
        fetchJson(`/api/jobs/${encodeURIComponent(watchingJobId)}/progress`),
        fetchJson(
          `/api/lookdev/outputs?asset_id=${encodeURIComponent(assetId)}&limit=48`
        ),
      ]);
      const status = job.status || progress.status || "running";
      const phase = humanPhaseFromProgressLog(progress.log);
      const phases = recentPhasesFromProgressLog(progress.log, 6);
      const outputs = derived.outputs || [];
      const niagara = outputs.filter((o) => o.kind === "niagara-render");

      phaseEl.textContent =
        status === "cancelled"
          ? "Cancelled"
          : status === "failed"
            ? `Failed: ${job.error || phase}`
            : phase;
      metaEl.textContent = `${status} · lookdev ${niagara.length}`;
      clear(feedEl);
      for (const msg of phases.slice().reverse()) {
        const li = document.createElement("li");
        li.textContent = msg;
        feedEl.appendChild(li);
      }

      if (outputs.length !== lastOutputCount) {
        lastOutputCount = outputs.length;
        renderLookdevGrid(lookdevHost, outputs, {
          emptyText: "Waiting for first lookdev frames to land…",
          limit: 24,
        });
      }

      const terminal =
        status === "succeeded" ||
        status === "failed" ||
        status === "cancelled";
      if (terminal) {
        ticksAfterDone += 1;
        liveRoot.dataset.state = status;
        if (cancelBtn) {
          cancelBtn.hidden = status !== "running" && status !== "queued";
          cancelBtn.disabled = true;
          cancelBtn.textContent =
            status === "cancelled" ? "Cancelled" : "Cancel job";
        }
        if (captureBtn) {
          captureBtn.disabled = false;
          captureBtn.textContent =
            status === "succeeded"
              ? "Capture entire pack"
              : status === "cancelled"
                ? "Capture entire pack"
                : "Capture entire pack";
        }
        if (ticksAfterDone >= 2) {
          stopCaptureWatch();
          if (onIdle) onIdle();
        }
      } else if (captureBtn) {
        captureBtn.disabled = true;
        captureBtn.textContent = "Capturing…";
        if (cancelBtn) {
          cancelBtn.hidden = false;
          cancelBtn.disabled = false;
          cancelBtn.textContent = "Cancel job";
        }
      }
    } catch (err) {
      phaseEl.textContent = "Live update interrupted — retrying…";
      console.warn(err);
    }
  };

  tick();
  captureWatchTimer = setInterval(tick, 4000);
}

function formatSilence(sec) {
  if (sec == null || Number.isNaN(sec)) return "";
  const s = Math.max(0, Math.floor(sec));
  if (s < 60) return `${s}s quiet`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem}s quiet`;
}

function renderLiveOps(ops) {
  const host = $("live-ops");
  if (!host) return;
  clear(host);
  const finish = ops.finish || {};
  const counts = ops.counts || {};
  const running = (ops.capture && ops.capture.running) || [];
  const queued = (ops.capture && ops.capture.queued) || [];
  const run = running[0];
  const stalled = !!(run && run.stalled);
  const done = !!finish.done;
  host.dataset.state = done ? "done" : stalled ? "stalled" : "active";

  const top = document.createElement("div");
  top.className = "live-ops-top";
  const title = document.createElement("div");
  title.className = "live-ops-title";
  title.textContent = done
    ? "Live ops · inventory complete"
    : "Live ops · inventory progress";
  const pct = document.createElement("div");
  pct.className = "live-ops-pct";
  pct.textContent = `${finish.percent_complete ?? 0}% Ready`;
  top.append(title, pct);
  host.appendChild(top);

  const h = ops.host || {};
  if (h.gpu_util_pct != null || h.worker_busy != null) {
    const util = document.createElement("div");
    util.className = "live-ops-line";
    const gpu =
      h.gpu_util_pct != null ? `GPU ${h.gpu_util_pct}%` : "GPU —";
    const mem =
      h.gpu_mem_used_mb != null && h.gpu_mem_total_mb != null
        ? ` · VRAM ${h.gpu_mem_used_mb}/${h.gpu_mem_total_mb} MB`
        : "";
    const ed =
      h.editor_rss_mb != null ? ` · Editor ${h.editor_rss_mb} MB` : "";
    const busy =
      h.worker_busy === true
        ? " · worker busy"
        : h.worker_busy === false
          ? " · worker idle"
          : "";
    const tax = h.idle_tax ? " · IDLE TAX (warm editor, GPU ~0%)" : "";
    util.textContent = `Aurora ${h.host_id || ""}: ${gpu}${mem}${ed}${busy}${tax}`;
    host.appendChild(util);
  }

  const bar = document.createElement("div");
  bar.className = "live-ops-bar";
  bar.dataset.stalled = stalled ? "1" : "0";
  const fill = document.createElement("span");
  fill.style.width = `${Math.max(0, Math.min(100, finish.percent_complete ?? 0))}%`;
  bar.appendChild(fill);
  host.appendChild(bar);

  const line = document.createElement("div");
  line.className = "live-ops-line";
  if (done) {
    line.textContent = "All Unreal packs Ready. Nothing for you to babysit.";
  } else if (run) {
    const p =
      run.percent != null ? `${run.percent}%` : "phase-known / % unknown";
    const sys =
      run.systems_total != null && run.systems_done != null
        ? ` · systems ${run.systems_done}/${run.systems_total}`
        : run.systems_total != null
          ? ` · ${run.systems_total} systems`
          : "";
    const stall = stalled
      ? ` · STALLED (${formatSilence(run.silence_sec)})`
      : run.silence_sec != null
        ? ` · ${formatSilence(run.silence_sec)}`
        : "";
    line.textContent = `MRQ ${run.status}: ${run.asset_id} — ${run.phase || "…"} (${p}${sys})${stall}`;
  } else if (queued.length) {
    line.textContent = `MRQ queued: ${queued.map((j) => j.asset_id).join(", ")}`;
  } else if ((counts.on_disk || 0) > 0) {
    line.textContent = `${counts.on_disk} on disk waiting for capture — agent should enqueue.`;
  } else if ((counts.need_download || 0) > 0) {
    line.textContent = `${counts.need_download} still need VaultCache fill (agent-owned; redeem closed).`;
  } else {
    line.textContent = "Idle — checking…";
  }
  host.appendChild(line);

  const sub = document.createElement("div");
  sub.className = "live-ops-sub";
  const op = ops.operator || {};
  sub.textContent = `Your job: ${op.responsibility || "none"} · Redeem: ${
    op.redeem || "closed"
  } · Ready ${finish.ready ?? 0} / ${finish.total ?? "?"} · remaining ${
    finish.remaining ?? "?"
  } · updated ${ops.generated_at || ""}`;
  host.appendChild(sub);
}

let liveOpsTimer = null;
let liveOpsInFlight = false;
async function refreshLiveOps() {
  if (liveOpsInFlight) return;
  liveOpsInFlight = true;
  try {
    const ops = await fetchJson("/api/ops/pulse?engine=unreal");
    renderLiveOps(ops);
    const host = $("stats");
    if (host && ops.counts) {
      const keys = ["ready", "on_disk", "vault", "installable", "need_download"];
      const kids = host.querySelectorAll(".stat");
      keys.forEach((key, i) => {
        if (!kids[i]) return;
        const strong = kids[i].querySelector("strong");
        if (strong) strong.textContent = String(ops.counts[key] ?? 0);
      });
    }
  } catch (err) {
    const host = $("live-ops");
    if (host) {
      clear(host);
      host.dataset.state = "stalled";
      const line = document.createElement("div");
      line.className = "live-ops-line";
      line.textContent = "Live ops unreachable — /api/ops/pulse failed.";
      host.appendChild(line);
    }
    console.warn(err);
  } finally {
    liveOpsInFlight = false;
  }
}

function startLiveOps() {
  // loadStats already painted pulse once; poll without overlaps.
  if (liveOpsTimer != null) clearInterval(liveOpsTimer);
  liveOpsTimer = setInterval(() => {
    refreshLiveOps().catch(console.error);
  }, 5000);
}

async function loadStats() {
  const host = $("stats");
  clear(host);
  // One cheap pulse. Do not stack availability + coverage + queue on first paint.
  let pulse = null;
  try {
    pulse = await fetchJson("/api/ops/pulse?engine=unreal");
  } catch (err) {
    console.warn(err);
  }
  const c = (pulse && pulse.counts) || {};
  for (const [n, label] of [
    [c.ready, "ready"],
    [c.on_disk, "on disk"],
    [c.vault, "vault only"],
    [c.installable, "installable"],
    [c.need_download, "need download"],
  ]) {
    const div = document.createElement("div");
    div.className = "stat";
    const strong = document.createElement("strong");
    strong.textContent = String(n ?? 0);
    div.append(strong, document.createTextNode(` ${label}`));
    host.appendChild(div);
  }
  if (pulse) renderLiveOps(pulse);

  let box = $("import-queue");
  if (!box) {
    box = document.createElement("div");
    box.id = "import-queue";
    box.className = "import-queue";
    host.parentElement.appendChild(box);
  }
  clear(box);
  const items = (pulse && pulse.on_disk_need_lookdev) || [];
  const headRow = document.createElement("div");
  headRow.className = "import-queue-head";
  const h = document.createElement("h2");
  h.textContent =
    items.length > 0
      ? `On disk — still need work (${items.length})`
      : "On disk — lookdev caught up";
  headRow.appendChild(h);
  box.appendChild(headRow);
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "fit";
    const need = c.need_download || 0;
    empty.textContent =
      need > 0
        ? `No on-disk lookdev left. ${need} packs still need VaultCache fill (agent-owned).`
        : "All Unreal packs past import + lookdev (or none pending).";
    box.appendChild(empty);
  } else {
    const ul = document.createElement("ul");
    for (const item of items) {
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = item.display_name || item.asset_id;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "linkish";
      btn.textContent = "open";
      btn.addEventListener("click", () => openDetail(item.asset_id));
      li.append(name, btn);
      ul.appendChild(li);
    }
    box.appendChild(ul);
  }
}

function renderRows(assets) {
  const body = $("rows");
  clear(body);
  $("count").textContent = `${assets.length} shown`;
  if (!assets.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "empty";
    td.textContent = "No assets match.";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }

  for (const a of assets) {
    const tr = document.createElement("tr");
    tr.dataset.id = a.id;

    const tdIdx = document.createElement("td");
    tdIdx.textContent = a.list_index ?? "";

    const tdName = document.createElement("td");
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = a.display_name || a.id;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = a.store_label || a.store_lane || "";
    tdName.append(name, meta);

    const tdEngine = document.createElement("td");
    tdEngine.textContent = a.engine || "";

    const tdType = document.createElement("td");
    tdType.textContent = a.package_type || "";

    const tdAvail = makeAvailabilityCell(a.availability);

    const tdFit = document.createElement("td");
    tdFit.className = "fit";
    tdFit.textContent = a.project_fit || "";

    tr.append(tdIdx, tdName, tdEngine, tdType, tdAvail, tdFit);
    tr.addEventListener("click", () => openDetail(a.id));
    body.appendChild(tr);
  }
}

function addDlRow(dl, term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  if (term === "Id") {
    const code = document.createElement("code");
    code.textContent = value;
    dd.appendChild(code);
  } else {
    dd.textContent = value;
  }
  dl.append(dt, dd);
}

function makeStatusPill(status) {
  const span = document.createElement("span");
  const kind =
    status === "done" || status === "succeeded"
      ? "open"
      : status === "blocked" || status === "failed" || status === "cancelled"
        ? "expired"
        : status === "needs-human" || status === "queued" || status === "running"
          ? "needs"
          : "unknown";
  span.className = `pill ${kind}`;
  span.textContent = status || "unknown";
  return span;
}

async function cancelJob(jobId, reason = "operator_cancelled") {
  const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`cancel ${res.status}: ${detail}`);
  }
  return res.json();
}

function renderIntakeRun(host, run) {
  const wrap = document.createElement("div");
  wrap.className = "intake-run";

  const head = document.createElement("div");
  head.className = "intake-run-head";
  const title = document.createElement("strong");
  title.textContent = run.run_id;
  head.appendChild(title);
  head.appendChild(makeStatusPill(run.status));
  wrap.appendChild(head);

  const meta = document.createElement("p");
  meta.className = "fit";
  meta.textContent = `requested_by=${run.requested_by || "?"} · ${run.steps?.length || 0} steps`;
  wrap.appendChild(meta);

  const enqueueBtn = document.createElement("button");
  enqueueBtn.type = "button";
  enqueueBtn.className = "btn btn-secondary";
  enqueueBtn.textContent = "Enqueue automatable jobs";
  enqueueBtn.addEventListener("click", async () => {
    enqueueBtn.disabled = true;
    enqueueBtn.textContent = "Enqueueing…";
    try {
      const res = await fetch(
        `/api/intake/${encodeURIComponent(run.run_id)}/enqueue-automatable`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(`enqueue ${res.status}`);
      const body = await res.json();
      enqueueBtn.textContent = `Queued ${body.count}`;
      // Give worker a moment, then refresh detail
      setTimeout(() => openDetail(run.asset_id), 1200);
    } catch (err) {
      enqueueBtn.textContent = "Enqueue failed";
      console.error(err);
    }
  });
  wrap.appendChild(enqueueBtn);

  const ol = document.createElement("ol");
  ol.className = "intake-steps";
  for (const step of run.steps || []) {
    const li = document.createElement("li");
    const row = document.createElement("div");
    row.className = "intake-step-row";
    const label = document.createElement("span");
    label.textContent = step.title;
    row.appendChild(label);
    row.appendChild(makeStatusPill(step.status));
    li.appendChild(row);
    if (step.detail) {
      const d = document.createElement("p");
      d.className = "fit";
      d.textContent = step.detail;
      li.appendChild(d);
    }
    if (step.notes) {
      const n = document.createElement("p");
      n.className = "fit";
      n.textContent = `notes: ${step.notes}`;
      li.appendChild(n);
    }
    ol.appendChild(li);
  }
  wrap.appendChild(ol);
  host.appendChild(wrap);
}

async function proposeIntake(assetId) {
  const res = await fetch("/api/intake/propose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ asset_id: assetId, requested_by: "operator-ui" }),
  });
  if (!res.ok) throw new Error(`propose failed ${res.status}`);
  return res.json();
}

async function openDetail(id) {
  stopCaptureWatch();
  const a = await fetchJson(`/api/assets/${encodeURIComponent(id)}`);
  const host = $("detail-body");
  clear(host);

  const titleRow = document.createElement("div");
  titleRow.className = "detail-title-row";
  const h2 = document.createElement("h2");
  h2.textContent = a.display_name || a.id;
  titleRow.appendChild(h2);
  titleRow.appendChild(makePill(a.redeem_window));
  host.appendChild(titleRow);

  const summary = document.createElement("p");
  summary.className = "detail-summary";
  summary.textContent = `${a.engine || "?"} · ${a.package_type || "pack"} · ${a.store_label || a.store_lane || "store?"}`;
  host.appendChild(summary);

  let activeHost = null;
  try {
    const hostsPayload = await fetchJson("/api/ue/hosts");
    activeHost = hostsPayload.active_host || null;
  } catch (err) {
    console.warn(err);
  }

  // ---- Import pack (operator checklist) ----
  let importStatus = null;
  try {
    importStatus = await fetchJson(
      `/api/assets/${encodeURIComponent(a.id)}/import`
    );
  } catch (err) {
    console.warn(err);
  }

  const importSec = document.createElement("section");
  importSec.className = "detail-section import-section";
  const importHead = document.createElement("h3");
  importHead.textContent = "Import pack";
  importSec.appendChild(importHead);
  const fabBanner = document.createElement("p");
  fabBanner.className = "fit fab-target-banner";
  const fabLabel =
    (activeHost &&
      (activeHost.fab_target_label ||
        (activeHost.host_specs && activeHost.host_specs.fab_target_label))) ||
    "AuroraVellum (F:\\Games\\AuroraVellum)";
  const fabProject =
    (activeHost &&
      (activeHost.fab_target_project ||
        (activeHost.host_specs && activeHost.host_specs.fab_target_project) ||
        activeHost.project)) ||
    "F:\\Games\\AuroraVellum\\AuroraVellum.uproject";
  fabBanner.textContent =
    "STOP using Epic Launcher Fab Add-to-Project (project picker is broken). Open AuroraVellum in Unreal 5.8, then use the Fab plugin INSIDE the editor to Add to this project. Packs already on F: — pick below and Stage.";
  importSec.appendChild(fabBanner);
  const fabPathLine = document.createElement("p");
  fabPathLine.className = "fit mono-path";
  fabPathLine.textContent = fabProject;
  importSec.appendChild(fabPathLine);

  const openEditorBtn = document.createElement("button");
  openEditorBtn.type = "button";
  openEditorBtn.className = "btn";
  openEditorBtn.textContent = "Open AuroraVellum in UE";
  openEditorBtn.addEventListener("click", async () => {
    openEditorBtn.disabled = true;
    openEditorBtn.textContent = "Launching…";
    try {
      const hostId = (activeHost && activeHost.id) || "aurora";
      const res = await fetch(
        `/api/ue/hosts/open-editor?host_id=${encodeURIComponent(hostId)}`,
        { method: "POST" }
      );
      if (!res.ok) throw new Error(`open-editor ${res.status}`);
      openEditorBtn.textContent = "UE launch queued";
    } catch (err) {
      console.error(err);
      openEditorBtn.textContent = "Launch failed";
      openEditorBtn.disabled = false;
    }
  });
  importSec.appendChild(openEditorBtn);

  const checklist = document.createElement("ol");
  checklist.className = "import-checklist";
  const pathRow = document.createElement("div");
  pathRow.className = "import-path-row";
  const pickLabel = document.createElement("label");
  pickLabel.textContent = "Content folder (from Aurora scan)";
  const folderSelect = document.createElement("select");
  folderSelect.className = "import-path import-folder-select";
  const emptyOpt = document.createElement("option");
  emptyOpt.value = "";
  emptyOpt.textContent = "— pick Content/* —";
  folderSelect.appendChild(emptyOpt);
  pickLabel.appendChild(folderSelect);
  pathRow.appendChild(pickLabel);

  const refreshFoldersBtn = document.createElement("button");
  refreshFoldersBtn.type = "button";
  refreshFoldersBtn.className = "btn btn-secondary";
  refreshFoldersBtn.textContent = "Refresh folders";
  pathRow.appendChild(refreshFoldersBtn);

  const pathLabel = document.createElement("label");
  pathLabel.textContent = "Selected host path (from scan only)";
  const pathInputImport = document.createElement("input");
  pathInputImport.type = "text";
  pathInputImport.className = "import-path";
  pathInputImport.readOnly = true;
  pathInputImport.placeholder = "Pick a scanned folder above";
  pathInputImport.value =
    (importStatus && importStatus.host_content_path) ||
    (a.host_content_path || "");
  pathLabel.appendChild(pathInputImport);
  pathRow.appendChild(pathLabel);
  importSec.appendChild(pathRow);

  const scanWarn = document.createElement("p");
  scanWarn.className = "fit scan-warn";
  scanWarn.hidden = true;
  importSec.appendChild(scanWarn);

  const postStageHint = document.createElement("p");
  postStageHint.className = "fit post-stage-hint";
  postStageHint.hidden = true;
  importSec.appendChild(postStageHint);

  const importActions = document.createElement("div");
  importActions.className = "capture-actions";
  importSec.appendChild(importActions);

  let deriveOfferBtn = null;

  const fillFolderSelect = async () => {
    try {
      const hostId = (activeHost && activeHost.id) || "aurora";
      const data = await fetchJson(
        `/api/ue/hosts/content-folders?host_id=${encodeURIComponent(hostId)}`
      );
      const previous = folderSelect.value;
      clear(folderSelect);
      const opt0 = document.createElement("option");
      opt0.value = "";
      opt0.textContent =
        data.count > 0
          ? `— ${data.count} folders (updated ${data.updated_at || "?"}) —`
          : "— no folders yet — Fab Add to Project, then Refresh —";
      folderSelect.appendChild(opt0);
      for (const f of data.folders || []) {
        const opt = document.createElement("option");
        opt.value = f.path || "";
        opt.dataset.name = f.name || "";
        opt.dataset.engine = f.engine || "unreal";
        const eng = f.engine && f.engine !== "unreal" ? ` [${f.engine}]` : "";
        opt.textContent = f.project_root
          ? `${f.name}${eng}  ·  ${f.project_root}`
          : `${f.name}${eng}`;
        folderSelect.appendChild(opt);
      }
      if (data.fab_target_project) {
        fabPathLine.textContent = data.fab_target_project;
      }
      const cur =
        previous ||
        (importStatus && importStatus.host_content_path) ||
        pathInputImport.value;
      if (cur) {
        for (const opt of folderSelect.options) {
          if (opt.value.toLowerCase() === String(cur).toLowerCase()) {
            folderSelect.value = opt.value;
            pathInputImport.value = opt.value;
            break;
          }
        }
      }
      scanWarn.hidden = (data.folders || []).length > 0;
      scanWarn.textContent = (data.folders || []).length
        ? ""
        : "No Content folders scanned yet. After Fab finishes, click Refresh folders.";
    } catch (err) {
      console.warn(err);
    }
  };

  folderSelect.addEventListener("change", () => {
    const opt = folderSelect.selectedOptions[0];
    pathInputImport.value = opt && opt.value ? opt.value : "";
  });

  refreshFoldersBtn.addEventListener("click", async () => {
    refreshFoldersBtn.disabled = true;
    refreshFoldersBtn.textContent = "Scanning…";
    try {
      const hostId = (activeHost && activeHost.id) || "aurora";
      await fetch(
        `/api/ue/hosts/content-folders/refresh?host_id=${encodeURIComponent(hostId)}`,
        { method: "POST" }
      );
      for (let i = 0; i < 20; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        await fillFolderSelect();
        if (folderSelect.options.length > 1) break;
      }
    } catch (err) {
      console.error(err);
    } finally {
      refreshFoldersBtn.disabled = false;
      refreshFoldersBtn.textContent = "Refresh folders";
    }
  });

  const ensureDeriveOffer = (st) => {
    const show = st && st.offer_derive;
    postStageHint.hidden = !show;
    postStageHint.textContent = show
      ? st.post_stage_hint || "Pack staged — Derive texture stills, or Capture for Niagara."
      : "";
    if (!show) {
      if (deriveOfferBtn) {
        deriveOfferBtn.remove();
        deriveOfferBtn = null;
      }
      return;
    }
    if (deriveOfferBtn) return;
    deriveOfferBtn = document.createElement("button");
    deriveOfferBtn.type = "button";
    deriveOfferBtn.className = "btn";
    deriveOfferBtn.textContent = "Derive texture stills";
    deriveOfferBtn.addEventListener("click", async () => {
      deriveOfferBtn.disabled = true;
      try {
        const res = await fetch("/api/lookdev/derive", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ asset_id: a.id }),
        });
        if (!res.ok) throw new Error(`derive ${res.status}`);
        deriveOfferBtn.textContent = "Derive queued";
      } catch (err) {
        console.error(err);
        deriveOfferBtn.textContent = "Derive failed";
        deriveOfferBtn.disabled = false;
      }
    });
    importActions.appendChild(deriveOfferBtn);
  };

  const refreshImportUi = (st) => {
    importStatus = st;
    clear(checklist);
    for (const step of (st && st.steps) || []) {
      const li = document.createElement("li");
      li.className = step.done ? "done" : "todo";
      li.textContent = `${step.done ? "✓" : "○"} ${step.label}`;
      checklist.appendChild(li);
    }
    if (st && st.content_root) {
      const cr = document.createElement("p");
      cr.className = "fit";
      cr.textContent = `content_root ${st.content_root}`;
      checklist.appendChild(cr);
    }
    if (st && st.host_content_path && st.path_verified === false) {
      const warn = document.createElement("p");
      warn.className = "fit scan-warn";
      warn.textContent =
        "Saved path not in latest scan — Refresh folders, then pick again.";
      checklist.appendChild(warn);
    }
    ensureDeriveOffer(st);
  };
  importSec.insertBefore(checklist, pathRow);
  if (importStatus) refreshImportUi(importStatus);
  fillFolderSelect();

  const markRedeemed = document.createElement("button");
  markRedeemed.type = "button";
  markRedeemed.className = "btn";
  markRedeemed.textContent = "Mark redeemed";
  markRedeemed.addEventListener("click", async () => {
    markRedeemed.disabled = true;
    try {
      const res = await fetch(
        `/api/assets/${encodeURIComponent(a.id)}/import/mark`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ step: "redeemed" }),
        }
      );
      if (!res.ok) throw new Error(`mark ${res.status}`);
      const body = await res.json();
      refreshImportUi(body.import);
    } catch (err) {
      console.error(err);
      markRedeemed.textContent = "Mark failed";
    } finally {
      markRedeemed.disabled = false;
      markRedeemed.textContent = "Mark redeemed";
    }
  });
  importActions.appendChild(markRedeemed);

  const fabInstallBtn = document.createElement("button");
  fabInstallBtn.type = "button";
  fabInstallBtn.className = "btn";
  fabInstallBtn.textContent = "Install from VaultCache";
  fabInstallBtn.title =
    "Copy Epic VaultCache pack into F:\\Games\\AuroraVellum\\Content (no Fab UI)";
  fabInstallBtn.addEventListener("click", async () => {
    fabInstallBtn.disabled = true;
    fabInstallBtn.textContent = "Queuing install…";
    try {
      const res = await fetch(
        `/api/assets/${encodeURIComponent(a.id)}/import/fab-install`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ue_host: (activeHost && activeHost.id) || "aurora",
            auto_stage: true,
          }),
        }
      );
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `fab-install ${res.status}`);
      }
      const body = await res.json();
      const jobId = body.job && body.job.job_id;
      if (jobId) {
        fabInstallBtn.textContent = "Installing…";
        const poll = setInterval(async () => {
          try {
            const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
            const st = await fetchJson(
              `/api/assets/${encodeURIComponent(a.id)}/import`
            );
            refreshImportUi(st);
            await fillFolderSelect();
            if (
              job.status === "succeeded" ||
              job.status === "failed" ||
              job.status === "cancelled"
            ) {
              clearInterval(poll);
              fabInstallBtn.disabled = false;
              fabInstallBtn.textContent =
                job.status === "succeeded"
                  ? "Installed"
                  : job.error || "Install failed";
              setTimeout(() => {
                fabInstallBtn.textContent = "Install from VaultCache";
              }, 4000);
            }
          } catch (err) {
            console.warn(err);
          }
        }, 2500);
      } else {
        fabInstallBtn.disabled = false;
        fabInstallBtn.textContent = "Install from VaultCache";
      }
    } catch (err) {
      console.error(err);
      fabInstallBtn.disabled = false;
      fabInstallBtn.textContent =
        String(err.message || "").includes("no_fab_install_map")
          ? "No VaultCache map"
          : "Install failed";
      setTimeout(() => {
        fabInstallBtn.textContent = "Install from VaultCache";
      }, 3000);
    }
  });
  importActions.appendChild(fabInstallBtn);

  const markInProject = document.createElement("button");
  markInProject.type = "button";
  markInProject.className = "btn";
  markInProject.textContent = "Mark in project";
  markInProject.addEventListener("click", async () => {
    const path = folderSelect.value.trim() || pathInputImport.value.trim();
    if (!path) {
      folderSelect.focus();
      markInProject.textContent = "Pick scanned folder";
      setTimeout(() => {
        markInProject.textContent = "Mark in project";
      }, 2000);
      return;
    }
    markInProject.disabled = true;
    try {
      const res = await fetch(
        `/api/assets/${encodeURIComponent(a.id)}/import/mark`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            step: "in_project",
            host_content_path: path,
          }),
        }
      );
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `mark ${res.status}`);
      }
      const body = await res.json();
      refreshImportUi(body.import);
    } catch (err) {
      console.error(err);
      markInProject.textContent =
        String(err.message || "").includes("host_path_not_in_scan")
          ? "Not in scan — Refresh"
          : "Mark failed";
    } finally {
      markInProject.disabled = false;
      setTimeout(() => {
        markInProject.textContent = "Mark in project";
      }, 2500);
    }
  });
  importActions.appendChild(markInProject);

  const stageBtn = document.createElement("button");
  stageBtn.type = "button";
  stageBtn.className = "btn";
  stageBtn.textContent = "Stage to vault";
  stageBtn.addEventListener("click", async () => {
    const path = folderSelect.value.trim() || pathInputImport.value.trim();
    if (!path) {
      folderSelect.focus();
      stageBtn.textContent = "Pick scanned folder";
      setTimeout(() => {
        stageBtn.textContent = "Stage to vault";
      }, 2000);
      return;
    }
    stageBtn.disabled = true;
    stageBtn.textContent = "Queuing stage…";
    try {
      const opt = folderSelect.selectedOptions[0];
      const folder =
        (opt && opt.dataset.name) ||
        path.replace(/[\\/]+$/, "").split(/[\\/]/).pop();
      const res = await fetch(
        `/api/assets/${encodeURIComponent(a.id)}/import/stage`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            host_content_path: path,
            content_folder_name: folder,
            ue_host: (activeHost && activeHost.id) || "aurora",
          }),
        }
      );
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `stage ${res.status}`);
      }
      const body = await res.json();
      const jobId = body.job && body.job.job_id;
      if (jobId) {
        stageBtn.textContent = "Staging…";
        const poll = setInterval(async () => {
          try {
            const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
            const st = await fetchJson(
              `/api/assets/${encodeURIComponent(a.id)}/import`
            );
            refreshImportUi(st);
            if (
              job.status === "succeeded" ||
              job.status === "failed" ||
              job.status === "cancelled" ||
              (st.steps && st.steps.find((s) => s.id === "staged" && s.done))
            ) {
              clearInterval(poll);
              stageBtn.disabled = false;
              stageBtn.textContent =
                job.status === "succeeded" ||
                (st.steps && st.steps.find((s) => s.id === "staged" && s.done))
                  ? "Staged — derive or capture"
                  : "Stage failed";
              refreshImportUi(st);
            }
          } catch {
            /* ignore */
          }
        }, 3000);
      }
    } catch (err) {
      console.error(err);
      stageBtn.textContent = "Stage failed";
      stageBtn.disabled = false;
    }
  });
  importActions.appendChild(stageBtn);
  host.appendChild(importSec);

  // ---- Capture (primary) ----
  const captureSec = document.createElement("section");
  captureSec.className = "detail-section";
  const captureHead = document.createElement("h3");
  captureHead.textContent = "Capture";
  captureSec.appendChild(captureHead);

  const hostLine = document.createElement("p");
  hostLine.className = "fit";
  if (activeHost) {
    const s = activeHost.host_specs || {};
    const cpu = (s.cpu && s.cpu[0] && s.cpu[0].name) || "";
    const gpu =
      (s.nvidia_gpus && s.nvidia_gpus[0] && s.nvidia_gpus[0].name) ||
      (Array.isArray(s.gpus) &&
        (s.gpus.find((g) => g && g.name && !/remote display/i.test(g.name)) ||
          {}).name) ||
      "";
    const bits = [activeHost.label || activeHost.id];
    if (s.ram_gb) bits.push(`${s.ram_gb} GB RAM`);
    if (gpu) bits.push(gpu);
    else if (cpu) bits.push(cpu.split("@")[0].trim());
    hostLine.textContent = bits.join(" · ");
  } else {
    hostLine.textContent = "UE host unknown — start vellum_ue_agent on Aurora";
  }
  captureSec.appendChild(hostLine);

  const pathInput = document.createElement("input");
  pathInput.type = "hidden";
  pathInput.value =
    (activeHost && (activeHost.project_dir || activeHost.project)) ||
    a.scratch_project_path ||
    "F:\\Games\\AuroraVellum";
  const engInput = document.createElement("input");
  engInput.type = "hidden";
  engInput.value =
    (activeHost && activeHost.engine_version) ||
    a.scratch_engine_version ||
    "5.8";

  const actions = document.createElement("div");
  actions.className = "capture-actions";

  const captureBtn = document.createElement("button");
  captureBtn.type = "button";
  captureBtn.className = "btn";
  captureBtn.textContent = "Capture entire pack";
  actions.appendChild(captureBtn);

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "btn btn-danger";
  cancelBtn.textContent = "Cancel job";
  cancelBtn.hidden = true;
  actions.appendChild(cancelBtn);

  const forceLabel = document.createElement("label");
  forceLabel.className = "force-check";
  const forceInput = document.createElement("input");
  forceInput.type = "checkbox";
  forceLabel.append(forceInput, document.createTextNode(" Force re-render (wipes + re-renders all systems)"));
  actions.appendChild(forceLabel);
  captureSec.appendChild(actions);

  const liveRoot = document.createElement("section");
  liveRoot.className = "capture-live";
  liveRoot.hidden = true;
  liveRoot.setAttribute("aria-live", "polite");
  const liveHead = document.createElement("div");
  liveHead.className = "capture-live-head";
  const liveTitle = document.createElement("strong");
  liveTitle.textContent = "Live import";
  liveHead.appendChild(liveTitle);
  const liveMeta = document.createElement("span");
  liveMeta.className = "capture-live-meta";
  liveMeta.textContent = "—";
  liveHead.appendChild(liveMeta);
  liveRoot.appendChild(liveHead);
  const livePhase = document.createElement("p");
  livePhase.className = "capture-live-phase";
  livePhase.textContent = "Waiting for agent…";
  liveRoot.appendChild(livePhase);
  const liveFeed = document.createElement("ul");
  liveFeed.className = "capture-live-feed";
  liveRoot.appendChild(liveFeed);
  captureSec.appendChild(liveRoot);
  host.appendChild(captureSec);

  // ---- Game-ready (product catalog) ----
  const grSec = document.createElement("section");
  grSec.className = "detail-section";
  const grHead = document.createElement("h3");
  grHead.textContent = "Game-ready";
  grSec.appendChild(grHead);
  const grNote = document.createElement("p");
  grNote.className = "muted";
  grNote.textContent =
    "Portable Conversion Factory outputs (models / VFX clips / textures / audio). Not lookdev photos.";
  grSec.appendChild(grNote);
  const grHost = document.createElement("div");
  grHost.className = "game-ready-list";
  grSec.appendChild(grHost);
  host.appendChild(grSec);

  // ---- Lookdev ----
  const lookdevSec = document.createElement("section");
  lookdevSec.className = "detail-section";
  const lookdevHead = document.createElement("h3");
  lookdevHead.textContent = "Lookdev (legacy stills)";
  lookdevSec.appendChild(lookdevHead);
  const lookdevHost = document.createElement("div");
  lookdevHost.className = "lookdev-grid";
  lookdevSec.appendChild(lookdevHost);
  host.appendChild(lookdevSec);

  const startWatchForJob = (jobId) => {
    startCaptureWatch({
      assetId: a.id,
      jobId,
      liveRoot,
      phaseEl: livePhase,
      metaEl: liveMeta,
      feedEl: liveFeed,
      lookdevHost,
      captureBtn,
      cancelBtn,
    });
  };

  captureBtn.addEventListener("click", async () => {
    captureBtn.disabled = true;
    captureBtn.textContent = "Queuing…";
    try {
      let intakeRunId = null;
      try {
        const listed = await fetchJson(
          `/api/intake?asset_id=${encodeURIComponent(a.id)}&limit=1`
        );
        intakeRunId =
          (listed.runs && listed.runs[0] && listed.runs[0].run_id) || null;
      } catch {
        /* ignore */
      }
      const res = await fetch("/api/ue/capture", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          asset_id: a.id,
          lane: "slots",
          project_path: pathInput.value.trim(),
          engine_version: engInput.value.trim(),
          intake_run_id: intakeRunId,
          content_root:
            (importStatus && importStatus.content_root) ||
            (a.content_root && String(a.content_root)) ||
            "/Game/FireworksV1",
          force: !!forceInput.checked,
        }),
      });
      if (!res.ok) throw new Error(`ue capture ${res.status}`);
      const body = await res.json();
      const jobId = body.job && body.job.job_id;
      if (!jobId) throw new Error("missing job_id");
      startWatchForJob(jobId);
    } catch (err) {
      captureBtn.disabled = false;
      captureBtn.textContent = "Queue failed";
      console.error(err);
    }
  });

  try {
    const gr = await fetchJson(
      `/api/game-ready/elements?asset_id=${encodeURIComponent(a.id)}&limit=48`
    );
    clear(grHost);
    const elements = gr.elements || [];
    if (!elements.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent =
        "No game-ready elements yet. Run Conversion Factory jobs (tools/pipeline/).";
      grHost.appendChild(empty);
    } else {
      elements.forEach((el) => {
        const row = document.createElement("div");
        row.className = "game-ready-row";
        const title = document.createElement("strong");
        title.textContent = `${el.kind} · ${el.pack || el.asset_id}`;
        row.appendChild(title);
        const meta = document.createElement("span");
        meta.className = "muted";
        const lanes = (el.lanes || []).join(", ") || "unpublished";
        meta.textContent = ` lanes: ${lanes}`;
        row.appendChild(meta);
        const pub = document.createElement("button");
        pub.type = "button";
        pub.className = "btn tiny";
        pub.textContent = "Publish → slots";
        pub.addEventListener("click", async () => {
          pub.disabled = true;
          try {
            await fetch(
              `/api/game-ready/elements/${encodeURIComponent(el.id)}/publish`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ lane: "slots" }),
              }
            );
            pub.textContent = "Published";
          } catch (e) {
            pub.textContent = "Failed";
            pub.disabled = false;
          }
        });
        row.appendChild(pub);
        grHost.appendChild(row);
      });
    }
  } catch (err) {
    console.error(err);
  }

  try {
    const derived = await fetchJson(
      `/api/lookdev/outputs?asset_id=${encodeURIComponent(a.id)}&limit=48`
    );
    renderLookdevGrid(lookdevHost, derived.outputs || []);
  } catch (err) {
    console.error(err);
  }

  // Active / orphaned capture job
  let activeCapture = null;
  let jobs = [];
  try {
    const jobsListed = await fetchJson(
      `/api/jobs?asset_id=${encodeURIComponent(a.id)}`
    );
    jobs = jobsListed.jobs || [];
    activeCapture = jobs.find(
      (j) =>
        j.kind === "ue_capture" &&
        (j.status === "running" || j.status === "queued")
    );
    if (activeCapture) startWatchForJob(activeCapture.job_id);
  } catch (err) {
    console.warn(err);
  }

  // ---- More (collapsed) ----
  const more = document.createElement("details");
  more.className = "detail-more";
  const moreSum = document.createElement("summary");
  moreSum.textContent = "More details";
  more.appendChild(moreSum);

  const dl = document.createElement("dl");
  dl.className = "detail-meta";
  addDlRow(dl, "Id", a.id);
  addDlRow(dl, "Redeem by", formatDeadline(a.redemption_deadline));
  addDlRow(dl, "Fit", a.project_fit || "—");
  if (a.scratch_project_path) {
    addDlRow(dl, "Scratch", a.scratch_project_path);
  }
  more.appendChild(dl);

  if (activeHost && activeHost.host_specs) {
    const s = activeHost.host_specs;
    const specsP = document.createElement("p");
    specsP.className = "fit";
    const nvidia = s.nvidia_gpus && s.nvidia_gpus[0];
    specsP.textContent = [
      s.os_caption,
      s.cpu && s.cpu[0] && s.cpu[0].name,
      nvidia
        ? `${nvidia.name} ${nvidia.vram_gb} GB`
        : null,
      (s.volumes || [])
        .map((v) => `${v.device_id}${v.free_gb}G free`)
        .join(" "),
    ]
      .filter(Boolean)
      .join(" · ");
    more.appendChild(specsP);
  }

  const jobsHead = document.createElement("h4");
  jobsHead.textContent = "Recent jobs";
  more.appendChild(jobsHead);
  const jobsHost = document.createElement("div");
  jobsHost.className = "jobs-list";
  more.appendChild(jobsHost);
  if (!jobs.length) {
    const empty = document.createElement("p");
    empty.className = "fit";
    empty.textContent = "No jobs yet.";
    jobsHost.appendChild(empty);
  } else {
    for (const job of jobs.slice(0, 6)) {
      const row = document.createElement("div");
      row.className = "job-row";
      const label = document.createElement("span");
      const shortId = String(job.job_id || "").replace(/^job-\d{8}-/, "");
      label.textContent = `${job.kind} · ${shortId}`;
      row.appendChild(label);
      row.appendChild(makeStatusPill(job.status));
      if (
        job.kind === "ue_capture" &&
        (job.status === "running" || job.status === "queued")
      ) {
        const miniCancel = document.createElement("button");
        miniCancel.type = "button";
        miniCancel.className = "btn btn-danger btn-tiny";
        miniCancel.textContent = "Cancel";
        miniCancel.addEventListener("click", async () => {
          miniCancel.disabled = true;
          try {
            await cancelJob(job.job_id);
            await openDetail(a.id);
          } catch (err) {
            miniCancel.disabled = false;
            console.error(err);
          }
        });
        row.appendChild(miniCancel);
      }
      jobsHost.appendChild(row);
    }
  }

  const intakeWrap = document.createElement("div");
  intakeWrap.className = "intake-compact";
  const intakeHead = document.createElement("h4");
  intakeHead.textContent = "Intake";
  more.appendChild(intakeHead);
  more.appendChild(intakeWrap);
  try {
    const listed = await fetchJson(
      `/api/intake?asset_id=${encodeURIComponent(a.id)}&limit=1`
    );
    const runs = listed.runs || [];
    if (!runs.length) {
      const empty = document.createElement("p");
      empty.className = "fit";
      empty.textContent = "No intake run yet.";
      intakeWrap.appendChild(empty);
      const proposeBtn = document.createElement("button");
      proposeBtn.type = "button";
      proposeBtn.className = "btn btn-secondary";
      proposeBtn.textContent = "Propose intake";
      proposeBtn.addEventListener("click", async () => {
        proposeBtn.disabled = true;
        try {
          await proposeIntake(a.id);
          await openDetail(a.id);
        } catch (err) {
          proposeBtn.textContent = "Propose failed";
          console.error(err);
        }
      });
      intakeWrap.appendChild(proposeBtn);
    } else {
      const run = runs[0];
      const line = document.createElement("p");
      line.className = "fit";
      line.textContent = `${run.run_id} · ${run.status}`;
      intakeWrap.appendChild(line);
    }
  } catch (err) {
    console.error(err);
  }

  const lookdevTools = document.createElement("div");
  lookdevTools.className = "detail-actions";
  const deriveBtn = document.createElement("button");
  deriveBtn.type = "button";
  deriveBtn.className = "btn btn-secondary";
  deriveBtn.textContent = "Derive texture stills";
  deriveBtn.addEventListener("click", async () => {
    deriveBtn.disabled = true;
    try {
      const res = await fetch("/api/lookdev/derive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset_id: a.id }),
      });
      if (!res.ok) throw new Error(`derive ${res.status}`);
      deriveBtn.textContent = "Queued";
    } catch (err) {
      deriveBtn.textContent = "Derive failed";
      console.error(err);
    }
  });
  lookdevTools.appendChild(deriveBtn);
  more.appendChild(lookdevTools);

  host.appendChild(more);
  $("detail").hidden = false;
}

async function refresh() {
  const params = new URLSearchParams();
  const q = $("q").value.trim();
  const engine = $("engine").value;
  const available = $("available").value;
  if (q) params.set("q", q);
  if (engine) params.set("engine", engine);
  if (available) params.set("available", available);
  params.set("lite", "1");
  const qs = params.toString();
  try {
    const data = await fetchJson(`/api/assets${qs ? `?${qs}` : ""}`);
    renderRows(data.assets || []);
  } catch (err) {
    console.error(err);
    const body = $("rows");
    clear(body);
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "empty";
    td.textContent = "Failed to load assets — check /api/assets (timeout or server error).";
    tr.appendChild(td);
    body.appendChild(tr);
    $("count").textContent = "load error";
  }
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

$("detail-close").addEventListener("click", () => {
  stopCaptureWatch();
  $("detail").hidden = true;
});

(function applyEmbedMode() {
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get("embed") === "axiom") {
      document.body.setAttribute("data-embed", "axiom");
    }
  } catch {
    /* ignore */
  }
})();

$("q").addEventListener("input", debounce(refresh, 180));
$("engine").addEventListener("change", refresh);
$("available").addEventListener("change", refresh);

/* —— Visual Research view —— */
const RESEARCH_TOKEN_KEY = "vellum.researchWriteToken";

function loadResearchToken() {
  try {
    return localStorage.getItem(RESEARCH_TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function saveResearchToken(token) {
  try {
    if (token) localStorage.setItem(RESEARCH_TOKEN_KEY, token);
    else localStorage.removeItem(RESEARCH_TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode) — token stays page-local */
  }
}

let researchWriteToken = loadResearchToken();

function setView(view) {
  const register = $("view-register");
  const research = $("view-research");
  const tabReg = $("tab-register");
  const tabRes = $("tab-research");
  if (!register || !research) return;
  const isResearch = view === "research";
  register.hidden = isResearch;
  research.hidden = !isResearch;
  if (tabReg) tabReg.classList.toggle("active", !isResearch);
  if (tabRes) tabRes.classList.toggle("active", isResearch);
  if (isResearch) {
    $("detail").hidden = true;
    stopCaptureWatch();
    refreshResearch().catch(console.error);
  }
}

function formatCaptureDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return String(iso);
  }
}

function openResearchLightbox(item) {
  const dlg = $("research-lightbox");
  const img = $("research-lightbox-img");
  const title = $("research-lightbox-title");
  const meta = $("research-lightbox-meta");
  if (!dlg || !img) return;
  title.textContent = item.title || item.id;
  img.src = item.file_url || `/api/visual-research/${encodeURIComponent(item.id)}/file`;
  img.alt = item.title || "Visual research";
  const bits = [
    `Type: Visual Research`,
    item.project_id ? `Project: ${item.project_id}` : null,
    `Format: ${(item.format || "").toUpperCase()}`,
    item.source_url ? `Source: ${item.source_url}` : null,
    `Captured: ${formatCaptureDate(item.captured_at)}`,
    item.caption ? `Caption: ${item.caption}` : null,
    item.tags && item.tags.length ? `Tags: ${item.tags.join(", ")}` : null,
    item.attribution ? `Attribution: ${item.attribution}` : null,
    item.rights ? `Rights: ${item.rights}` : null,
    item.width && item.height ? `${item.width}×${item.height}` : null,
  ].filter(Boolean);
  meta.textContent = bits.join(" · ");
  if (item.mneme_document_url) {
    meta.appendChild(document.createTextNode(" · "));
    const mnemeLink = document.createElement("a");
    mnemeLink.href = item.mneme_document_url;
    mnemeLink.target = "_blank";
    mnemeLink.rel = "noopener";
    mnemeLink.textContent = "Read source text in Mneme";
    meta.appendChild(mnemeLink);
  }
  if (typeof dlg.showModal === "function") dlg.showModal();
}

function renderResearchGrid(items) {
  const host = $("research-grid");
  if (!host) return;
  clear(host);
  const list = Array.isArray(items) ? items : [];
  if (!list.length) {
    const empty = document.createElement("p");
    empty.className = "fit";
    empty.textContent =
      "No visual research yet. Upload a source bundle above, or POST /api/visual-research/bundles.";
    host.appendChild(empty);
    return;
  }
  for (const item of list) {
    const card = document.createElement("figure");
    card.className = "research-card";
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", `Open ${item.title || item.id}`);

    const img = document.createElement("img");
    img.src = item.file_url || `/api/visual-research/${encodeURIComponent(item.id)}/file`;
    img.alt = item.title || "Visual research";
    img.loading = "lazy";
    if (item.format === "svg") img.className = "research-svg-thumb";
    card.appendChild(img);

    const cap = document.createElement("figcaption");
    const typePill = document.createElement("span");
    typePill.className = "pill-research";
    typePill.textContent = "Visual Research";
    cap.appendChild(typePill);
    const titleEl = document.createElement("span");
    titleEl.className = "research-title";
    titleEl.textContent = item.title || item.id;
    cap.appendChild(titleEl);
    const meta = document.createElement("span");
    meta.className = "research-meta";
    meta.textContent = [
      item.project_id || null,
      (item.format || "?").toUpperCase(),
      item.tags && item.tags.length ? item.tags.slice(0, 3).join(", ") : null,
    ]
      .filter(Boolean)
      .join(" · ");
    cap.appendChild(meta);
    card.appendChild(cap);

    const open = () => openResearchLightbox(item);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        open();
      }
    });
    host.appendChild(card);
  }
}

async function refreshResearch() {
  const params = new URLSearchParams();
  const q = ($("rq") && $("rq").value.trim()) || "";
  const format = ($("rformat") && $("rformat").value) || "";
  const tag = ($("rtag") && $("rtag").value.trim()) || "";
  const project = ($("rproject-filter") && $("rproject-filter").value.trim()) || "";
  if (q) params.set("q", q);
  if (format) params.set("format", format);
  if (tag) params.set("tag", tag);
  if (project) params.set("project_id", project);
  params.set("limit", "200");
  const qs = params.toString();
  try {
    const data = await fetchJson(`/api/visual-research${qs ? `?${qs}` : ""}`);
    renderResearchGrid(data.items || []);
    const total = data.total != null ? data.total : (data.items || []).length;
    $("rcount").textContent = `${total} visual research image${total === 1 ? "" : "s"}`;
  } catch (err) {
    console.error(err);
    const host = $("research-grid");
    clear(host);
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Failed to load visual research — check /api/visual-research.";
    host.appendChild(empty);
    $("rcount").textContent = "load error";
  }
}

if ($("tab-register")) {
  $("tab-register").addEventListener("click", () => setView("register"));
}
if ($("tab-research")) {
  $("tab-research").addEventListener("click", () => setView("research"));
}
if ($("rq")) $("rq").addEventListener("input", debounce(refreshResearch, 180));
if ($("rformat")) $("rformat").addEventListener("change", refreshResearch);
if ($("rtag")) $("rtag").addEventListener("input", debounce(refreshResearch, 180));
if ($("rproject-filter")) {
  $("rproject-filter").addEventListener("input", debounce(refreshResearch, 180));
}

if ($("rtoken") && researchWriteToken) {
  $("rtoken").value = researchWriteToken;
}

if ($("research-upload-form")) {
  $("research-upload-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const status = $("rupload-status");
    const btn = $("rupload-btn");
    const fileInput = $("rfile");
    const tokenInput = $("rtoken");
    if (!fileInput.files || !fileInput.files[0]) {
      status.textContent = "Choose a file.";
      return;
    }
    const token = (tokenInput.value || researchWriteToken || "").trim();
    if (!token) {
      status.textContent = "Write token required.";
      return;
    }
    researchWriteToken = token;
    saveResearchToken(token);
    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    const title = $("rtitle").value.trim();
    const source = $("rsource").value.trim();
    const project = $("rproject").value.trim();
    const sourceBody = $("rbody").value.trim();
    const caption = $("rcaption").value.trim();
    const tags = $("rtags").value.trim();
    const rights = $("rrights").value.trim();
    const attribution = $("rattribution").value.trim();
    if (title) fd.append("title", title);
    fd.append("source_url", source);
    fd.append("body", sourceBody);
    if (project) fd.append("project_id", project);
    if (caption) fd.append("caption", caption);
    if (tags) fd.append("tags", tags);
    if (rights) fd.append("rights", rights);
    if (attribution) fd.append("attribution", attribution);

    btn.disabled = true;
    status.textContent = "Storing in Vellum and Mneme…";
    try {
      const res = await fetch("/api/visual-research/bundles", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status === 403) {
          // Stored token was rejected — forget it so the next attempt re-prompts.
          researchWriteToken = "";
          saveResearchToken("");
        }
        const detail = body.detail || res.statusText || "upload_failed";
        throw new Error(detail);
      }
      status.textContent = "Stored in Vellum and Mneme.";
      fileInput.value = "";
      $("rtitle").value = "";
      $("rcaption").value = "";
      $("rsource").value = "";
      $("rbody").value = "";
      await refreshResearch();
    } catch (err) {
      status.textContent = `Failed: ${err.message || err}`;
      console.error(err);
    } finally {
      btn.disabled = false;
    }
  });
}

loadStats().catch(console.error);
refresh().catch(console.error);
startLiveOps();
