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
      : status === "blocked" || status === "failed"
        ? "expired"
        : status === "needs-human" || status === "queued" || status === "running"
          ? "needs"
          : "unknown";
  span.className = `pill ${kind}`;
  span.textContent = status || "unknown";
  return span;
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
  const a = await fetchJson(`/api/assets/${encodeURIComponent(id)}`);
  const host = $("detail-body");
  clear(host);

  const h2 = document.createElement("h2");
  h2.textContent = a.display_name || a.id;
  host.appendChild(h2);
  host.appendChild(makePill(a.redeem_window));

  const actions = document.createElement("div");
  actions.className = "detail-actions";
  const proposeBtn = document.createElement("button");
  proposeBtn.type = "button";
  proposeBtn.className = "btn";
  proposeBtn.textContent = "Propose intake";
  proposeBtn.addEventListener("click", async () => {
    proposeBtn.disabled = true;
    proposeBtn.textContent = "Proposing…";
    try {
      await proposeIntake(a.id);
      await openDetail(a.id);
    } catch (err) {
      proposeBtn.textContent = "Propose failed";
      console.error(err);
    }
  });
  actions.appendChild(proposeBtn);
  host.appendChild(actions);

  const dl = document.createElement("dl");
  addDlRow(dl, "Id", a.id);
  addDlRow(dl, "Engine / type", `${a.engine || ""} · ${a.package_type || ""}`);
  addDlRow(dl, "Store", a.store_label || a.store_lane || "");
  addDlRow(dl, "Redeem by", formatDeadline(a.redemption_deadline));
  addDlRow(dl, "Status", a.redemption_status || "not_recorded");
  addDlRow(dl, "Project fit", a.project_fit || "");
  addDlRow(dl, "Source bundle", a.source_bundle || "");
  addDlRow(dl, "Scratch", a.scratch_project_status || "not_recorded");
  if (a.scratch_project_path) {
    addDlRow(dl, "Scratch path", a.scratch_project_path);
  }
  if (a.scratch_engine_version) {
    addDlRow(dl, "Scratch engine", a.scratch_engine_version);
  }
  host.appendChild(dl);

  const note = document.createElement("p");
  note.className = "fit";
  note.style.marginTop = "1.25rem";
  note.textContent =
    "Expired redeem window only means we may not re-fetch from the store — it does not invalidate staged assets.";
  host.appendChild(note);

  const intakeHead = document.createElement("h3");
  intakeHead.textContent = "Intake";
  intakeHead.style.marginTop = "1.5rem";
  host.appendChild(intakeHead);

  const latest = document.createElement("div");
  latest.id = "intake-latest";
  host.appendChild(latest);

  try {
    const listed = await fetchJson(
      `/api/intake?asset_id=${encodeURIComponent(a.id)}&limit=3`
    );
    const runs = listed.runs || [];
    if (!runs.length) {
      const empty = document.createElement("p");
      empty.className = "fit";
      empty.textContent = "No IntakeRuns yet. Propose one to get a step plan.";
      latest.appendChild(empty);
    } else {
      for (const run of runs) renderIntakeRun(latest, run);
    }
  } catch (err) {
    console.error(err);
  }

  const jobsHead = document.createElement("h3");
  jobsHead.textContent = "Jobs";
  jobsHead.style.marginTop = "1.5rem";
  host.appendChild(jobsHead);

  const jobsHost = document.createElement("div");
  jobsHost.className = "jobs-list";
  host.appendChild(jobsHost);

  try {
    const jobsListed = await fetchJson(
      `/api/jobs?asset_id=${encodeURIComponent(a.id)}`
    );
    const jobs = jobsListed.jobs || [];
    if (!jobs.length) {
      const empty = document.createElement("p");
      empty.className = "fit";
      empty.textContent = "No jobs yet. Enqueue automatable steps from an IntakeRun.";
      jobsHost.appendChild(empty);
    } else {
      for (const job of jobs.slice(0, 8)) {
        const row = document.createElement("div");
        row.className = "job-row";
        const label = document.createElement("span");
        label.textContent = `${job.kind} · ${job.job_id}`;
        row.appendChild(label);
        row.appendChild(makeStatusPill(job.status));
        jobsHost.appendChild(row);
        if (job.error) {
          const err = document.createElement("p");
          err.className = "fit";
          err.textContent = job.error;
          jobsHost.appendChild(err);
        }
      }
    }
  } catch (err) {
    console.error(err);
  }

  const scratchHead = document.createElement("h3");
  scratchHead.textContent = "Unreal capture";
  scratchHead.style.marginTop = "1.5rem";
  host.appendChild(scratchHead);

  const captureHelp = document.createElement("p");
  captureHelp.className = "fit";
  captureHelp.textContent =
    "Queues a job for the Windows UE agent (no Unreal clicking). Keep vellum_ue_agent.ps1 running on the active host (Aurora primary / Borealis secondary — only one at a time).";
  host.appendChild(captureHelp);

  const hostMeta = document.createElement("p");
  hostMeta.className = "fit";
  hostMeta.textContent = "Loading UE host profile…";
  host.appendChild(hostMeta);

  let activeHost = null;
  try {
    const hostsPayload = await fetchJson("/api/ue/hosts");
    activeHost = hostsPayload.active_host || null;
    const labels = (hostsPayload.hosts || [])
      .map((h) => `${h.id}${h.active ? " (active)" : ""}`)
      .join(", ");
    hostMeta.textContent = activeHost
      ? `Active host: ${activeHost.label || activeHost.id} · profiles: ${labels}`
      : `UE hosts: ${labels}`;
  } catch (err) {
    hostMeta.textContent = "UE host profiles unavailable — using local defaults.";
    console.warn(err);
  }

  const scratchForm = document.createElement("div");
  scratchForm.className = "scratch-form";
  const pathLabel = document.createElement("label");
  pathLabel.className = "field grow";
  const pathSpan = document.createElement("span");
  pathSpan.textContent = "Unreal project path";
  const pathInput = document.createElement("input");
  pathInput.type = "text";
  const hostProject =
    (activeHost && (activeHost.project_dir || activeHost.project)) || "";
  pathInput.placeholder = hostProject || "F:\\Games\\AuroraVellum";
  // Prefer active host (Aurora) over a stale Borealis path on the asset.
  pathInput.value = hostProject || a.scratch_project_path || "F:\\Games\\AuroraVellum";
  pathLabel.appendChild(pathSpan);
  pathLabel.appendChild(pathInput);
  scratchForm.appendChild(pathLabel);

  const engLabel = document.createElement("label");
  engLabel.className = "field";
  const engSpan = document.createElement("span");
  engSpan.textContent = "Engine";
  const engInput = document.createElement("input");
  engInput.type = "text";
  engInput.placeholder = "5.8";
  engInput.value =
    (activeHost && activeHost.engine_version) ||
    a.scratch_engine_version ||
    "5.8";
  engLabel.appendChild(engSpan);
  engLabel.appendChild(engInput);
  scratchForm.appendChild(engLabel);

  const captureBtn = document.createElement("button");
  captureBtn.type = "button";
  captureBtn.className = "btn";
  captureBtn.textContent = "Capture from Unreal";
  captureBtn.addEventListener("click", async () => {
    captureBtn.disabled = true;
    captureBtn.textContent = "Queuing…";
    try {
      let intakeRunId = null;
      try {
        const listed = await fetchJson(
          `/api/intake?asset_id=${encodeURIComponent(a.id)}&limit=1`
        );
        intakeRunId = (listed.runs && listed.runs[0] && listed.runs[0].run_id) || null;
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
        }),
      });
      if (!res.ok) throw new Error(`ue capture ${res.status}`);
      const body = await res.json();
      captureBtn.textContent = `Queued ${body.job && body.job.job_id ? body.job.job_id : ""}`;
      setTimeout(() => openDetail(a.id), 1500);
    } catch (err) {
      captureBtn.textContent = "Queue failed";
      console.error(err);
    }
  });
  scratchForm.appendChild(captureBtn);
  host.appendChild(scratchForm);

  const lookdevHead = document.createElement("h3");
  lookdevHead.textContent = "Lookdev";
  lookdevHead.style.marginTop = "1.5rem";
  host.appendChild(lookdevHead);

  const lookdevActions = document.createElement("div");
  lookdevActions.className = "detail-actions";
  const deriveBtn = document.createElement("button");
  deriveBtn.type = "button";
  deriveBtn.className = "btn";
  deriveBtn.textContent = "Derive lookdev stills";
  deriveBtn.addEventListener("click", async () => {
    deriveBtn.disabled = true;
    deriveBtn.textContent = "Queuing…";
    try {
      const res = await fetch("/api/lookdev/derive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset_id: a.id }),
      });
      if (!res.ok) throw new Error(`derive ${res.status}`);
      deriveBtn.textContent = "Queued";
      setTimeout(() => openDetail(a.id), 1500);
    } catch (err) {
      deriveBtn.textContent = "Derive failed";
      console.error(err);
    }
  });
  lookdevActions.appendChild(deriveBtn);

  const fileLabel = document.createElement("label");
  fileLabel.className = "btn btn-secondary file-btn";
  fileLabel.textContent = "Upload Niagara render";
  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = "image/png,image/jpeg,image/webp";
  fileInput.hidden = true;
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;
    fileLabel.textContent = "Uploading…";
    try {
      const fd = new FormData();
      fd.append("asset_id", a.id);
      fd.append("lane", "slots");
      fd.append("note", "Niagara viewport still from Unreal scratch");
      fd.append("file", file, file.name);
      const res = await fetch("/api/lookdev/ingest-render", {
        method: "POST",
        body: fd,
      });
      if (!res.ok) throw new Error(`ingest ${res.status}`);
      await openDetail(a.id);
    } catch (err) {
      fileLabel.textContent = "Upload failed";
      console.error(err);
    }
  });
  fileLabel.appendChild(fileInput);
  fileLabel.addEventListener("click", () => fileInput.click());
  lookdevActions.appendChild(fileLabel);
  host.appendChild(lookdevActions);

  const lookdevHost = document.createElement("div");
  lookdevHost.className = "lookdev-grid";
  host.appendChild(lookdevHost);

  try {
    const derived = await fetchJson(
      `/api/lookdev/outputs?asset_id=${encodeURIComponent(a.id)}`
    );
    const outputs = derived.outputs || [];
    if (!outputs.length) {
      const empty = document.createElement("p");
      empty.className = "fit";
      empty.textContent =
        "No derived stills yet. Requires staged pack with png/jpg textures.";
      lookdevHost.appendChild(empty);
    } else {
      for (const out of outputs.slice(0, 12)) {
        const card = document.createElement("figure");
        card.className = "lookdev-card";
        const img = document.createElement("img");
        img.src = `/api/lookdev/outputs/${encodeURIComponent(out.id)}/file`;
        img.alt = `${out.lane} ${out.kind}`;
        img.loading = "lazy";
        card.appendChild(img);
        const cap = document.createElement("figcaption");
        cap.textContent = `${out.lane} · ${out.kind}`;
        card.appendChild(cap);
        lookdevHost.appendChild(card);
      }
    }
  } catch (err) {
    console.error(err);
  }

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
