(function () {
  "use strict";

  const NAV_KEY = "vellum.journey.navigation.hidden";
  const EASTERN_ZONE = "America/New_York";
  const KANON_ROUTE = "#/assets/:asset_id";
  const KANON_SLOTS = new Set([
    "vellum.asset.identity",
    "vellum.asset.transformation",
    "vellum.asset.journey",
    "vellum.asset.outputs",
    "vellum.asset.destinations",
    "vellum.asset.evidence-footer",
  ]);
  let navigationKeydownHandler = null;
  const root = document.getElementById("journey-root");
  const legacy = document.getElementById("legacy-app");
  if (!root || !legacy) return;

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function assetIdFromHash() {
    const match = window.location.hash.match(/^#\/assets\/([^/?#]+)/);
    if (!match) return null;
    try {
      return decodeURIComponent(match[1]);
    } catch {
      return null;
    }
  }

  function requestedSection() {
    const query = window.location.hash.split("?", 2)[1] || "";
    return new URLSearchParams(query).get("section");
  }

  function routeFor(assetId, section) {
    const base = `#/assets/${encodeURIComponent(assetId)}`;
    return section ? `${base}?section=${encodeURIComponent(section)}` : base;
  }

  function workspaceHref(view) {
    const url = new URL(window.location.href);
    url.hash = "#/";
    if (view && view !== "register") url.searchParams.set("view", view);
    else url.searchParams.delete("view");
    return `${url.pathname}${url.search}${url.hash}`;
  }

  function formatEastern(iso, includeTime = true) {
    if (!iso) return null;
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return null;
    const options = includeTime
      ? {
          timeZone: EASTERN_ZONE,
          month: "short",
          day: "numeric",
          year: "numeric",
          hour: "numeric",
          minute: "2-digit",
          timeZoneName: "short",
        }
      : { timeZone: EASTERN_ZONE, month: "long", day: "numeric", year: "numeric" };
    return new Intl.DateTimeFormat("en-US", options).format(date);
  }

  function easternLabel(iso) {
    const date = new Date(iso || Date.now());
    const part = new Intl.DateTimeFormat("en-US", {
      timeZone: EASTERN_ZONE,
      timeZoneName: "short",
    })
      .formatToParts(date)
      .find((item) => item.type === "timeZoneName");
    const name = part ? part.value : "ET";
    const offset = name === "EDT" ? "UTC−4" : name === "EST" ? "UTC−5" : "local offset";
    return `Eastern Time (${name}, ${offset})`;
  }

  function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) return "Size not recorded";
    if (bytes < 1024) return `${bytes} B`;
    const units = ["KB", "MB", "GB"];
    let amount = bytes / 1024;
    let index = 0;
    while (amount >= 1024 && index < units.length - 1) {
      amount /= 1024;
      index += 1;
    }
    return `${amount >= 10 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
  }

  function icon(name) {
    const paths = {
      registered: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h5M9 14l2 2 4-5"/>',
      "staged-factory": '<path d="M4 8l8-5 8 5-8 5z"/><path d="M4 8v8l8 5 8-5V8M8 11v5l4 2.5 4-2.5v-5"/>',
      "trusted-capture": '<circle cx="12" cy="12" r="3"/><path d="M12 2v5M12 17v5M2 12h5M17 12h5M5 5l3.5 3.5M15.5 15.5L19 19M19 5l-3.5 3.5M8.5 15.5L5 19"/>',
      "game-ready": '<path d="M5 7h14v12H5zM8 7V4h8v3M9 12h6M12 9v6"/>',
      destinations: '<path d="M4 6h7M4 12h11M4 18h7M11 6l3-3M11 6l3 3M15 12l3-3M15 12l3 3M11 18l3-3M11 18l3 3"/>',
    };
    return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${paths[name] || paths.registered}</svg>`;
  }

  function navigationMarkup(asset) {
    const id = asset.id;
    const activeSection = requestedSection() || "overview";
    const assetLink = (label, section, target, iconMarkup) => {
      const active = activeSection === section;
      return `<a class="journey-nav-link${active ? " active" : ""}" href="${routeFor(id, target)}"${active ? ' aria-current="page"' : ""}>${iconMarkup} ${label}</a>`;
    };
    return `
      <aside class="journey-navigation" id="journey-navigation">
        <a class="journey-brand" href="${escapeHtml(workspaceHref("register"))}" aria-label="Vellum asset register">
          <span class="journey-brand-mark" aria-hidden="true">V</span>
          <span><strong>Vellum</strong><small>Control Alt Games</small></span>
        </a>
        <button class="journey-hide-navigation" type="button" data-nav-hide aria-expanded="true" aria-controls="journey-navigation">
          <span aria-hidden="true">‹</span> Hide navigation
        </button>
        <p class="journey-nav-heading">Workspace</p>
        <nav aria-label="Vellum workspace">
          <a class="journey-nav-link" href="${escapeHtml(workspaceHref("register"))}"><span aria-hidden="true">▧</span> Asset Register</a>
          <a class="journey-nav-link" href="${escapeHtml(workspaceHref("studio"))}"><span aria-hidden="true">◇</span> Games Studio</a>
          <a class="journey-nav-link" href="${escapeHtml(workspaceHref("eidolon"))}"><span aria-hidden="true">◉</span> Eidolon Renders</a>
          <a class="journey-nav-link" href="${escapeHtml(workspaceHref("research"))}"><span aria-hidden="true">✦</span> Visual Research</a>
        </nav>
        <div class="journey-nav-rule"></div>
        <p class="journey-nav-heading">Current Asset</p>
        <nav aria-label="Current asset sections">
          ${assetLink("Overview", "overview", null, '<span class="journey-nav-dot" aria-hidden="true"></span>')}
          ${assetLink("Intake", "journey", "journey", '<span class="journey-nav-dot" aria-hidden="true"></span>')}
          ${assetLink("Lookdev", "transformation", "transformation", '<span class="journey-nav-dot" aria-hidden="true"></span>')}
          ${assetLink("Game-ready", "outputs", "outputs", '<span class="journey-nav-dot" aria-hidden="true"></span>')}
        </nav>
      </aside>`;
  }

  function transformationCard(item, emptyLabel) {
    if (!item) {
      return `<div class="journey-transform-card empty"><span>${escapeHtml(emptyLabel)}</span><small>No trustworthy image evidence is available.</small></div>`;
    }
    const media = item.preview === "video"
      ? `<video src="${escapeHtml(item.file_href)}" aria-label="${escapeHtml(item.label)}" muted playsinline preload="auto" data-featured-video data-preview-time="${escapeHtml(item.preview_time_seconds ?? "")}" data-rest-frame data-media-fallback="${escapeHtml(item.label)} is unavailable"></video>`
      : `<img src="${escapeHtml(item.file_href)}" alt="${escapeHtml(item.label)}" loading="eager" data-media-fallback="${escapeHtml(item.label)} is unavailable">`;
    return `
      <figure class="journey-transform-card">
        <figcaption>${escapeHtml(item.label)}</figcaption>
        ${media}
        <p>${escapeHtml(item.system_name || item.kind || "Image evidence")}</p>
        <small>${escapeHtml(formatEastern(item.created_at) || "Time not recorded")}</small>
      </figure>`;
  }

  function outputPreview(item, featured = false) {
    const href = escapeHtml(item.file_href);
    const label = escapeHtml(item.name);
    if (featured && item.preview === "video") {
      return `<a class="journey-poster-link" href="${href}" target="_blank" rel="noreferrer" aria-label="Play ${label}">
        <video src="${href}" aria-label="${label}" muted playsinline preload="auto" data-featured-video data-preview-time="${escapeHtml(item.preview_time_seconds ?? "")}" data-rest-frame data-media-fallback="Clip preview unavailable"></video>
        <span>Play clip</span>
      </a>`;
    }
    if (item.preview === "image") {
      return `<img src="${href}" alt="${label}" loading="lazy">`;
    }
    if (item.preview === "video") {
      return `<video src="${href}" aria-label="${label}" controls muted playsinline preload="none"></video>`;
    }
    if (item.preview === "audio") {
      return `<div class="journey-output-file" aria-hidden="true">♪</div><audio src="${href}" aria-label="${label}" controls preload="none"></audio>`;
    }
    return `<div class="journey-output-file" aria-hidden="true">{ }</div>`;
  }

  function technicalLine(item) {
    const tech = item.technical || {};
    const bits = [];
    if (tech.width && tech.height) bits.push(`${tech.width}×${tech.height}`);
    if (tech.duration_seconds) bits.push(`${tech.duration_seconds}s`);
    if (tech.frame_count) bits.push(`${tech.frame_count} frames`);
    if (tech.alpha === true) bits.push("alpha");
    return bits.join(" · ") || "Technical metadata not recorded";
  }

  function outputCard(item, index, featured = false) {
    const variant = (item.technical || {}).variant;
    return `
      <article class="journey-output-card${featured ? " featured" : ""}">
        <div class="journey-output-media">${outputPreview(item, featured)}</div>
        <div class="journey-output-copy">
          <p class="journey-output-index">${String(index + 1).padStart(2, "0")}</p>
          <h3>${escapeHtml(item.display_name || item.name)}</h3>
          <p class="journey-output-filename">${escapeHtml(item.name)}</p>
          <p>${escapeHtml(item.kind)}${variant ? ` · ${escapeHtml(variant)}` : ""}</p>
          <p>${escapeHtml(technicalLine(item))}</p>
          <p>${escapeHtml(formatBytes(item.bytes))} · ${escapeHtml((item.technical || {}).validation || "cataloged")}</p>
        </div>
      </article>`;
  }

  function attachmentChip(item) {
    return `<a class="journey-attachment" href="${escapeHtml(item.file_href)}" target="_blank" rel="noreferrer">
      <span><strong>${escapeHtml(item.system_name || item.name)}</strong><small>${escapeHtml(item.id)}</small></span>
    </a>`;
  }

  function destinationCard(item) {
    const stateLabel = {
      received: "Received",
      "preview-only": "Preview only",
      "no-evidence": "No evidence",
    }[item.state] || item.state;
    const receipt = item.consumer_receipt
      ? `<a class="journey-consumer-receipt" href="${escapeHtml(item.consumer_receipt.evidence_href)}" target="_blank" rel="noreferrer">
          Consumer selected · ${escapeHtml(item.consumer_receipt.surface)}<small>${escapeHtml(item.consumer_receipt.element_id)}</small>
        </a>`
      : "";
    return `
      <article class="journey-destination ${escapeHtml(item.state)}">
        <span class="journey-destination-mark" aria-hidden="true">${escapeHtml(item.mark)}</span>
        <div>
          <div class="journey-destination-head"><h3>${escapeHtml(item.name)}</h3><span>${escapeHtml(stateLabel)}</span></div>
          <p>${escapeHtml(item.detail)}</p>
          ${receipt}
          <div class="journey-attachments">${(item.attachments || []).map(attachmentChip).join("")}</div>
        </div>
      </article>`;
  }

  function renderJourney(data) {
    const latestEvidence = [
      ...data.milestones.map((item) => item.occurred_at),
      data.transformation.source?.created_at,
      data.transformation.capture?.created_at,
    ]
      .filter(Boolean)
      .sort()
      .at(-1);
    const outputs = data.outputs || [];
    const featured = data.featured_outputs || [];
    root.innerHTML = `
      <div class="journey-shell">
        ${navigationMarkup(data.asset)}
        <button class="journey-show-navigation" type="button" data-nav-show aria-expanded="false" aria-controls="journey-navigation">
          <span aria-hidden="true">›</span><span>Show navigation</span>
        </button>
        <button class="journey-nav-scrim" type="button" data-nav-hide aria-label="Close navigation"></button>
        <main class="journey-canvas" id="journey-overview">
          <header class="journey-page-header" data-kanon-slot="vellum.asset.identity">
            <div>
              <a class="journey-back" href="${escapeHtml(workspaceHref("register"))}">Asset Register</a>
              <h1>${escapeHtml(data.asset.display_name)}</h1>
              <p>${escapeHtml(data.asset.package_type || data.asset.engine || "Asset pack")}</p>
            </div>
            <p class="journey-evidence-date">${latestEvidence ? `Evidence through ${escapeHtml(formatEastern(latestEvidence, false))}` : "Evidence time not recorded"}</p>
          </header>

          <section class="journey-section" id="journey-transformation" aria-labelledby="journey-transformation-title" data-kanon-slot="vellum.asset.transformation">
            <div class="journey-section-heading">
              <div><p>01 / Evidence</p><h2 id="journey-transformation-title">Transformation</h2></div>
              <span>${escapeHtml(data.status)}</span>
            </div>
            <div class="journey-transformation-grid">
              ${transformationCard(data.transformation.source, "Source reference")}
              ${transformationCard(data.transformation.capture, "Trusted capture")}
              <aside class="journey-transform-summary">
                <strong>${escapeHtml(data.outcome.primary_count)}</strong>
                <span>${escapeHtml(data.outcome.unit_label)}</span>
                <p>${escapeHtml(data.outcome.headline)}.</p>
                <a href="${routeFor(data.asset.id, "outputs")}">View transformation <span aria-hidden="true">↗</span></a>
              </aside>
            </div>
          </section>

          <section class="journey-section" id="journey-journey" aria-labelledby="journey-title" data-kanon-slot="vellum.asset.journey">
            <div class="journey-section-heading"><div><p>02 / Provenance</p><h2 id="journey-title">Journey</h2></div></div>
            <ol class="journey-milestones">
              ${data.milestones
                .map(
                  (item, index) => `
                    <li class="${escapeHtml(item.state)}">
                      <span class="journey-step-number">${String(index + 1).padStart(2, "0")}</span>
                      <span class="journey-step-icon">${icon(item.id)}</span>
                      <strong>${escapeHtml(item.label)}</strong>
                      <time datetime="${escapeHtml(item.occurred_at || "")}">${escapeHtml(formatEastern(item.occurred_at) || item.time_note)}</time>
                      <small>${escapeHtml(item.detail)}</small>
                    </li>`
                )
                .join("")}
            </ol>
          </section>

          <section class="journey-section" id="journey-outputs" aria-labelledby="journey-outputs-title" data-kanon-slot="vellum.asset.outputs">
            <div class="journey-section-heading">
              <div><p>03 / Visible payoff</p><h2 id="journey-outputs-title">Derived outputs (${featured.length})</h2></div>
              <span>${data.counts.bandit_ready_clips ? `${escapeHtml(data.counts.bandit_ready_clips)} Bandit-ready clips` : `${escapeHtml(data.counts.published)} published artifacts`}</span>
            </div>
            <p class="journey-output-intro">${featured.length === 8 ? "Eight distinct systems" : `${escapeHtml(featured.length)} distinct outputs`}, selected from validated artifacts with stored visual evidence.</p>
            <div class="journey-output-grid">${featured.map((item, index) => outputCard(item, index, true)).join("")}</div>
            <details class="journey-technical-inventory">
              <summary>Inspect all ${outputs.length} outputs and technical evidence</summary>
              <div class="journey-technical-list">${outputs.map((item, index) => outputCard(item, index, false)).join("")}</div>
            </details>
          </section>

          <section class="journey-section" id="journey-destinations" aria-labelledby="journey-destinations-title" data-kanon-slot="vellum.asset.destinations">
            <div class="journey-section-heading"><div><p>04 / Delivery</p><h2 id="journey-destinations-title">Destinations</h2></div></div>
            <div class="journey-destination-grid">${data.destinations.map(destinationCard).join("")}</div>
          </section>

          <footer class="journey-footer" data-kanon-slot="vellum.asset.evidence-footer">All times shown in ${escapeHtml(easternLabel(latestEvidence))}. · Evidence is read from Vellum authorities, not inferred from this page.</footer>
        </main>
      </div>`;

    wireNavigation();
    wireMediaFallbacks();
    wireFeaturedRestFrames();
    wireAssetPalette();
    const section = requestedSection();
    if (section) {
      window.requestAnimationFrame(() => {
        document.getElementById(`journey-${section}`)?.scrollIntoView({ block: "start" });
      });
    }
  }

  function rgbToHsl(red, green, blue) {
    const r = red / 255;
    const g = green / 255;
    const b = blue / 255;
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    const lightness = (max + min) / 2;
    const delta = max - min;
    if (!delta) return { hue: 0, saturation: 0, lightness };
    const saturation = delta / (1 - Math.abs(2 * lightness - 1));
    let hue = max === r
      ? ((g - b) / delta) % 6
      : max === g
        ? (b - r) / delta + 2
        : (r - g) / delta + 4;
    hue = Math.round(hue * 60);
    if (hue < 0) hue += 360;
    return { hue, saturation, lightness };
  }

  function wireAssetPalette() {
    const image = root.querySelector('[data-kanon-slot="vellum.asset.transformation"] img');
    if (!image) return;
    const sample = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = 72;
        canvas.height = 48;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        if (!context) return;
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
        const buckets = new Map();
        for (let index = 0; index < pixels.length; index += 16) {
          if (pixels[index + 3] < 200) continue;
          const color = rgbToHsl(pixels[index], pixels[index + 1], pixels[index + 2]);
          if (color.saturation < 0.48 || color.lightness < 0.22 || color.lightness > 0.78) continue;
          const bucket = Math.round(color.hue / 24) * 24 % 360;
          const current = buckets.get(bucket) || { score: 0, r: 0, g: 0, b: 0, count: 0 };
          const weight = color.saturation * (1 - Math.abs(0.52 - color.lightness));
          current.score += weight;
          current.r += pixels[index] * weight;
          current.g += pixels[index + 1] * weight;
          current.b += pixels[index + 2] * weight;
          current.count += weight;
          buckets.set(bucket, current);
        }
        const colors = [...buckets.values()]
          .sort((left, right) => right.score - left.score)
          .slice(0, 5)
          .map((value) => `rgb(${Math.round(value.r / value.count)} ${Math.round(value.g / value.count)} ${Math.round(value.b / value.count)})`);
        if (colors.length < 3) return;
        colors.forEach((color, index) => root.style.setProperty(`--journey-asset-${index + 1}`, color));
        root.setAttribute("data-asset-palette", "sampled-from-source");
      } catch {
        root.setAttribute("data-asset-palette", "fallback");
      }
    };
    if (image.complete && image.naturalWidth) sample();
    else image.addEventListener("load", sample, { once: true });
  }

  function wireMediaFallbacks() {
    root.querySelectorAll("[data-media-fallback]").forEach((media) => {
      media.addEventListener("error", () => {
        const fallback = document.createElement("span");
        fallback.className = "journey-media-error";
        fallback.textContent = media.dataset.mediaFallback || "Visual evidence unavailable";
        media.replaceWith(fallback);
      }, { once: true });
    });
  }

  function wireFeaturedRestFrames() {
    root.querySelectorAll("video[data-rest-frame]").forEach((video) => {
      video.dataset.restFrameWired = "true";
      const showValidatedSample = () => {
        if (Number.isFinite(video.duration) && video.duration > 0) {
          const recorded = Number(video.dataset.previewTime);
          const fallback = video.duration / 2;
          video.currentTime = Math.min(Number.isFinite(recorded) && recorded >= 0 ? recorded : fallback, Math.max(0, video.duration - 0.034));
          video.dataset.restFrameCue = String(video.currentTime);
        }
      };
      if (video.readyState >= 1) showValidatedSample();
      // Metadata can be reloaded when a governed composition clones/moves the
      // slot or a browser reclaims media. Re-seek every time so the evidence
      // never falls back to a blank opening frame.
      video.addEventListener("loadedmetadata", showValidatedSample);
    });
  }

  function storedNavHidden() {
    try {
      return window.localStorage.getItem(NAV_KEY) === "true";
    } catch {
      return false;
    }
  }

  function persistNavHidden(hidden) {
    try {
      window.localStorage.setItem(NAV_KEY, String(hidden));
    } catch {
      /* device preference remains session-local when storage is unavailable */
    }
  }

  function wireNavigation() {
    const shell = root.querySelector(".journey-shell");
    const navigation = root.querySelector(".journey-navigation");
    const show = root.querySelector("[data-nav-show]");
    const hides = root.querySelectorAll("[data-nav-hide]");
    if (!shell || !navigation || !show) return;
    if (storedNavHidden()) shell.classList.add("nav-hidden");

    const syncAria = () => {
      const mobileOpen = shell.classList.contains("nav-drawer-open");
      const visible = window.matchMedia("(max-width: 860px)").matches
        ? mobileOpen
        : !shell.classList.contains("nav-hidden");
      show.setAttribute("aria-expanded", String(visible));
      root.querySelector(".journey-hide-navigation")?.setAttribute("aria-expanded", String(visible));
    };
    syncAria();

    show.addEventListener("click", () => {
      if (window.matchMedia("(max-width: 860px)").matches) {
        shell.classList.add("nav-drawer-open");
        window.requestAnimationFrame(() => root.querySelector(".journey-hide-navigation")?.focus());
      } else {
        shell.classList.remove("nav-hidden");
        persistNavHidden(false);
      }
      syncAria();
    });
    hides.forEach((button) => {
      button.addEventListener("click", () => {
        if (window.matchMedia("(max-width: 860px)").matches) {
          shell.classList.remove("nav-drawer-open");
          show.focus();
        } else {
          shell.classList.add("nav-hidden");
          persistNavHidden(true);
        }
        syncAria();
      });
    });
    if (navigationKeydownHandler) document.removeEventListener("keydown", navigationKeydownHandler);
    navigationKeydownHandler = (event) => {
      if (event.key === "Escape" && shell.classList.contains("nav-drawer-open")) {
        shell.classList.remove("nav-drawer-open");
        syncAria();
        show.focus();
      }
    };
    document.addEventListener("keydown", navigationKeydownHandler);
  }

  function safeKanonToken(name, value) {
    return /^--ca-[a-z0-9-]+$/.test(name)
      && typeof value === "string"
      && value.length < 512
      && !/[{};]/.test(value)
      && !/(?:url|expression)\s*\(/i.test(value);
  }

  function applyKanonDirection(snapshot) {
    if (snapshot?.schema_version !== 1 || snapshot.authority !== "kanon" || snapshot.app_id !== "vellum") {
      return false;
    }
    const direction = snapshot.visual_direction || {};
    const definition = direction.definition || {};
    const variants = direction.resolved_variants || {};
    // Vellum's governed expression is editorial-catalog / games / airy / subtle.
    // A migrated Kanon release without a games variant must not silently restyle
    // the leaf as Core light or dark; the canonical local games tokens remain the
    // safe fallback until Kanon publishes the correct variant.
    const tokens = variants.games;
    root.dataset.caTheme = "games";
    root.dataset.caSurfaceRecipe = "editorial-catalog";
    root.dataset.caDensity = tokens ? (definition.density || "airy") : "airy";
    root.dataset.caMotion = tokens ? (definition.motion || "subtle") : "subtle";
    root.dataset.caShape = tokens ? (definition.shape || "subtle") : "subtle";
    if (tokens && typeof tokens === "object") {
      if (Object.entries(tokens).some(([name, value]) => !safeKanonToken(name, value))) return false;
      Object.entries(tokens).forEach(([name, value]) => {
        root.style.setProperty(name, value);
      });
    }
    const recipes = definition.recipes || {};
    Object.entries(recipes).forEach(([name, value]) => {
      if (typeof value === "string") root.dataset[`caRecipe${name[0].toUpperCase()}${name.slice(1)}`] = value;
    });
    const logoUrl = snapshot.branding?.logo_url;
    if (typeof logoUrl === "string" && logoUrl.trim()) {
      try {
        const url = new URL(logoUrl, window.location.origin);
        if (["http:", "https:"].includes(url.protocol)) {
          const mark = root.querySelector(".journey-brand-mark");
          if (mark) {
            mark.textContent = "";
            const logo = document.createElement("img");
            logo.src = url.href;
            logo.alt = "";
            mark.appendChild(logo);
          }
        }
      } catch {
        /* the local V placeholder remains the explicit unauthored-brand fallback */
      }
    }
    root.setAttribute("data-kanon-theme-status", tokens ? "applied" : "fallback-no-games-variant");
    return true;
  }

  function resolveKanonField(value, path) {
    let current = value;
    for (const part of String(path || "").split(".")) {
      if (!part || ["__proto__", "prototype", "constructor"].includes(part)) return undefined;
      if (!current || typeof current !== "object" || !Object.prototype.hasOwnProperty.call(current, part)) return undefined;
      current = current[part];
    }
    return current;
  }

  function formatKanonValue(value, format) {
    if (value == null) return "—";
    if (format === "number") return typeof value === "number" ? new Intl.NumberFormat().format(value) : "—";
    if (format === "boolean") return value === true ? "true" : value === false ? "false" : "—";
    if (format === "yes-no") return value === true ? "Yes" : value === false ? "No" : "—";
    return ["string", "number", "boolean"].includes(typeof value) ? String(value) : "—";
  }

  function kanonElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = text;
    return element;
  }

  function validateKanonNode(node, runtime, seen) {
    const containers = new Set(["layout.stack", "layout.grid", "layout.split", "surface.section", "action.row"]);
    const allowedProps = {
      "layout.stack": new Set(["gap"]),
      "layout.grid": new Set(["columns", "gap"]),
      "layout.split": new Set(["ratio", "gap"]),
      "page.header": new Set(["eyebrow", "title", "lead"]),
      "surface.section": new Set(["title", "description"]),
      "data.description-list": new Set(["fields"]),
      "data.metric-strip": new Set(["fields"]),
      "data.status-list": new Set(["fields"]),
      "data.table": new Set(["columns"]),
      "content.text": new Set(["text", "tone"]),
      "action.link": new Set(["link", "label", "variant", "target"]),
      "action.row": new Set(["actions"]),
      "slot.custom": new Set(["slot"]),
    };
    const allowedKeys = new Set(["id", "type", "props", "source", "visible_when", "children"]);
    if (!node || typeof node !== "object" || !/^[a-z][a-z0-9_]*$/.test(String(node.id || "")) || seen.has(node.id)) {
      throw new Error("invalid_composition_node");
    }
    if (Object.keys(node).some((key) => !allowedKeys.has(key))) throw new Error("unknown_node_property");
    if (!allowedProps[node.type]) throw new Error("unsupported_node_type");
    if (!node.props || typeof node.props !== "object" || Array.isArray(node.props)) throw new Error("invalid_node_props");
    if (Object.keys(node.props).some((key) => !allowedProps[node.type].has(key))) throw new Error("unknown_node_prop");
    if (!Array.isArray(node.children || [])) throw new Error("invalid_children");
    if ((node.children || []).length && !containers.has(node.type)) throw new Error("children_on_leaf");
    seen.add(node.id);
    const visibility = node.visible_when || [];
    if (!Array.isArray(visibility) || visibility.some((condition) =>
      !condition || typeof condition !== "object" || Object.keys(condition).some((key) => !["context", "operator", "value"].includes(key))
      || condition.context !== "embed" || condition.operator !== "equals" || typeof condition.value !== "boolean"
    )) throw new Error("invalid_visibility");
    const gap = node.props.gap || "medium";
    if (node.type.startsWith("layout.") && !["small", "medium", "large"].includes(gap)) throw new Error("invalid_gap");
    if (node.type === "layout.grid" && !["1", "1-2", "1-2-4"].includes(node.props.columns || "1-2")) throw new Error("invalid_columns");
    if (node.type === "layout.split" && !["1-1", "1-2", "2-1"].includes(node.props.ratio || "1-1")) throw new Error("invalid_ratio");
    if (["page.header", "surface.section"].includes(node.type)) {
      const keys = node.type === "page.header" ? ["eyebrow", "title", "lead"] : ["title", "description"];
      if (keys.some((key) => key in node.props && typeof node.props[key] !== "string")) throw new Error("invalid_text_prop");
    }
    if (node.type === "content.text" && (typeof node.props.text !== "string" || !["primary", "secondary", "muted"].includes(node.props.tone || "secondary"))) {
      throw new Error("invalid_content_text");
    }
    if (node.type?.startsWith("data.")) {
      if (node.source !== "vellum.asset.journey") throw new Error("unknown_data_source");
      if (node.type === "data.table" && !Array.isArray(runtime.data)) throw new Error("invalid_table_data");
      const fields = node.props[node.type === "data.table" ? "columns" : "fields"];
      if (!Array.isArray(fields) || fields.some((field) =>
        !field || typeof field !== "object" || Object.keys(field).some((key) => !["label", "path", "format"].includes(key))
        || typeof field.label !== "string" || !field.label.trim()
        || typeof field.path !== "string" || !/^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$/.test(field.path)
        || field.path.split(".").some((part) => ["__proto__", "prototype", "constructor"].includes(part))
        || !["text", "number", "boolean", "yes-no", "status"].includes(field.format || "text")
      )) throw new Error("invalid_data_fields");
    } else if (node.source != null) {
      throw new Error("source_on_non_data_node");
    }
    if (node.type === "action.link") {
      if (node.props.link !== "vellum.assets.detail") throw new Error("unknown_link");
      if (typeof node.props.label !== "string" || !node.props.label.trim()) throw new Error("invalid_link_label");
      if (!["primary", "secondary", "outline", "link"].includes(node.props.variant || "link")) throw new Error("invalid_link_variant");
      if (!["_self", "_blank"].includes(node.props.target || "_self")) throw new Error("invalid_link_target");
    }
    if (node.type === "action.row") {
      if (!Array.isArray(node.props.actions || []) || (node.props.actions || []).length) throw new Error("unknown_action");
    }
    if (node.type === "slot.custom") {
      const slot = String(node.props?.slot || "");
      if (!KANON_SLOTS.has(slot) || !runtime.slots.has(slot)) throw new Error("unknown_slot");
    }
    for (const child of node.children || []) validateKanonNode(child, runtime, seen);
  }

  function renderKanonDataNode(node, data) {
    const fields = node.props?.[node.type === "data.table" ? "columns" : "fields"];
    if (!Array.isArray(fields)) throw new Error("invalid_data_fields");
    if (node.type === "data.table") {
      if (!Array.isArray(data)) throw new Error("invalid_table_data");
      const wrapper = kanonElement("div", "journey-kanon-table-wrap");
      const table = document.createElement("table");
      const head = table.createTHead().insertRow();
      fields.forEach((field) => head.appendChild(kanonElement("th", "", field.label)));
      const body = table.createTBody();
      data.forEach((row) => {
        const tr = body.insertRow();
        fields.forEach((field) => tr.appendChild(kanonElement("td", "", formatKanonValue(resolveKanonField(row, field.path), field.format))));
      });
      wrapper.appendChild(table);
      return wrapper;
    }
    const kind = node.type.replace("data.", "").replace("-list", "");
    const list = kanonElement("dl", `journey-kanon-data journey-kanon-data-${kind}`);
    fields.forEach((field) => {
      const item = kanonElement("div", "journey-kanon-field");
      item.append(
        kanonElement("dt", "", field.label),
        kanonElement("dd", "", formatKanonValue(resolveKanonField(data, field.path), field.format))
      );
      list.appendChild(item);
    });
    return list;
  }

  function renderKanonNode(node, runtime, seen) {
    if (!node || typeof node !== "object" || !/^[a-z][a-z0-9_]*$/.test(String(node.id || "")) || seen.has(node.id)) {
      throw new Error("invalid_composition_node");
    }
    seen.add(node.id);
    if ((node.visible_when || []).some((condition) => condition.context === "embed" && condition.value !== runtime.embed)) {
      return document.createDocumentFragment();
    }
    const props = node.props || {};
    let element;
    if (["layout.stack", "layout.grid", "layout.split"].includes(node.type)) {
      element = kanonElement("div", `journey-kanon-${node.type.replace(".", "-")}`);
      if (props.gap) element.dataset.gap = props.gap;
      if (props.columns) element.dataset.columns = props.columns;
      if (props.ratio) element.dataset.ratio = props.ratio;
    } else if (node.type === "surface.section") {
      element = kanonElement("section", "journey-kanon-section");
      if (props.title) element.appendChild(kanonElement("h2", "", props.title));
      if (props.description) element.appendChild(kanonElement("p", "", props.description));
    } else if (node.type === "page.header") {
      element = kanonElement("header", "journey-kanon-header");
      if (props.eyebrow) element.appendChild(kanonElement("p", "journey-back", props.eyebrow));
      if (props.title) element.appendChild(kanonElement("h1", "", props.title));
      if (props.lead) element.appendChild(kanonElement("p", "", props.lead));
    } else if (node.type === "content.text") {
      element = kanonElement("p", `journey-kanon-text tone-${props.tone || "secondary"}`, props.text || "");
    } else if (node.type?.startsWith("data.")) {
      if (node.source !== "vellum.asset.journey") throw new Error("unknown_data_source");
      element = renderKanonDataNode(node, runtime.data);
    } else if (node.type === "action.link") {
      if (props.link !== "vellum.assets.detail") throw new Error("unknown_link");
      element = kanonElement("a", `journey-kanon-link variant-${props.variant || "link"}`, props.label);
      element.href = routeFor(runtime.data.asset.id);
      element.target = props.target === "_blank" ? "_blank" : "_self";
    } else if (node.type === "action.row") {
      if ((props.actions || []).length) throw new Error("unknown_action");
      element = kanonElement("div", "journey-kanon-actions");
    } else if (node.type === "slot.custom") {
      const slot = String(props.slot || "");
      if (!KANON_SLOTS.has(slot) || !runtime.slots.has(slot)) throw new Error("unknown_slot");
      return runtime.slots.get(slot).cloneNode(true);
    } else {
      throw new Error("unsupported_node_type");
    }
    element.dataset.kanonNode = node.id;
    for (const child of node.children || []) element.appendChild(renderKanonNode(child, runtime, seen));
    return element;
  }

  function applyKanonComposition(snapshot, data) {
    const currentRoute = window.location.hash.split("?", 1)[0];
    const route = snapshot.routes?.[currentRoute] || snapshot.routes?.[KANON_ROUTE];
    if (!route) return { rendered: false, reason: "route_not_bound" };
    const documentValue = route.document;
    if (
      documentValue?.schema_version !== 1
      || typeof documentValue.title !== "string"
      || !documentValue.root
      || Object.keys(documentValue).some((key) => !["schema_version", "title", "root", "preview_data"].includes(key))
      || (documentValue.preview_data != null && (typeof documentValue.preview_data !== "object" || Array.isArray(documentValue.preview_data)))
    ) return { rendered: false, reason: "invalid_composition" };
    const canvas = root.querySelector(".journey-canvas");
    if (!canvas) return { rendered: false, reason: "missing_local_canvas" };
    const slots = new Map();
    canvas.querySelectorAll("[data-kanon-slot]").forEach((element) => slots.set(element.dataset.kanonSlot, element));
    try {
      const runtime = { data, slots, embed: window.self !== window.top };
      // Validate the complete tree before moving any local slot into the detached
      // composition. Invalid delivery therefore leaves the local page untouched.
      validateKanonNode(documentValue.root, runtime, new Set());
      const composition = kanonElement("div", "journey-kanon-composition");
      composition.appendChild(renderKanonNode(documentValue.root, runtime, new Set()));
      canvas.replaceChildren(composition);
      wireMediaFallbacks();
      wireFeaturedRestFrames();
      wireAssetPalette();
      root.setAttribute("data-kanon-composition-id", route.composition_id || "");
      root.setAttribute("data-kanon-composition-revision", String(route.revision || ""));
      return { rendered: true };
    } catch (error) {
      return { rendered: false, reason: String(error.message || "invalid_composition") };
    }
  }

  async function applyKanonDelivery(data) {
    try {
      const response = await fetch("/api/axiom-effective");
      if (!response.ok) throw new Error(`delivery_http_${response.status}`);
      const effective = await response.json();
      const snapshot = effective.design_snapshot;
      const release = snapshot?.release || effective.design_release || {};
      if (release.id) root.setAttribute("data-kanon-release-id", release.id);
      if (effective.design_delivery_status) {
        root.setAttribute("data-kanon-delivery-status", effective.design_delivery_status);
      }
      if (!applyKanonDirection(snapshot)) throw new Error("invalid_design_snapshot");
      const composition = applyKanonComposition(snapshot, data);
      root.setAttribute("data-kanon-render-status", composition.rendered ? "rendered" : "fallback");
      root.setAttribute("data-kanon-fallback-reason", composition.reason || "");
    } catch (error) {
      root.setAttribute("data-kanon-render-status", "fallback");
      root.setAttribute("data-kanon-fallback-reason", String(error.message || "kanon_unavailable"));
    }
  }

  async function activate() {
    const assetId = assetIdFromHash();
    if (!assetId) {
      root.hidden = true;
      legacy.hidden = false;
      return;
    }
    legacy.hidden = true;
    root.hidden = false;
    root.innerHTML = '<div class="journey-loading"><span></span><p>Reading the asset journey…</p></div>';
    try {
      const response = await fetch(`/api/assets/${encodeURIComponent(assetId)}/journey`);
      if (!response.ok) throw new Error(response.status === 404 ? "Asset not found" : `Journey unavailable (${response.status})`);
      const data = await response.json();
      renderJourney(data);
      applyKanonDelivery(data);
    } catch (error) {
      root.innerHTML = `<main class="journey-error"><p>Vellum</p><h1>The journey could not be read.</h1><p>${escapeHtml(error.message || error)}</p><a href="${escapeHtml(workspaceHref("register"))}">Return to Asset Register</a></main>`;
    }
  }

  window.openVellumJourney = function (assetId) {
    window.location.hash = routeFor(assetId);
  };
  window.addEventListener("hashchange", activate);
  activate();
})();
