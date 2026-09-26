/* Self-test: the Docker address change's Confirm waits as long as the panel does.
 *
 * /api/access/docker-confirm waits up to 220 s for its dry-run (on Cloudflare it issues a real DNS-01 certificate in a
 * throwaway container), while every SPA request gave up at REQ_TIMEOUT, 90 s: the operator read "Couldn't run the
 * dry-run" while it carried on, and a second click ran a second one (pre-release loose ends D2, 1.8.8 qualification).
 * The fetch wrapper takes a per-call timeout and this one call asks for more than the server's wait.
 *
 * Reads js/store.js, js/screen-settings.js and swg-panel-server as shipped.
 * Run: node tests/spa_docker_confirm_timeout_selftest.mjs
 *      --perturb   the call back on the default timeout and expects red.
 */
import fs from "node:fs";
import path from "node:path";
import { check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const store = fs.readFileSync(path.join(ROOT, "js", "store.js"), "utf8");
let sett = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
const srv = fs.readFileSync(path.join(ROOT, "swg-panel-server"), "utf8");
if (PERTURB) sett = sett.replace('{ nonce: dockerRestart.nonce }, 240000)', "{ nonce: dockerRestart.nonce })");
const wait = +((/_netctl_wait\(deps, rid, timeout=(\d+)\)/.exec(srv.slice(srv.indexOf('path == "/api/access/docker-confirm"'))) || [])[1] || 0);
const ask = +((/api\.post\("\/api\/access\/docker-confirm", \{ nonce: dockerRestart\.nonce \}, (\d+)\)/.exec(sett) || [])[1] || 0);
const dflt = +((/export const REQ_TIMEOUT = (\d+);/.exec(store) || [])[1] || 0);
console.log("[the wait each side keeps]");
check("the server's dry-run wait is read (seconds)", wait > 0, wait);
check("the default request timeout is shorter than it (the case this exists for)", dflt > 0 && dflt < wait * 1000, { dflt, wait });
check("the Confirm call asks for longer than the server waits", ask > wait * 1000, { ask, wait });
check("the fetch wrapper honours a per-call timeout", /async function _fetch\(u, opts, ms\)/.test(store) && /setTimeout\(\(\) => ac\.abort\(\), ms \|\| REQ_TIMEOUT\)/.test(store));
check("…and api.post passes it through", /async post\(p, b, ms\) \{ const r = await _fetch\(url\(p\), \{[^}]*\}, ms\)/.test(store) || /async post\(p, b, ms\)[\s\S]{0,200}\}, ms\);/.test(store));
done(PERTURB);
