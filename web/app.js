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

async function loadStats() {
  const s = await fetchJson("/api/register/summary");
  const host = $("stats");
  clear(host);
  for (const [n, label] of [
    [s.count, "assets"],
    [s.redeem_open, "redeem open"],
    [s.redeem_expired, "redeem expired"],
  ]) {
    const div = document.createElement("div");
    div.className = "stat";
    const strong = document.createElement("strong");
    strong.textContent = String(n);
    div.append(strong, document.createTextNode(` ${label}`));
    host.appendChild(div);
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

    const tdRedeem = document.createElement("td");
    tdRedeem.appendChild(makePill(a.redeem_window));
    const deadline = document.createElement("span");
    deadline.className = "deadline";
    deadline.textContent = formatDeadline(a.redemption_deadline);
    tdRedeem.appendChild(deadline);

    const tdFit = document.createElement("td");
    tdFit.className = "fit";
    tdFit.textContent = a.project_fit || "";

    tr.append(tdIdx, tdName, tdEngine, tdType, tdRedeem, tdFit);
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

  // ---- Capture (primary) ----
  const captureSec = document.createElement("section");
  captureSec.className = "detail-section";
  const captureHead = document.createElement("h3");
  captureHead.textContent = "Capture";
  captureSec.appendChild(captureHead);

  let activeHost = null;
  try {
    const hostsPayload = await fetchJson("/api/ue/hosts");
    activeHost = hostsPayload.active_host || null;
  } catch (err) {
    console.warn(err);
  }

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

  // ---- Lookdev ----
  const lookdevSec = document.createElement("section");
  lookdevSec.className = "detail-section";
  const lookdevHead = document.createElement("h3");
  lookdevHead.textContent = "Lookdev";
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
          content_root: "/Game/FireworksV1",
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
  const redeem = $("redeem").value;
  if (q) params.set("q", q);
  if (engine) params.set("engine", engine);
  if (redeem) params.set("redeem", redeem);
  const qs = params.toString();
  const data = await fetchJson(`/api/assets${qs ? `?${qs}` : ""}`);
  renderRows(data.assets || []);
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
$("redeem").addEventListener("change", refresh);

loadStats().catch(console.error);
refresh().catch(console.error);
