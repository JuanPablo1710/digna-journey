// Headless integration probe. Point it at a disposable demo backend.
import { spawn } from "node:child_process";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { createServer, preview } from "vite";
import config from "../vite.config.js";

const backend = process.env.PERF_BACKEND ?? "http://127.0.0.1:8011";
const origin = "http://127.0.0.1:5181";
const debugPort = 9225;
const chrome = process.env.PERF_CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const temporary = await mkdtemp(join(tmpdir(), "salud-digna-perf-"));
let upstream = 0;
let upstreamMax = 0;
const proxy = Object.fromEntries(Object.keys(config.server.proxy).map((path) => [path, {
  target: backend,
  ...(path === "/stream" ? {
    configure(proxyServer) {
      proxyServer.on("proxyRes", (response) => {
        upstream += 1;
        upstreamMax = Math.max(upstreamMax, upstream);
        response.once("close", () => { upstream -= 1; });
      });
    },
  } : {}),
}]));
const localConfig = {
  ...config, configFile: false, root: process.env.PERF_FRONTEND ?? process.cwd(),
  cacheDir: join(temporary, "vite"),
};
const listen = { proxy, host: "127.0.0.1", port: 5181, strictPort: true };
const built = process.env.PERF_PREVIEW === "1";
const vite = built
  ? await preview({ ...localConfig, preview: listen })
  : await createServer({ ...localConfig, server: { ...listen, watch: null } });
if (!built) await vite.listen();
const browser = spawn(chrome, [
  "--headless=new", `--remote-debugging-port=${debugPort}`, `--user-data-dir=${join(temporary, "browser")}`,
  "--no-first-run", "--disable-background-networking", "--disable-sync", "about:blank",
], { stdio: "ignore", windowsHide: true });

async function until(fn, message, timeout = 12000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const result = await fn();
    if (result) return result;
    await delay(25);
  }
  throw new Error(message);
}

async function protocol(url) {
  const socket = new WebSocket(url);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let next = 0;
  const pending = new Map();
  const listeners = new Map();
  socket.addEventListener("message", ({ data }) => {
    const message = JSON.parse(data);
    if (message.id) {
      const handler = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(handler?.timer);
      if (message.error) handler?.reject(new Error(message.error.message));
      else handler?.resolve(message.result);
    } else {
      listeners.get(message.method)?.(message.params);
    }
  });
  return {
    send(method, params = {}) {
      const id = ++next;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pending.delete(id);
          reject(new Error(`No hubo respuesta de Chrome para ${method}`));
        }, 18000);
        pending.set(id, { resolve, reject, timer });
        socket.send(JSON.stringify({ id, method, params }));
      });
    },
    on(method, handler) { listeners.set(method, handler); },
    close() { socket.close(); },
  };
}

async function api(path, body, headers = {}) {
  const result = await fetch(backend + path, body ? {
    method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body),
  } : { headers }).catch((error) => { throw new Error(`No se pudo consultar ${path}`, { cause: error }); });
  if (!result.ok) throw new Error(`${path} devolvió ${result.status}`);
  return result.json();
}

const routes = [
  ["/web", "Cotiza y agenda", null],
  ["/whatsapp", "WhatsApp", null],
  ["/app", "Folio C-1002", "app"],
  ["/callcenter", "Centro de contacto", "advisor"],
  ["/admin", "C-1001", "admin"],
  ["/mailbox?email=marta.demo@example.com", "Código OTP", null],
  ["/login", "Acceso de personal", null],
];
const tracked = /^(\/catalog\/|\/channels\/|\/demo\/|\/admin\/|\/agent\/|\/me\/)/;

let root;
let sessions;
async function tab(path, role, keepVisible = false) {
  const created = await root.send("Target.createBrowserContext");
  const browserContextId = created.browserContextId;
  const { targetId } = await root.send("Target.createTarget", { url: "about:blank", browserContextId });
  const target = await until(async () => {
    const targets = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
    return targets.find((item) => item.id === targetId);
  }, "No se creó la pestaña.");
  const page = await protocol(target.webSocketDebuggerUrl);
  const pending = new Map();
  const calls = new Map();
  const remote = new Set();
  let maxStreams = 0;
  page.on("Network.requestWillBeSent", ({ requestId, request }) => {
    const url = new URL(request.url);
    if (url.protocol.startsWith("http") && url.origin !== origin) remote.add(url.origin);
    if (url.origin !== origin) return;
    const pathname = url.pathname;
    pending.set(requestId, pathname);
    calls.set(pathname, (calls.get(pathname) ?? 0) + 1);
    if (pathname === "/stream") maxStreams = Math.max(maxStreams, streams());
  });
  for (const event of ["Network.loadingFinished", "Network.loadingFailed"]) {
    page.on(event, ({ requestId }) => pending.delete(requestId));
  }
  function streams() { return [...pending.values()].filter((url) => url === "/stream").length; }
  const evaluate = async (expression) => (await page.send("Runtime.evaluate", { expression, returnByValue: true })).result.value;
  await page.send("Network.enable");
  await page.send("Network.setCacheDisabled", { cacheDisabled: true });
  await page.send("Page.enable");
  if (keepVisible) {
    await page.send("Page.addScriptToEvaluateOnNewDocument", {
      source: 'Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });',
    });
  }
  if (role) {
    const slot = role === "app" ? "salud-digna-app-session" : "salud-digna-staff";
    const value = JSON.stringify(sessions[role]);
    await page.send("Page.addScriptToEvaluateOnNewDocument", {
      source: `if(location.origin===${JSON.stringify(origin)}) sessionStorage.setItem(${JSON.stringify(slot)},${JSON.stringify(value)});`,
    });
  }
  await page.send("Page.navigate", { url: origin + path });
  return {
    pending, calls, remote, streams, evaluate, maxStreams: () => maxStreams,
    async close() { page.close(); await root.send("Target.disposeBrowserContext", { browserContextId }); },
  };
}

async function ready(page, marker) {
  return until(async () => {
    if ([...page.pending.values()].some((url) => url !== "/stream")) return null;
    return page.evaluate(`document.body?.innerText.toLowerCase().includes(${JSON.stringify(marker.toLowerCase())}) && Math.round(performance.now())`);
  }, `La página no llegó a: ${marker}`).catch(async (error) => {
    if (process.env.PERF_VERBOSE) console.error([...page.calls.keys()]);
    throw error;
  });
}

async function authorizeCall(page) {
  const input = `(element, value) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(element,value);
    element.dispatchEvent(new Event("input",{bubbles:true}));
    element.dispatchEvent(new Event("change",{bubbles:true}));
  }`;
  await page.evaluate(`{
    const form=document.querySelector('[aria-labelledby="cc-step-2"] form');
    (${input})(form.querySelector('input'),'+522221111111');
  }`);
  await page.evaluate(`document.querySelector('[aria-labelledby="cc-step-2"] form').requestSubmit()`);
  await until(() => page.evaluate(`[...document.querySelectorAll("button")].find(b=>b.textContent==="Seleccionar esta persona")?.click() ?? !!document.querySelector('input[type=date]')`), "No se encontró el solicitante.");
  await page.evaluate(`{
    const field=document.querySelector('input[type=date]');
    (${input})(field,'1985-04-12');
  }`);
  await page.evaluate(`document.querySelector('input[type=date]').form.requestSubmit()`);
  return until(() => page.evaluate(`document.body.innerText.includes("Trámite C-1001") && Math.round(performance.now())`),
    "No se abrió el contexto verificado.");
}

try {
  const info = await until(() => fetch(`http://127.0.0.1:${debugPort}/json/version`).then((result) => result.json()).catch(() => null), "Chrome no inició.");
  root = await protocol(info.webSocketDebuggerUrl);
  const appHeaders = { "X-Channel-Key": "demo-app-key" };
  const email = "marta.demo@example.com";
  const identity = { channel: "app", identifier: email };
  await api("/identity/verify/request", { ...identity, method: "email_otp" }, appHeaders);
  const inbox = await api(`/demo/mailbox?email=${email}`);
  sessions = {
    admin: await api("/auth/login", { username: "admin", password: "Admin#2026" }),
    advisor: await api("/auth/login", { username: "asesor", password: "Asesor#2026" }),
    app: { ...await api("/identity/verify/confirm", { ...identity, code: inbox.messages[0].code }, appHeaders), email },
  };
  const runs = Number(process.env.PERF_RUNS ?? 3);
  const report = Object.fromEntries(routes.map(([path]) => [path, []]));
  for (let trial = 0; trial <= runs; trial += 1) {
    for (const [path, marker, role] of routes) {
      if (process.env.PERF_VERBOSE) console.error(trial, path);
      const page = await tab(path, role);
      try {
        const ms = await ready(page, marker);
        await delay(180);
        const settled = { ms, streams: page.streams(), requests: [...page.calls]
          .filter(([url]) => tracked.test(url)), external: [...page.remote] };
        if (path === "/callcenter") {
          const contextMs = await authorizeCall(page);
          await delay(650);
          settled.verified = { contextMs, streams: page.streams(), maxStreams: page.maxStreams(), contextReads: [...page.calls]
            .filter(([url]) => url.endsWith("/context")).reduce((total, [, count]) => total + count, 0) };
        }
        if (trial) {
          report[path].push(settled);
          if (process.env.PERF_VERBOSE) console.error(JSON.stringify({ path, ...settled }));
        }
      } finally {
        await page.close();
      }
    }
  }
  const first = await tab("/admin", "admin", true);
  const second = await tab("/admin", "admin", true);
  await ready(first, "C-1001");
  await ready(second, "C-1001");
  await delay(400);
  const both = [first.streams(), second.streams()];
  const upstreamWithTabs = upstream;
  await first.evaluate(`
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  `);
  await delay(650);
  const upstreamWithHiddenTab = upstream;
  await first.evaluate(`
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  `);
  await until(() => upstream === 2, "El stream no se reabrió al mostrar la pestaña.");
  await first.evaluate("document.querySelector('header button').click()");
  await until(() => !first.streams() && upstream === 1, "El stream de la ruta anterior no se cerró.");
  await first.close();
  await second.close();
  await until(() => upstream === 0, "El proxy conservó conexiones SSE después del cierre.");
  const summary = Object.fromEntries(Object.entries(report).map(([path, samples]) => [path, {
    loadMs: samples.map((sample) => sample.ms).sort((a, b) => a - b),
    streams: samples.map((sample) => sample.streams),
    requests: samples[0].requests,
    external: [...new Set(samples.flatMap((sample) => sample.external))],
    verified: samples.flatMap((sample) => sample.verified ? [sample.verified] : []),
  }]));
  console.log(JSON.stringify({ summary, both, upstreamWithTabs, upstreamWithHiddenTab, upstreamAfterClose: upstream, upstreamMax }));
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  root?.close();
  browser.kill();
  const close = built ? new Promise((resolve) => vite.httpServer.close(resolve)) : vite.close();
  await Promise.race([close, delay(1500)]);
  vite.httpServer?.closeAllConnections();
}
