/* Self-test: Settings has a name for a certificate by IP (card tls-type-ip).
 *
 * A panel can hold the TLS type `letsencrypt-ip` — every Docker install by IP does, and since this card a bare-metal one
 * too — but the Type list had no such entry, so the field and the subscription card's "Certificate" row showed "—", as
 * if the panel did not know its own certificate.
 *
 * It is listed while it is the panel's SAVED type and only then: the root helper cannot issue a certificate for an
 * address, so it must never be an offered choice.
 *
 * Imports js/screen-settings.js as shipped (spa_env) and reads js/lang/ru.js.
 *
 * Run: node tests/spa_tls_type_ip_selftest.mjs
 *      --perturb   the list without the entry again, and expects red.
 */
import fs from "node:fs";
import path from "node:path";
import { spa, check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
const S = await spa("screen-settings.js");
let { tlsModeOpts, tlsModeLabel } = S;
const { TLS_MODE_OPTS } = S;
if (PERTURB) { tlsModeOpts = () => TLS_MODE_OPTS(); tlsModeLabel = m => ((TLS_MODE_OPTS().find(o => o.value === (m || "")) || {}).label || "—"); }

const EN = "Let's Encrypt for this IP (needs port 80 reachable)";
const vals = l => l.map(o => o.value);

console.log("[a panel whose saved type is a certificate by IP]");
check("the label is its own, not \"—\"", tlsModeLabel("letsencrypt-ip") === EN, tlsModeLabel("letsencrypt-ip"));
const mine = tlsModeOpts("letsencrypt-ip");
check("the Type list shows it, beside the other Let's Encrypt entry",
      vals(mine).indexOf("letsencrypt-ip") === 1 && vals(mine).indexOf("letsencrypt") === 2 && mine[1].label === EN, vals(mine));
check("…and every type that was offered is still offered, in its order",
      JSON.stringify(vals(mine).filter(v => v !== "letsencrypt-ip")) === JSON.stringify(vals(TLS_MODE_OPTS())), vals(mine));

console.log("\n[every other panel]");
const others = ["", "letsencrypt", "cloudflare", "cf15", "selfsigned", "skip", undefined];
check("it is never offered: the root helper cannot issue one",
      others.every(m => !vals(tlsModeOpts(m)).includes("letsencrypt-ip")) && !vals(TLS_MODE_OPTS()).includes("letsencrypt-ip"),
      others.map(m => vals(tlsModeOpts(m)).length));
check("the other labels are what they were", tlsModeLabel("letsencrypt") === "Let's Encrypt (HTTP-01 — needs port 80 reachable)"
      && tlsModeLabel("selfsigned") === "Self-signed" && tlsModeLabel("bogus") === "—", [tlsModeLabel("letsencrypt"), tlsModeLabel("bogus")]);

console.log("\n[where it is used, and its Russian]");
const src = fs.readFileSync(path.join(ROOT, "js", "screen-settings.js"), "utf8");
check("the Access card's Type list is built from the saved type", src.includes("options=${tlsModeOpts(orig.mode)}")
      && !src.includes("onChange=${setModeLinked} options=${TLS_MODE_OPTS()}"));
const ru = fs.readFileSync(path.join(ROOT, "js", "lang", "ru.js"), "utf8");
const m = ru.match(new RegExp('^\\s*"' + EN.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + '":\\s*"([^"]+)",?\\s*$', "m"));
check("js/lang/ru.js has it, with the IP and the port named", !!m && /IP/.test(m[1]) && /80/.test(m[1]) && /[а-я]/.test(m[1]), m && m[1]);

done(PERTURB);
