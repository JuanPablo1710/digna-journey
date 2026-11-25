import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { createContext, SourceTextModule } from "node:vm";

async function loadApi(globals) {
  const source = await readFile(new URL("../src/api.js", import.meta.url), "utf8");
  const sandbox = createContext({
    AbortController, TextDecoder, URLSearchParams, queueMicrotask,
    sessionStorage: { getItem: () => JSON.stringify({ access_token: "token-de-prueba" }) },
    ...globals,
  });
  const module = new SourceTextModule(source, {
    context: sandbox,
    initializeImportMeta(meta) { meta.env = {}; },
  });
  await module.link(() => {});
  await module.evaluate();
  return module.namespace;
}

test("SSE sends the token in a header, resumes at the cursor and aborts on exit", async () => {
  const requests = [];
  const received = [];
  const statuses = [];
  const encoder = new TextEncoder();
  const token = "token-de-prueba";
  let stop;
  let finish;
  const finished = new Promise((resolve) => { finish = resolve; });

  const api = await loadApi({
    window: { setTimeout, clearTimeout },
    fetch(url, options) {
      requests.push({ url, ...options });
      const second = requests.length === 2;
      const body = new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode(second
            ? 'id: 11\ndata: {"type":"old"}\n\nid: 12\ndata: {"type":"new"}\n\n'
            : 'id: 10\n: conectado\n\nid: 11\ndata: {"type":"old"}\n\n'));
          if (!second) controller.close();
        },
      });
      return Promise.resolve(new Response(body, { headers: { "Content-Type": "text/event-stream" } }));
    },
  });
  const exitTimer = setTimeout(finish, 3000);
  try {
    stop = api.openStaffStream({
      caseId: "C-1001",
      onStatus: (status) => statuses.push(status),
      onEvent(event, cursor) {
        received.push([event.type, cursor]);
        if (cursor === 12) finish();
      },
      onError: finish,
    });
    await finished;
  } finally {
    clearTimeout(exitTimer);
    stop?.();
  }

  assert.deepEqual(received, [["old", 11], ["new", 12]]);
  assert.deepEqual(statuses, ["reconnecting", "connected", "reconnecting", "connected"]);
  assert.equal(requests.length, 2);
  assert.equal(requests[1].headers["Last-Event-ID"], "11");
  for (const request of requests) {
    assert.equal(request.url, "/stream?case_id=C-1001");
    assert.equal(request.headers.Authorization, `Bearer ${token}`);
    assert.ok(!request.url.includes(token));
    assert.ok(request.signal.aborted);
  }
});

test("SSE backs off, pauses while hidden and does not restart after cleanup", async () => {
  const page = Object.assign(new EventTarget(), { visibilityState: "visible" });
  const window = new EventTarget();
  const timers = new Map();
  let id = 0;
  let calls = 0;
  window.setTimeout = (run, ms) => { timers.set(++id, { run, ms }); return id; };
  window.clearTimeout = (timer) => timers.delete(timer);
  const flush = () => new Promise((resolve) => setImmediate(resolve));
  const api = await loadApi({
    document: page, window,
    fetch() { calls += 1; return Promise.reject(new Error("Sin conexión")); },
  });
  const stop = api.openStaffStream({ onStatus() {} });
  await flush();
  assert.equal(calls, 1);

  for (const expected of [500, 1000, 2000, 4000, 8000, 15000, 15000]) {
    assert.equal(timers.size, 1);
    const [[timer, { run, ms }]] = timers;
    assert.equal(ms, expected);
    timers.delete(timer);
    run();
    await flush();
  }
  assert.equal(calls, 8);

  page.visibilityState = "hidden";
  page.dispatchEvent(new Event("visibilitychange"));
  assert.equal(timers.size, 0);
  page.visibilityState = "visible";
  page.dispatchEvent(new Event("visibilitychange"));
  window.dispatchEvent(new Event("pageshow"));
  assert.equal(timers.size, 1);
  assert.equal(calls, 8);
  stop();
  assert.equal(timers.size, 0);
  page.dispatchEvent(new Event("visibilitychange"));
  assert.equal(timers.size, 0);
});
