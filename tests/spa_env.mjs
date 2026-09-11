/* The SPA, running under node — so its LOGIC can be gated the way the panel's and the node's already are.
 *
 * Everything in js/ has been verified by driving a browser and reading pixels, which proves a behaviour
 * once and prevents nothing afterwards. This makes the modules importable in a plain `node` process, with
 * no dependency added: the three bare specifiers come from the same vendored files the importmap serves,
 * and the browser globals the modules touch at import time are stubbed to the smallest thing that satisfies
 * them.
 *
 * ⚠️ WHAT THIS IS NOT. It is not a DOM. `preact.h()` builds vnodes without one, so anything that returns
 * DATA — option lists, labels, health verdicts, the rule model — is testable here, and that is where the
 * bugs this session found actually lived. Rendering, layout and event wiring still need a real browser;
 * a test that needs those belongs in a browser pass, not in a fake DOM that agrees with whatever it is told.
 */
import { register } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";

export const ROOT = path.resolve(new URL(".", import.meta.url).pathname, "..");
process.env.SPA_ROOT = ROOT;

// The browser surface the modules touch while being imported — no more than that, so a module that starts
// depending on something real fails loudly here instead of silently getting a stub that lies.
const noop = () => {};
globalThis.location = { href: "http://panel.test/", hash: "", search: "", pathname: "/", reload: noop };
globalThis.localStorage = { getItem: () => null, setItem: noop, removeItem: noop };
globalThis.sessionStorage = globalThis.localStorage;
globalThis.matchMedia = () => ({ matches: false, addEventListener: noop, removeEventListener: noop });
globalThis.addEventListener = noop;
globalThis.removeEventListener = noop;
const el = () => ({ style: {}, setAttribute: noop, appendChild: noop, remove: noop,
                    classList: { add: noop, remove: noop, toggle: noop, contains: () => false } });
globalThis.document = { documentElement: { ...el(), getAttribute: () => null },
                        createElement: el, createTextNode: el, querySelector: () => null,
                        querySelectorAll: () => [], addEventListener: noop, removeEventListener: noop,
                        head: el(), body: el() };
globalThis.window = globalThis;

register("./spa_hooks.mjs", import.meta.url);

/** Import one SPA module by filename, e.g. `spa("routing.js")`. */
export const spa = m => import(pathToFileURL(path.join(ROOT, "js", m)).href);

// ── the same reporting shape the Python selftests use, so a run reads identically whichever it is ────
export const FAILS = [];
export function check(name, cond, detail = "") {
  console.log((cond ? "  PASS " : "  FAIL ") + name + ((detail && !cond) ? "  — " + detail : ""));
  if (!cond) FAILS.push(name);
}
export function done(perturbed, what = "") {
  console.log("");
  if (perturbed) {
    const ok = FAILS.length > 0;
    console.log(ok ? `PERTURB OK (${what}) — ${FAILS.length} checks went red`
                   : "PERTURB FAILED — the fix was removed and every check still passed");
    process.exit(ok ? 0 : 1);
  }
  console.log(FAILS.length ? "FAIL: " + FAILS.join(", ") : "ALL PASS");
  process.exit(FAILS.length ? 1 : 0);
}
