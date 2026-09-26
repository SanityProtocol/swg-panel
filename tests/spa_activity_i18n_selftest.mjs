/* Self-test: activity rows read in Russian — the ones the panel writes now, and the ones already on disk.
 *
 * The log is never rewritten, so rows written before a verb or a prose detail had its key keep their English for
 * good: "Deleted peer · 1 target", "VK pool changed — reassigned 3 user(s)", "Updated user · expiry, note", a
 * Settings save's "Display, Network". Found in the 1.8.8 qualification's Russian pass. The browser recognises
 * those few shapes — each only under the verb that wrote it — and new rows travel as keys (ev_append).
 * "Reset learned IPs" is also a button: its catalog entry is the imperative, so the log reads its own key.
 *
 * The real js/i18n.js with the real Russian catalog (localStorage says "ru" before the module loads).
 *
 * Run: node tests/spa_activity_i18n_selftest.mjs
 *      --perturb   the legacy-detail lookup taken out → RED
 */
import fs from "node:fs";
import path from "node:path";
import { check, done, ROOT } from "./spa_env.mjs";

const PERTURB = process.argv.includes("--perturb");
globalThis.localStorage = { getItem: k => (k === "swg-lang" ? "ru" : null), setItem: () => {}, removeItem: () => {} };
let file = path.join(ROOT, "js", "i18n.js");
if (PERTURB) {
  const src = fs.readFileSync(file, "utf8");
  const a = "  for (const [re, f] of (d && LEGACY_DETAIL[e.verb]) || []) { const m = re.exec(d); if (m) return f(m); }\n";
  if (src.split(a).length !== 2) { console.log("ANCHOR MISSING — would FALSE-PASS"); process.exit(1); }
  file = path.join(ROOT, "js", ".i18n-perturbed.mjs");
  fs.writeFileSync(file, src.replace(a, ""));
  process.on("exit", () => { try { fs.unlinkSync(file); } catch (_) { /* gone */ } });
}
const I = await import(new URL("file://" + file).href);
await I.loadLang();
const { srvVerb, srvDetail, srvName, lang } = I;
check("the Russian catalog is loaded", lang() === "ru" && srvVerb("Deleted peer") !== "Deleted peer", srvVerb("Deleted peer"));

console.log("\n[rows already on disk — English detail, no key]");
const old = [
  [{ verb: "Deleted peer", detail: "1 target" }, "1 назначение"],
  [{ verb: "Deleted peer", detail: "3 targets" }, "3 назначения"],
  [{ verb: "Unassigned peer", detail: "was anna" }, "был у anna"],
  [{ verb: "Assigned peer", detail: "fresh key issued" }, "выдан новый ключ"],
  [{ verb: "Interface came back different from the request", detail: "awg0: listen_port" }, "awg0: порт прослушивания"],
  [{ verb: "Reclaimed a wdtt server", detail: "2 user(s) kept" }, "сохранено: 2 пользователя"],
  [{ verb: "Reclaimed a csqtt server", detail: "no users in its store" }, "в его хранилище нет пользователей"],
  [{ verb: "Updated user", detail: "expiry, note" }, "Срок действия подписки, Заметка"],
  [{ verb: "Updated panel settings", detail: "Display, Network" }, "Отображение, Сеть"],
];
for (const [e, want] of old) check(`${e.verb} · "${e.detail}" → "${want}"`, srvDetail(e) === want, srvDetail(e));

console.log("\n[two rows once carried their prose in the NAME]");
check("Update requested · name \"with the panel\"", srvName({ verb: "Update requested", name: "with the panel" }) === "вместе с панелью",
      srvName({ verb: "Update requested", name: "with the panel" }));
check("Starting interface · name \"wg0 (automatic, attempt 2 of 5)\"",
      srvName({ verb: "Starting interface", name: "wg0 (automatic, attempt 2 of 5)" }) === "wg0 (автоматически, попытка 2 из 5)",
      srvName({ verb: "Starting interface", name: "wg0 (automatic, attempt 2 of 5)" }));
check("any other name renders as it is", srvName({ verb: "Created user", name: "with the panel" }) === "with the panel");

console.log("\n[a value is never mistaken for one of those phrases]");
check("a user named \"1 target\" under another verb stays as it is", srvDetail({ verb: "Created user", detail: "1 target" }) === "1 target");
check("a bare node/iface detail stays as it is", srvDetail({ verb: "Added deployment", detail: "msk-main/wg1" }) === "msk-main/wg1");

console.log("\n[verbs with a value inside them, and the button-shaped one]");
check("VK pool changed — reassigned 3 user(s)", srvVerb("VK pool changed — reassigned 3 user(s)") === "Пул VK изменён — переназначено пользователей: 3", srvVerb("VK pool changed — reassigned 3 user(s)"));
check("VK links per new user: 1 → 2", srvVerb("VK links per new user: 1 → 2") === "VK-ссылок новому пользователю: 1 → 2", srvVerb("VK links per new user: 1 → 2"));
check("Reclaimed a wdtt server", srvVerb("Reclaimed a wdtt server") === "Возвращён сервер WDTT", srvVerb("Reclaimed a wdtt server"));
check("the log's \"Reset learned IPs\" says what happened, not the button's imperative",
      srvVerb("Reset learned IPs") === "Выученные IP сброшены", srvVerb("Reset learned IPs"));

console.log("\n[rows the panel writes now — keys, counted nouns, nested phrases]");
check("Deleted peer → {count} with a counted target", srvDetail({ verb: "Deleted peer", detail: "2 targets", detail_key: "{count}", detail_vars: { count: { n: 2, noun: "target" } } }) === "2 назначения");
check("VK pool changed → reassigned {count}", srvVerb("VK pool changed") === "Пул VK изменён"
      && srvDetail({ verb: "VK pool changed", detail_key: "reassigned {count}", detail_vars: { count: { n: 5, noun: "user" } } }) === "переназначено: 5 пользователей");
check("Starting interface → the iface as the name, the attempt as a keyed detail",
      srvName({ verb: "Starting interface", name: "wg0" }) === "wg0"
      && srvDetail({ verb: "Starting interface", detail_key: "automatic, attempt {v1} of {v2}", detail_vars: { v1: "2", v2: "5" } }) === "автоматически, попытка 2 из 5");
check("a phrase nested with perr() is translated in place",
      srvDetail({ verb: "Interface came back different from the request", detail_key: "{v1}: {v2}",
                  detail_vars: { v1: "wg1", v2: { error: "listen port", error_key: "act|listen port", error_vars: {} } } }) === "wg1: порт прослушивания");

done(PERTURB, "legacy-detail lookup removed");
