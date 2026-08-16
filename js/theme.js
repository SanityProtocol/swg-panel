/* theme.js — light/dark resolution and colour maths.
 *
 * LAYER 0 (see docs/APP-JS-SPLIT-PLAN.md). A LEAF: reads localStorage and matchMedia, nothing else.
 * store.js imports it (Store.nodeColor resolves a per-mode colour), which is why only the STORE-FREE
 * half of the theme lives here. The appliers that read Store or paint the document — ifaceColor,
 * themeColor, applyThemeColors, applyThemeMode, applyForkColors, applyFavicon — stay a layer up.
 */

export const IFACE_COLOR_DEFAULTS = { wg: { dark: "#3FD89A", light: "#0E9E63" }, awg: { dark: "#1FC8D6", light: "#0E9BB0" }, wdtt: { dark: "#81B512", light: "#5EAF0E" }, csqtt: { dark: "#F97316", light: "#E5620C" } };
export const NODE_COLOR_DEFAULT = { dark: "#5f7569", light: "#4A5C52" };   // fallback node colour when unset (per mode)
export const NODE_CREATE_DEFAULT = { dark: "#34d399", light: "#12A46B" };  // a fresh node's starting colour
// normalize a possibly-legacy colour ({dark,light} | string | null) into a {dark,light} pair.
export function toThemed(v, def) {
  if (v && typeof v === "object") return { dark: v.dark || def.dark, light: v.light || def.light };
  if (typeof v === "string" && v) return { dark: v, light: v };
  return { ...def };
}
export const THEME_COLOR_DEFAULT = "#1FC8D6";        // brand cyan (--brand) — the dark-mode accent
export const THEME_COLOR_LIGHT_DEFAULT = "#0E9BB0";  // a deeper cyan reads better on light surfaces
// resolve a themed colour: v may be {dark,light}, a legacy single string (used for both), or missing (→ defaults).
export function pickThemed(v, defDark, defLight) {
  const light = resolvedTheme() === "light";
  if (v && typeof v === "object") return (light ? v.light : v.dark) || (light ? defLight : defDark);
  if (typeof v === "string" && v) return v;   // legacy single colour → same in both modes
  return light ? defLight : defDark;
}

export function hexLum(h) {
  h = String(h).replace("#", ""); if (h.length === 3) h = h.split("").map(c => c + c).join("");
  const r = parseInt(h.slice(0, 2), 16) / 255, g = parseInt(h.slice(2, 4), 16) / 255, b = parseInt(h.slice(4, 6), 16) / 255;
  return (isNaN(r) ? 0.5 : 0.299 * r + 0.587 * g + 0.114 * b);
}
export function hexToHsl(hex) {
  let h = String(hex).replace("#", ""); if (h.length === 3) h = h.split("").map(c => c + c).join("");
  const r = parseInt(h.slice(0, 2), 16) / 255, g = parseInt(h.slice(2, 4), 16) / 255, b = parseInt(h.slice(4, 6), 16) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn; let hh = 0;
  if (d) { hh = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; hh /= 6; }
  const l = (mx + mn) / 2, s = d ? d / (1 - Math.abs(2 * l - 1)) : 0;
  return [hh, s, l];
}
export function hslToHex(h, s, l) {
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs((h * 6) % 2 - 1)), m = l - c / 2;
  const seg = Math.floor(h * 6) % 6, r = [c, x, 0, 0, x, c][seg], g = [x, c, c, x, 0, 0][seg], b = [0, 0, x, c, c, x][seg];
  return "#" + [r, g, b].map(v => Math.round((v + m) * 255).toString(16).padStart(2, "0")).join("");
}
// keep the theme accent legible against the active background by clamping LIGHTNESS in HSL (hue + saturation kept,
// so it stays a vivid darker/lighter shade of the SAME colour, not a washed grey). Only genuinely-out-of-band
// picks are moved; the picker snaps to this value too, so what you pick is what you see (WYSIWYG).
export function clampBrand(hex, light) {
  if (!/^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(String(hex))) return hex;
  let [h, s, l] = hexToHsl(hex);
  if (light && l > 0.52) l = 0.44;
  else if (!light && l < 0.44) l = 0.54;
  else return hex;
  s = Math.max(s, 0.4);   // keep it saturated so the darker/lighter shade reads as the colour, not grey
  return hslToHex(h, s, l);
}

export const THEME_MODES = ["auto", "light", "dark"];
export function themeMode() { try { const m = localStorage.getItem("swg-theme"); return THEME_MODES.includes(m) ? m : "auto"; } catch (_) { return "auto"; } }
export function prefersLight() { try { return matchMedia("(prefers-color-scheme: light)").matches; } catch (_) { return false; } }
export function resolvedTheme(mode) { mode = mode || themeMode(); return mode === "auto" ? (prefersLight() ? "light" : "dark") : mode; }
