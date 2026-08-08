const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const localBase = process.env.VELLUM_QA_BASE || "http://127.0.0.1:8877";
const liveBase = process.env.VELLUM_LIVE_BASE || "http://127.0.0.1:8770";
const qaDir = process.env.VELLUM_QA_DIR || path.join(process.cwd(), ".tmp", "vellum-journey-qa");
const assetRoute = "#/assets/fireworks-vol-1-niagara";
let activeBrowser;

async function json(url) {
  const response = await fetch(url);
  assert.equal(response.ok, true, `${url} returned ${response.status}`);
  return response.json();
}

async function main() {
  fs.mkdirSync(qaDir, { recursive: true });
  const journey = await json(`${liveBase}/api/assets/fireworks-vol-1-niagara/journey`);
  const catalog = await json(`${liveBase}/api/game-ready/elements?asset_id=fireworks-vol-1-niagara&limit=1000`);
  const byId = new Map((catalog.elements || []).map((row) => [row.id, row]));
  const enrich = (item) => {
    const row = byId.get(item.id);
    if (!row) return;
    const system = String(row.meta?.system || item.name)
      .replace(/^NS_/, "")
      .replace(/_Single$/, "")
      .replaceAll("_", " ")
      .replace(/(?<=[a-z])(?=[A-Z])/g, " ")
      .replace(/(?<=[A-Za-z])(?=\d)/g, " ");
    item.display_name = system;
    item.technical = { ...(item.technical || {}), variant: row.meta?.variant };
    const validation = row.meta?.validation || {};
    const samples = validation.visual_samples || [];
    const best = [...samples].sort((left, right) =>
      (right.bright_pixels || 0) - (left.bright_pixels || 0)
      || (right.visible_pixels || 0) - (left.visible_pixels || 0)
    )[0];
    const frame = Number(String(best?.frame || "").match(/\.(\d+)\.png$/)?.[1]);
    const count = Number(validation.frame_count || row.meta?.frames);
    const duration = Number(validation.duration_seconds);
    if (Number.isFinite(frame) && count > 1 && duration > 0) {
      item.preview_time_seconds = Math.min(frame / count * duration, duration - duration / count);
    }
  };
  [...journey.featured_outputs, ...journey.outputs].forEach(enrich);
  if (journey.transformation.capture) enrich(journey.transformation.capture);
  const baseEffective = await json(`${liveBase}/api/axiom-effective`);
  const composition = JSON.parse(fs.readFileSync(path.join(process.cwd(), "docs", "kanon-asset-journey.composition.json"), "utf8"));
  let effective = structuredClone(baseEffective);

  const browser = await chromium.launch({ headless: true });
  activeBrowser = browser;
  const context = await browser.newContext({ viewport: { width: 1440, height: 1060 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) consoleErrors.push(`${message.type()}: ${message.text()}`);
  });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));

  await page.route(`${localBase}/api/assets/fireworks-vol-1-niagara/journey`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", headers: { "cache-control": "no-store" }, body: JSON.stringify(journey) })
  );
  await page.route(`${localBase}/api/axiom-effective`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", headers: { "cache-control": "no-store" }, body: JSON.stringify(effective) })
  );
  await page.route(new RegExp(`^${localBase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/api/(lookdev/outputs|game-ready/elements)/.+/file$`), async (route) => {
    const liveUrl = route.request().url().replace(localBase, liveBase);
    const requestRange = route.request().headers().range;
    const response = await fetch(liveUrl, { headers: requestRange ? { range: requestRange } : {} });
    const forwardedHeaders = {};
    for (const name of ["content-type", "accept-ranges", "content-range", "content-length"]) {
      const value = response.headers.get(name);
      if (value) forwardedHeaders[name] = value;
    }
    route.fulfill({
      status: response.status,
      headers: { "content-type": "application/octet-stream", ...forwardedHeaders },
      body: Buffer.from(await response.arrayBuffer()),
    });
  });

  const open = async (hash = assetRoute) => {
    const target = `${localBase}/${hash}`;
    if (page.url() === target) await page.reload({ waitUntil: "domcontentloaded" });
    else await page.goto(target, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".journey-shell");
    await page.waitForFunction(() => document.querySelector(".journey-root")?.hasAttribute("data-kanon-render-status"));
  };

  await open();
  await page.waitForFunction(() => document.querySelectorAll("video[data-preview-time]").length === 9);
  await page.waitForFunction(
    () => [...document.querySelectorAll("video[data-preview-time]")].every((video) => video.readyState >= 2),
    null,
    { timeout: 15000 },
  );
  await page.waitForTimeout(750);
  const localStructure = await page.locator(".journey-canvas").innerHTML();
  const metrics = await page.evaluate(() => ({
    height: document.documentElement.scrollHeight,
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    palette: document.querySelector(".journey-root")?.getAttribute("data-asset-palette"),
    theme: document.querySelector(".journey-root")?.getAttribute("data-ca-theme"),
    themeStatus: document.querySelector(".journey-root")?.getAttribute("data-kanon-theme-status"),
    videos: [...document.querySelectorAll("video[data-preview-time]")].map((video) => ({
      label: video.getAttribute("aria-label"),
      readyState: video.readyState,
      duration: video.duration,
      actual: video.currentTime,
      expected: Number(video.dataset.previewTime),
      wired: video.dataset.restFrameWired,
      cue: video.dataset.restFrameCue,
    })),
    regions: [...document.querySelectorAll(".journey-page-header, .journey-section, .journey-footer")].map((element) => ({
      id: element.id || element.className,
      height: Math.round(element.getBoundingClientRect().height),
    })),
  }));
  await page.screenshot({ path: path.join(qaDir, "expanded.png"), fullPage: true });
  assert.equal(metrics.overflow, 0);
  assert.equal(metrics.palette, "sampled-from-source");
  assert.equal(metrics.theme, "games");
  assert.equal(metrics.themeStatus, "fallback-no-games-variant");
  assert.ok(metrics.height <= 1060, `Journey is ${metrics.height}px tall at 1440×1060: ${JSON.stringify(metrics.regions)}`);
  assert.equal(metrics.videos.length, 9);
  metrics.videos.forEach((video) => {
    assert.ok(video.readyState >= 2);
    if (Number.isFinite(video.expected)) {
      assert.ok(
        Math.abs(video.actual - video.expected) < 0.12,
        `video cue drifted: ${JSON.stringify(video)}`,
      );
    }
  });
  await page.getByRole("button", { name: "Hide navigation" }).click();
  await page.waitForTimeout(220);
  await page.screenshot({ path: path.join(qaDir, "hidden.png"), fullPage: true });

  effective = structuredClone(baseEffective);
  effective.design_snapshot.routes = {
    "#/assets/:asset_id": {
      composition_id: "vellum-asset-journey",
      revision: 1,
      content_hash: "qa",
      document: composition,
    },
  };
  await open();
  const renderedStatus = await page.locator(".journey-root").getAttribute("data-kanon-render-status");
  const renderedReason = await page.locator(".journey-root").getAttribute("data-kanon-fallback-reason");
  assert.equal(renderedStatus, "rendered", `valid composition fell back: ${renderedReason}`);
  assert.equal(await page.locator(".journey-root").getAttribute("data-kanon-composition-id"), "vellum-asset-journey");
  assert.equal(await page.locator("[data-kanon-slot]").count(), 6);

  effective.design_snapshot.routes["#/assets/:asset_id"].document = structuredClone(composition);
  effective.design_snapshot.routes["#/assets/:asset_id"].document.root.children.push({
    id: "unknown_slot",
    type: "slot.custom",
    props: { slot: "vellum.asset.unknown" },
  });
  await open();
  assert.equal(await page.locator(".journey-root").getAttribute("data-kanon-render-status"), "fallback");
  assert.equal(await page.locator(".journey-root").getAttribute("data-kanon-fallback-reason"), "unknown_slot");
  await page.waitForFunction(
    () => [...document.querySelectorAll("video[data-rest-frame]")].every((video) => video.dataset.restFrameCue),
    null,
    { timeout: 15000 },
  );
  assert.equal(await page.locator(".journey-canvas").innerHTML(), localStructure);

  effective = structuredClone(baseEffective);
  effective.design_snapshot.visual_direction.resolved_variants.games = { "--ca-bg": "url(javascript:alert(1))" };
  await open();
  assert.equal(await page.locator(".journey-root").getAttribute("data-kanon-render-status"), "fallback");
  assert.equal(await page.locator(".journey-root").getAttribute("data-kanon-fallback-reason"), "invalid_design_snapshot");
  assert.equal(await page.locator("[data-kanon-slot]").count(), 6);

  effective = structuredClone(baseEffective);
  await page.setViewportSize({ width: 390, height: 844 });
  await open();
  await page.waitForFunction(() => {
    const videos = [...document.querySelectorAll("video[data-preview-time]")];
    const images = [...document.querySelectorAll(".journey-transform-card img")];
    return videos.length === 9
      && videos.every((video) => video.readyState >= 2 && Math.abs(video.currentTime - Number(video.dataset.previewTime)) < 0.12)
      && images.every((image) => image.complete && image.naturalWidth > 0);
  }, null, { timeout: 15000 });
  const mobileShowNavigation = page.locator(".journey-show-navigation");
  await page.getByRole("button", { name: "Show navigation" }).click();
  assert.equal(await mobileShowNavigation.evaluate((element) => getComputedStyle(element).display), "none");
  await page.keyboard.press("Escape");
  assert.equal(await mobileShowNavigation.evaluate((element) => document.activeElement === element), true);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), 0);
  await page.screenshot({ path: path.join(qaDir, "mobile.png"), fullPage: true });

  await page.setViewportSize({ width: 1440, height: 1060 });
  await open(`${assetRoute}?section=outputs`);
  assert.equal(await page.locator('.journey-nav-link[aria-current="page"]').textContent(), " Game-ready");
  assert.deepEqual(consoleErrors, []);
  await browser.close();
  activeBrowser = null;
  process.stdout.write(`${JSON.stringify({ qaDir, metrics }, null, 2)}\n`);
}

main().catch((error) => {
  console.error(error);
  if (activeBrowser) activeBrowser.close().catch(() => {});
  process.exitCode = 1;
});
