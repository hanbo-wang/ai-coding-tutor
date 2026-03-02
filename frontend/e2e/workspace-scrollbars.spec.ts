import { expect, FrameLocator, Page, test } from "playwright/test";

const USER_ID = "11111111-1111-1111-1111-111111111111";
const NOTEBOOK_ID = "22222222-2222-2222-2222-222222222222";
const ZONE_ID = "33333333-3333-3333-3333-333333333333";
const ZONE_NOTEBOOK_ID = "44444444-4444-4444-4444-444444444444";
const NOTEBOOK_IFRAME_SELECTOR = "main iframe";

function createNotebookJson(): Record<string, unknown> {
  const cells = [];
  for (let index = 0; index < 70; index += 1) {
    cells.push({
      cell_type: "markdown",
      metadata: {},
      source: [
        `## Section ${index}\n`,
        "This notebook content is intentionally long to validate vertical scrolling.\n\n",
        "The paragraph stays readable and wraps naturally in wide panes.\n\n",
      ],
    });
  }
  return {
    cells,
    metadata: {
      kernelspec: {
        display_name: "Python 3",
        language: "python",
        name: "python3",
      },
      language_info: {
        name: "python",
      },
    },
    nbformat: 4,
    nbformat_minor: 5,
  };
}

async function installWorkspaceApiMocks(page: Page): Promise<void> {
  const notebookJson = createNotebookJson();
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const method = request.method();
    const resourceType = request.resourceType();
    const url = new URL(request.url());
    const path = url.pathname;

    if ((resourceType !== "fetch" && resourceType !== "xhr") || !path.startsWith("/api/")) {
      await route.fallback();
      return;
    }

    const respondJson = async (payload: unknown, status = 200) => {
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(payload),
      });
    };

    if (path === "/api/auth/refresh" && method === "POST") {
      await respondJson({ access_token: "playwright-access-token", token_type: "bearer" });
      return;
    }
    if (path === "/api/auth/me" && method === "GET") {
      await respondJson({
        id: USER_ID,
        email: "playwright@example.com",
        username: "playwright",
        programming_level: 2,
        maths_level: 2,
        is_admin: false,
        created_at: "2026-01-01T00:00:00Z",
      });
      return;
    }
    if (path === "/api/upload/limits" && method === "GET") {
      await respondJson({
        max_images: 3,
        max_documents: 2,
        max_image_bytes: 10 * 1024 * 1024,
        max_document_bytes: 25 * 1024 * 1024,
        image_extensions: [".png", ".jpg", ".jpeg", ".gif", ".webp"],
        document_extensions: [".pdf", ".txt", ".md", ".py", ".ipynb"],
        accept_extensions: [
          ".png",
          ".jpg",
          ".jpeg",
          ".gif",
          ".webp",
          ".pdf",
          ".txt",
          ".md",
          ".py",
          ".ipynb",
        ],
      });
      return;
    }
    if (path === `/api/notebooks/${NOTEBOOK_ID}` && method === "GET") {
      await respondJson({
        id: NOTEBOOK_ID,
        title: "Playwright notebook",
        original_filename: "playwright.ipynb",
        size_bytes: 1024,
        created_at: "2026-01-01T00:00:00Z",
        notebook_json: notebookJson,
      });
      return;
    }
    if (path === `/api/notebooks/${NOTEBOOK_ID}` && method === "PUT") {
      await respondJson({
        id: NOTEBOOK_ID,
        title: "Playwright notebook",
        original_filename: "playwright.ipynb",
        size_bytes: 1024,
        created_at: "2026-01-01T00:00:00Z",
      });
      return;
    }
    if (path === `/api/zones/${ZONE_ID}/notebooks/${ZONE_NOTEBOOK_ID}` && method === "GET") {
      await respondJson({
        id: ZONE_NOTEBOOK_ID,
        zone_id: ZONE_ID,
        title: "Playwright zone notebook",
        description: null,
        original_filename: "zone-playwright.ipynb",
        size_bytes: 1024,
        order: 1,
        created_at: "2026-01-01T00:00:00Z",
        has_progress: false,
        notebook_json: notebookJson,
      });
      return;
    }
    if (
      path === `/api/zones/${ZONE_ID}/notebooks/${ZONE_NOTEBOOK_ID}/runtime-files` &&
      method === "GET"
    ) {
      await respondJson([]);
      return;
    }
    if (path === `/api/zones/${ZONE_ID}/notebooks/${ZONE_NOTEBOOK_ID}/progress` && method === "PUT") {
      await respondJson({ message: "Progress saved" });
      return;
    }
    if (path === "/api/chat/sessions" && method === "GET") {
      await respondJson([]);
      return;
    }
    if (path.startsWith("/api/chat/sessions/") && method === "GET") {
      await respondJson([]);
      return;
    }
    if (path.startsWith("/api/chat/sessions/") && method === "DELETE") {
      await respondJson({ message: "Deleted" });
      return;
    }

    await respondJson({});
  });
}

async function openWorkspaceRoute(page: Page, pathname: string): Promise<void> {
  let lastError: unknown = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      await page.goto(pathname, { waitUntil: "commit", timeout: 45_000 });
      lastError = null;
      break;
    } catch (error) {
      lastError = error;
      await page.waitForTimeout(1200);
    }
  }
  if (lastError) {
    throw lastError;
  }
}

async function dragSplitTowardsCompactMode(page: Page): Promise<void> {
  const gutter = page.locator(".split-root > .gutter.gutter-horizontal").first();
  await expect(gutter).toBeVisible();
  const box = await gutter.boundingBox();
  if (!box) {
    throw new Error("Split gutter bounds are not available.");
  }
  const targetX = Math.max(80, Math.floor(box.x - 360));
  const targetY = Math.floor(box.y + box.height / 2);
  await page.mouse.move(Math.floor(box.x + box.width / 2), targetY);
  await page.mouse.down();
  await page.mouse.move(targetX, targetY, { steps: 18 });
  await page.mouse.up();
}

async function waitForActiveScrollHost(
  notebookIframe: FrameLocator
): Promise<void> {
  await expect
    .poll(
      async () =>
        notebookIframe.locator("body").evaluate((body) =>
          Boolean(body.querySelector(".gc-workspace-scroll-host"))
        ),
      { timeout: 90_000 }
    )
    .toBe(true);
}

async function ensureNotebookIframeVisible(page: Page): Promise<void> {
  const iframe = page.locator(NOTEBOOK_IFRAME_SELECTOR).first();
  try {
    await expect(iframe).toBeVisible({ timeout: 180_000 });
  } catch (error) {
    const currentUrl = page.url();
    const mainText = await page
      .locator("main")
      .first()
      .innerText()
      .catch(() => "");
    throw new Error(
      `Notebook iframe did not render at ${currentUrl}. ` +
      `Main content: ${mainText.slice(0, 300)}. ` +
      `Original error: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

async function readActiveScrollHostMetrics(
  notebookIframe: FrameLocator
): Promise<{
  hasHost: boolean;
  overflowX: string;
  overflowY: string;
  clientWidth: number;
  scrollWidth: number;
  clientHeight: number;
  scrollHeight: number;
  scrollTop: number;
  scrollLeft: number;
}> {
  return notebookIframe.locator("body").evaluate((body) => {
    const host = body.querySelector(".gc-workspace-scroll-host");
    if (!(host instanceof HTMLElement)) {
      return {
        hasHost: false,
        overflowX: "",
        overflowY: "",
        clientWidth: 0,
        scrollWidth: 0,
        clientHeight: 0,
        scrollHeight: 0,
        scrollTop: 0,
        scrollLeft: 0,
      };
    }
    const style = window.getComputedStyle(host);
    return {
      hasHost: true,
      overflowX: style.overflowX,
      overflowY: style.overflowY,
      clientWidth: host.clientWidth,
      scrollWidth: host.scrollWidth,
      clientHeight: host.clientHeight,
      scrollHeight: host.scrollHeight,
      scrollTop: host.scrollTop,
      scrollLeft: host.scrollLeft,
    };
  });
}

async function assertWorkspaceScrollbars(page: Page): Promise<void> {
  await ensureNotebookIframeVisible(page);

  const notebookIframe = page.frameLocator(NOTEBOOK_IFRAME_SELECTOR).first();
  await waitForActiveScrollHost(notebookIframe);

  await expect
    .poll(
      async () =>
        notebookIframe.locator("body").evaluate((body) =>
          body.classList.contains("gc-workspace-compact")
        ),
      { timeout: 30_000 }
    )
    .toBe(false);

  const host = notebookIframe.locator(".gc-workspace-scroll-host").first();
  await expect(host).toBeVisible({ timeout: 30_000 });

  const verticalCanScroll = await host.evaluate((node) => {
    const element = node as HTMLElement;
    return element.scrollHeight > element.clientHeight + 2;
  });
  expect(verticalCanScroll).toBeTruthy();
  await host.hover();
  const verticalBefore = await host.evaluate((node) => (node as HTMLElement).scrollTop);
  await page.mouse.wheel(0, 1200);
  await expect
    .poll(async () => host.evaluate((node) => (node as HTMLElement).scrollTop), {
      timeout: 10_000,
    })
    .toBeGreaterThan(verticalBefore + 10);

  const wideMetrics = await readActiveScrollHostMetrics(notebookIframe);
  expect(wideMetrics.hasHost).toBeTruthy();
  expect(
    wideMetrics.overflowX === "hidden" || wideMetrics.overflowX === "clip"
  ).toBeTruthy();

  await page.setViewportSize({ width: 1024, height: 900 });
  await expect
    .poll(
      async () =>
        notebookIframe.locator("body").evaluate((body) =>
          body.classList.contains("gc-workspace-compact")
        ),
      { timeout: 30_000 }
    )
    .toBe(true);

  const compactBackground = await notebookIframe.locator("body").evaluate((body) => {
    const panels = [
      body.ownerDocument?.getElementById("jp-main-content-panel"),
      body.ownerDocument?.getElementById("jp-main-vsplit-panel"),
      body.ownerDocument?.getElementById("jp-main-split-panel"),
      body.ownerDocument?.getElementById("jp-main-dock-panel"),
    ];
    return panels.every((panel) => {
      if (!(panel instanceof HTMLElement)) {
        return false;
      }
      return window.getComputedStyle(panel).backgroundColor === "rgb(255, 255, 255)";
    });
  });
  expect(compactBackground).toBeTruthy();

  await waitForActiveScrollHost(notebookIframe);
  const compactMetricsByViewport = await readActiveScrollHostMetrics(notebookIframe);
  expect(compactMetricsByViewport.hasHost).toBeTruthy();
  expect(compactMetricsByViewport.scrollWidth).toBeLessThanOrEqual(
    compactMetricsByViewport.clientWidth + 2
  );


  await page.setViewportSize({ width: 1440, height: 900 });
  await expect
    .poll(
      async () =>
        notebookIframe.locator("body").evaluate((body) =>
          body.classList.contains("gc-workspace-compact")
        ),
      { timeout: 30_000 }
    )
    .toBe(false);

  await expect
    .poll(
      async () => {
        const metrics = await readActiveScrollHostMetrics(notebookIframe);
        return metrics.overflowX === "hidden" || metrics.overflowX === "clip";
      },
      { timeout: 30_000 }
    )
    .toBe(true);

  await dragSplitTowardsCompactMode(page);

  await expect
    .poll(
      async () =>
        notebookIframe.locator("body").evaluate((body) =>
          body.classList.contains("gc-workspace-compact")
        ),
      { timeout: 15_000 }
    )
    .toBe(true);

  const compactMetricsBySplit = await readActiveScrollHostMetrics(notebookIframe);
  expect(compactMetricsBySplit.hasHost).toBeTruthy();
  expect(compactMetricsBySplit.scrollWidth).toBeLessThanOrEqual(
    compactMetricsBySplit.clientWidth + 2
  );

  await page.setViewportSize({ width: 800, height: 900 });
  await expect
    .poll(
      async () =>
        notebookIframe.locator("body").evaluate((body) =>
          body.classList.contains("gc-workspace-compact")
        ),
      { timeout: 30_000 }
    )
    .toBe(true);

  await waitForActiveScrollHost(notebookIframe);
  const tinyMetricsByViewport = await readActiveScrollHostMetrics(notebookIframe);
  expect(tinyMetricsByViewport.hasHost).toBeTruthy();
  expect(tinyMetricsByViewport.scrollWidth).toBeGreaterThan(
    tinyMetricsByViewport.clientWidth + 2
  );
  await host.hover();
  const horizontalBeforeTiny = await host.evaluate(
    (node) => (node as HTMLElement).scrollLeft
  );
  await page.mouse.wheel(380, 0);
  await expect
    .poll(async () => host.evaluate((node) => (node as HTMLElement).scrollLeft), {
      timeout: 10_000,
    })
    .toBeGreaterThan(horizontalBeforeTiny + 10);
}

test.describe("Workspace notebook scrollbars", () => {
  test.describe.configure({ timeout: 360_000 });
  test.beforeEach(async ({ page }) => {
    page.on("pageerror", (error) => {
      // Keep failures diagnosable in CI logs without opening videos first.
      console.error(`[pageerror] ${error.message}`);
    });
    page.on("console", (message) => {
      if (message.type() === "error") {
        console.error(`[console:error] ${message.text()}`);
      }
    });
  });

  test("personal notebook keeps vertical and horizontal scrolling available", async ({ page }) => {
    await installWorkspaceApiMocks(page);
    await openWorkspaceRoute(page, `/notebook/${NOTEBOOK_ID}`);
    await assertWorkspaceScrollbars(page);
  });

  test("zone notebook keeps vertical and horizontal scrolling available", async ({ page }) => {
    await installWorkspaceApiMocks(page);
    await openWorkspaceRoute(page, `/zone-notebook/${ZONE_ID}/${ZONE_NOTEBOOK_ID}`);
    await assertWorkspaceScrollbars(page);
  });
});
