// Module-resolution hooks for the SPA under node. The browser resolves "preact" / "preact/hooks" / "htm"
// through the importmap in index.html; node has no importmap, so the same three specifiers are mapped to the
// same vendored files here. Nothing else is redirected — a test imports the REAL module the browser loads.
import { pathToFileURL } from "node:url";

const VENDOR = { preact: "vendor/preact.module.js", "preact/hooks": "vendor/hooks.module.js", htm: "vendor/htm.module.js" };

export async function resolve(spec, ctx, next) {
  const f = VENDOR[spec];
  return f ? { url: pathToFileURL(process.env.SPA_ROOT + "/" + f).href, shortCircuit: true } : next(spec, ctx);
}
