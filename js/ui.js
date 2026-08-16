/* ui.js — the shared presentation layer: primitives, the modal/sheet stack, toasts and mutations.
 *
 * LAYER 2 (see docs/APP-JS-SPLIT-PLAN.md). Imports util + store; every screen imports THIS.
 *
 * The modal stack is the one piece with real state. openModal REPLACES the current top (so every
 * single-modal flow behaves as it always did — the stack is just length 1), pushModal stacks a CHILD over
 * its parent, closeModal pops back. `_stack` is a synchronous mirror of the rendered state so an opener
 * can ask "is a modal already up?" without waiting for a render. App owns the actual rendering, and
 * registers its setter through setModalRenderer — an imported binding is read-only, so the previous
 * direct assignment to _setStack cannot cross a module boundary.
 *
 * _sheetStack is separate and deliberately so: it tracks MOUNTED Sheet tokens, and only the topmost one
 * handles Esc/Enter/Tab. Without it a child sheet's Escape would close its parent too.
 */

import { $, esc, tkey, ipOf, isPrivIp, fmtBytes, rate, seen } from "./util.js";
import { Store, api, bus, useStore } from "./store.js";
import { go } from "./router.js";
import { lang, setLang, LANGS, nextLang, T, Tsplit, srvText } from "./i18n.js";
import { IFACE_COLOR_DEFAULTS, THEME_COLOR_DEFAULT, THEME_COLOR_LIGHT_DEFAULT, THEME_MODES,
         clampBrand, hexLum, pickThemed, resolvedTheme, themeMode } from "./theme.js";
import { targetType } from "./model.js";
import { turnColor, turnLabel, turnForkList } from "./turn-catalog.js";
import { h, render, Fragment } from "preact";
import { useState, useEffect, useRef } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// ───────────────────────── icons + panels ─────────────────────────
export const ICON = {
  arrow: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>',
  dots: '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2.1"/><circle cx="12" cy="12" r="2.1"/><circle cx="19" cy="12" r="2.1"/></svg>',
  waves: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M3 8q3.5-4 7 0t7 0"/><path d="M3 13q3.5-4 7 0t7 0"/><path d="M3 18q3.5-4 7 0t7 0"/></svg>',
  off: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/></svg>',
  back: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 18l-6-6 6-6"/></svg>',
  search: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>',
  copy: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
  pencil: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
  check: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M20 6 9 17l-5-5"/></svg>',
  warn: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
  info: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
  x: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  refresh: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6M3 12a9 9 0 0 1 15-6.7L21 8M3 22v-6h6M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>',
  err: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/></svg>',
  download: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14"/></svg>',
  play: '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M7 4l13 8-13 8z"/></svg>',
  stop: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>',
  plus: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
  server: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="3" y="4" width="18" height="7" rx="1.6"/><rect x="3" y="13" width="18" height="7" rx="1.6"/><path d="M7 7.5h.01M7 16.5h.01"/></svg>',
  network: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="5" r="2.2"/><circle cx="5" cy="19" r="2.2"/><circle cx="19" cy="19" r="2.2"/><path d="M12 7.2v3.3M12 10.5 6.2 17M12 10.5 17.8 17"/></svg>',
  key: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="8" cy="15" r="4"/><path d="M10.9 12.1 21 2m-4 1 2.4 2.4M14 5l2.4 2.4"/></svg>',
  shield: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M12 3l7.5 3.2v5C19.5 16 16.4 19 12 21 7.6 19 4.5 16 4.5 11.2v-5z"/></svg>',
  compass: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M15.8 8.2l-2 5.6-5.6 2 2-5.6z"/></svg>',
  eye: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>',
  activity: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"><path d="M3 12h4l3 8 4-16 3 8h4"/></svg>',
  users: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1"/><circle cx="9" cy="7" r="3.4"/><path d="M22 19v-1a4 4 0 0 0-3-3.85M16 3.2a4 4 0 0 1 0 7.6"/></svg>',
  user: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M19 20v-1a5 5 0 0 0-5-5h-4a5 5 0 0 0-5 5v1"/><circle cx="12" cy="7" r="4"/></svg>',
  device: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="7" y="3" width="10" height="18" rx="2.4"/><path d="M11 18h2"/></svg>',
  android: '<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M7.2 9.3h9.6v7.2a1 1 0 0 1-1 1H15v2.1a1.1 1.1 0 0 1-2.2 0V17.5h-1.6v2.1a1.1 1.1 0 0 1-2.2 0V17.5h-.8a1 1 0 0 1-1-1zM5 9.6a1.1 1.1 0 0 1 1.1 1.1v4.4a1.1 1.1 0 0 1-2.2 0v-4.4A1.1 1.1 0 0 1 5 9.6zm14 0a1.1 1.1 0 0 1 1.1 1.1v4.4a1.1 1.1 0 0 1-2.2 0v-4.4A1.1 1.1 0 0 1 19 9.6zM8.3 8.4a3.9 3.9 0 0 1 1.7-2.7l-.82-1.35a.28.28 0 0 1 .48-.28l.83 1.4a4.6 4.6 0 0 1 3 0l.83-1.4a.28.28 0 0 1 .48.28L14.0 5.7a3.9 3.9 0 0 1 1.7 2.7zm1.8-1.6a.62.62 0 1 0 0-1.24.62.62 0 0 0 0 1.24zm3.8 0a.62.62 0 1 0 0-1.24.62.62 0 0 0 0 1.24z"/></svg>',
  apple: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M15.8 12.7c-.02-2.2 1.8-3.26 1.88-3.32-1.02-1.5-2.62-1.7-3.19-1.72-1.36-.14-2.65.8-3.34.8-.68 0-1.75-.78-2.88-.76-1.5.02-2.85.86-3.61 2.19-1.54 2.68-.4 6.65 1.1 8.83.73 1.07 1.6 2.27 2.74 2.23 1.1-.045 1.52-.71 2.85-.71 1.33 0 1.7.71 2.87.69 1.18-.02 1.93-1.09 2.65-2.16.83-1.24 1.18-2.44 1.2-2.5-.026-.01-2.3-.885-2.32-3.51zM13.6 6.35c.6-.73.995-1.74.888-2.75-.86.035-1.9.57-2.52 1.3-.55.64-1.03 1.68-.9 2.66.955.075 1.93-.49 2.53-1.21z"/></svg>',
  windows: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M3 5.6l7.4-1.02v7.06H3zm8.3-1.14L21 3.1v8.54h-9.7zM3 12.44h7.4v7.06L3 18.44zm8.3 0H21v8.5l-9.7-1.36z"/></svg>',
  finder: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="M11.8 3.8c-1.1 2.1-.9 3.4.8 4.9-1.9 1.2-2 2.7-.3 4.3-1.7 1.1-1.9 3.3.2 6.2"/><path d="M8.3 9v1.7M15.6 9v1.7"/><path d="M7.7 14.4c2.6 2.1 6.3 2.1 8.9 0"/></svg>',
  cpu: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="7" y="7" width="10" height="10" rx="1.6"/><path d="M9 1.5v3M15 1.5v3M9 19.5v3M15 19.5v3M1.5 9h3M1.5 15h3M19.5 9h3M19.5 15h3"/></svg>',
  disk: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5.2 13 7.5 5h9l2.3 8M7 16.5h.01"/></svg>',
  database: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>',
  clock: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5l3.2 2"/></svg>',
  "cal-day": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/><rect x="10.2" y="12.4" width="3.6" height="3.6" rx="0.7" fill="currentColor" stroke="none"/></svg>',
  "cal-week": '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/><path d="M6.3 14h11.4" stroke-width="2.7"/></svg>',
  cal: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/><path d="M7.5 13h.01M12 13h.01M16.5 13h.01M7.5 16.6h.01M12 16.6h.01M16.5 16.6h.01" stroke-width="2.3"/></svg>',
  donut: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3.4"/></svg>',
  flow: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="6" cy="12" r="2.6"/><circle cx="18" cy="6" r="2.6"/><circle cx="18" cy="18" r="2.6"/><path d="M8.3 10.9 15.7 7.1M8.3 13.1 15.7 16.9"/></svg>',
  bars: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 20V12M12 20V4M19 20V15"/></svg>',
  exclaim: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7.3v5.4"/><path d="M12 16.3v.01" stroke-width="2.4"/></svg>',
  excl: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M12 3.5v11"/><path d="M12 20v.01" stroke-width="3.4"/></svg>',
  hour2: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 12 9.7 8.1"/><path d="M12 12 17 12"/></svg>',
  sun: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.3M12 19.2v2.3M2.5 12h2.3M19.2 12h2.3M5.1 5.1l1.7 1.7M17.2 17.2l1.7 1.7M18.9 5.1l-1.7 1.7M6.8 17.2l-1.7 1.7"/></svg>',
  weekcal: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="5" width="18" height="15" rx="2"/><path d="M3 9.5h18M8 3v3.4M16 3v3.4"/><rect x="6.2" y="12.4" width="3.2" height="3.2" rx="0.6" fill="currentColor" stroke="none"/><rect x="10.4" y="12.4" width="3.2" height="3.2" rx="0.6" fill="currentColor" stroke="none"/><rect x="14.6" y="12.4" width="3.2" height="3.2" rx="0.6" fill="currentColor" stroke="none"/></svg>',
  monthcal: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="5" width="18" height="15" rx="2"/><path d="M3 9.5h18M8 3v3.4M16 3v3.4"/><g fill="currentColor" stroke="none"><rect x="6.3" y="11.6" width="2.7" height="2.7" rx="0.5"/><rect x="10.65" y="11.6" width="2.7" height="2.7" rx="0.5"/><rect x="15" y="11.6" width="2.7" height="2.7" rx="0.5"/><rect x="6.3" y="15.4" width="2.7" height="2.7" rx="0.5"/><rect x="10.65" y="15.4" width="2.7" height="2.7" rx="0.5"/><rect x="15" y="15.4" width="2.7" height="2.7" rx="0.5"/></g></svg>',
  daycal: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="5" width="18" height="15" rx="2"/><path d="M3 9.5h18M8 3v3.4M16 3v3.4"/><rect x="9.9" y="12.2" width="4.2" height="4.2" rx="0.8" fill="currentColor" stroke="none"/></svg>',
  relay: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="2"/><path d="M8.2 8.2a5.4 5.4 0 0 0 0 7.6M15.8 15.8a5.4 5.4 0 0 0 0-7.6M5.4 5.4a9.4 9.4 0 0 0 0 13.2M18.6 18.6a9.4 9.4 0 0 0 0-13.2"/></svg>',
  cascade: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4v4h5v4h5v4h6"/></svg>',
  smart: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M11 3l1.8 5.2L18 10l-5.2 1.8L11 17l-1.8-5.2L4 10l5.2-1.8z"/><path d="M18.5 14l.8 2.4 2.4.8-2.4.8-.8 2.4-.8-2.4-2.4-.8 2.4-.8z"/></svg>',
  globe: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18z"/></svg>',
  bolt: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
  gauge: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M12 13.5 16 9"/><path d="M4 18a9 9 0 1 1 16 0"/></svg>',
  gear: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3.2"/><path d="M19.4 13a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V20a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-2.7-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 4.6 13H4.5a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.1-2.7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 2.7-1.1V2a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-1.1 2.7v.1a2 2 0 1 1 0 4z"/></svg>',
  trash: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13"/></svg>',
  link: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><path d="M10 13a4 4 0 0 0 6 .5l2-2a4 4 0 0 0-5.7-5.7l-1.2 1.1M14 11a4 4 0 0 0-6-.5l-2 2A4 4 0 0 0 11.7 18l1.2-1.1"/></svg>',
  qr: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="1.2"/><rect x="14" y="3" width="7" height="7" rx="1.2"/><rect x="3" y="14" width="7" height="7" rx="1.2"/><path d="M14 14h3v3M21 14v3M17 21h4M14 21h.01M21 21v.01M17 17h.01"/></svg>',
  doc: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/></svg>',
  // OS/platform brand glyphs (Android/iOS/Windows/macOS from the sub-page picker; Linux = Simple Icons Tux) — viewBox-only, CSS-sized
  os_android: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7.2 9.3h9.6v7.2a1 1 0 0 1-1 1H15v2.1a1.1 1.1 0 0 1-2.2 0V17.5h-1.6v2.1a1.1 1.1 0 0 1-2.2 0V17.5h-.8a1 1 0 0 1-1-1zM5 9.6a1.1 1.1 0 0 1 1.1 1.1v4.4a1.1 1.1 0 0 1-2.2 0v-4.4A1.1 1.1 0 0 1 5 9.6zm14 0a1.1 1.1 0 0 1 1.1 1.1v4.4a1.1 1.1 0 0 1-2.2 0v-4.4A1.1 1.1 0 0 1 19 9.6zM8.3 8.4a3.9 3.9 0 0 1 1.7-2.7l-.82-1.35a.28.28 0 0 1 .48-.28l.83 1.4a4.6 4.6 0 0 1 3 0l.83-1.4a.28.28 0 0 1 .48.28L14 5.7a3.9 3.9 0 0 1 1.7 2.7zm1.8-1.6a.62.62 0 1 0 0-1.24.62.62 0 0 0 0 1.24zm3.8 0a.62.62 0 1 0 0-1.24.62.62 0 0 0 0 1.24z"/></svg>',
  os_ios: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.8 12.7c-.02-2.2 1.8-3.26 1.88-3.32-1.02-1.5-2.62-1.7-3.19-1.72-1.36-.14-2.65.8-3.34.8-.68 0-1.75-.78-2.88-.76-1.5.02-2.85.86-3.61 2.19-1.54 2.68-.4 6.65 1.1 8.83.73 1.07 1.6 2.27 2.74 2.23 1.1-.045 1.52-.71 2.85-.71 1.33 0 1.7.71 2.87.69 1.18-.02 1.93-1.09 2.65-2.16.83-1.24 1.18-2.44 1.2-2.5-.026-.01-2.3-.885-2.32-3.51zM13.6 6.35c.6-.73.995-1.74.888-2.75-.86.035-1.9.57-2.52 1.3-.55.64-1.03 1.68-.9 2.66.955.075 1.93-.49 2.53-1.21z"/></svg>',
  os_windows: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 5.6l7.4-1.02v7.06H3zm8.3-1.14L21 3.1v8.54h-9.7zM3 12.44h7.4v7.06L3 18.44zm8.3 0H21v8.5l-9.7-1.36z"/></svg>',
  os_macos: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="M11.8 3.8c-1.1 2.1-.9 3.4.8 4.9-1.9 1.2-2 2.7-.3 4.3-1.7 1.1-1.9 3.3.2 6.2"/><path d="M8.3 9v1.7M15.6 9v1.7"/><path d="M7.7 14.4c2.6 2.1 6.3 2.1 8.9 0"/></svg>',
  os_linux: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12.504 0c-.155 0-.315.008-.48.021-4.226.333-3.105 4.807-3.17 6.298-.076 1.092-.3 1.953-1.05 3.02-.885 1.051-2.127 2.75-2.716 4.521-.278.832-.41 1.684-.287 2.489a.424.424 0 00-.11.135c-.26.268-.45.6-.663.839-.199.199-.485.267-.797.4-.313.136-.658.269-.864.68-.09.189-.136.394-.132.602 0 .199.027.4.055.536.058.399.116.728.04.97-.249.68-.28 1.145-.106 1.484.174.334.535.47.94.601.81.2 1.91.135 2.774.6.926.466 1.866.67 2.616.47.526-.116.97-.464 1.208-.946.587-.003 1.23-.269 2.26-.334.699-.058 1.574.267 2.577.2.025.134.063.198.114.333l.003.003c.391.778 1.113 1.132 1.884 1.071.771-.06 1.592-.536 2.257-1.306.631-.765 1.683-1.084 2.378-1.503.348-.199.629-.469.649-.853.023-.4-.2-.811-.714-1.376v-.097l-.003-.003c-.17-.2-.25-.535-.338-.926-.085-.401-.182-.786-.492-1.046h-.003c-.059-.054-.123-.067-.188-.135a.357.357 0 00-.19-.064c.431-1.278.264-2.55-.173-3.694-.533-1.41-1.465-2.638-2.175-3.483-.796-1.005-1.576-1.957-1.56-3.368.026-2.152.236-6.133-3.544-6.139zm.529 3.405h.013c.213 0 .396.062.584.198.19.135.33.332.438.533.105.259.158.459.166.724 0-.02.006-.04.006-.06v.105a.086.086 0 01-.004-.021l-.004-.024a1.807 1.807 0 01-.15.706.953.953 0 01-.213.335.71.71 0 00-.088-.042c-.104-.045-.198-.064-.284-.133a1.312 1.312 0 00-.22-.066c.05-.06.146-.133.183-.198.053-.128.082-.264.088-.402v-.02a1.21 1.21 0 00-.061-.4c-.045-.134-.101-.2-.183-.333-.084-.066-.167-.132-.267-.132h-.016c-.093 0-.176.03-.262.132a.8.8 0 00-.205.334 1.18 1.18 0 00-.09.4v.019c.002.089.008.179.02.267-.193-.067-.438-.135-.607-.202a1.635 1.635 0 01-.018-.2v-.02a1.772 1.772 0 01.15-.768c.082-.22.232-.406.43-.533a.985.985 0 01.594-.2zm-2.962.059h.036c.142 0 .27.048.399.135.146.129.264.288.344.465.09.199.14.4.153.667v.004c.007.134.006.2-.002.266v.08c-.03.007-.056.018-.083.024-.152.055-.274.135-.393.2.012-.09.013-.18.003-.267v-.015c-.012-.133-.04-.2-.082-.333a.613.613 0 00-.166-.267.248.248 0 00-.183-.064h-.021c-.071.006-.13.04-.186.132a.552.552 0 00-.12.27.944.944 0 00-.023.33v.015c.012.135.037.2.08.334.046.134.098.2.166.268.01.009.02.018.034.024-.07.057-.117.07-.176.136a.304.304 0 01-.131.068 2.62 2.62 0 01-.275-.402 1.772 1.772 0 01-.155-.667 1.759 1.759 0 01.08-.668 1.43 1.43 0 01.283-.535c.128-.133.26-.2.418-.2zm1.37 1.706c.332 0 .733.065 1.216.399.293.2.523.269 1.052.468h.003c.255.136.405.266.478.399v-.131a.571.571 0 01.016.47c-.123.31-.516.643-1.063.842v.002c-.268.135-.501.333-.775.465-.276.135-.588.292-1.012.267a1.139 1.139 0 01-.448-.067 3.566 3.566 0 01-.322-.198c-.195-.135-.363-.332-.612-.465v-.005h-.005c-.4-.246-.616-.512-.686-.71-.07-.268-.005-.47.193-.6.224-.135.38-.271.483-.336.104-.074.143-.102.176-.131h.002v-.003c.169-.202.436-.47.839-.601.139-.036.294-.065.466-.065zm2.8 2.142c.358 1.417 1.196 3.475 1.735 4.473.286.534.855 1.659 1.102 3.024.156-.005.33.018.513.064.646-1.671-.546-3.467-1.089-3.966-.22-.2-.232-.335-.123-.335.59.534 1.365 1.572 1.646 2.757.13.535.16 1.104.021 1.67.067.028.135.06.205.067 1.032.534 1.413.938 1.23 1.537v-.043c-.06-.003-.12 0-.18 0h-.016c.151-.467-.182-.825-1.065-1.224-.915-.4-1.646-.336-1.77.465-.008.043-.013.066-.018.135-.068.023-.139.053-.209.064-.43.268-.662.669-.793 1.187-.13.533-.17 1.156-.205 1.869v.003c-.02.334-.17.838-.319 1.35-1.5 1.072-3.58 1.538-5.348.334a2.645 2.645 0 00-.402-.533 1.45 1.45 0 00-.275-.333c.182 0 .338-.03.465-.067a.615.615 0 00.314-.334c.108-.267 0-.697-.345-1.163-.345-.467-.931-.995-1.788-1.521-.63-.4-.986-.87-1.15-1.396-.165-.534-.143-1.085-.015-1.645.245-1.07.873-2.11 1.274-2.763.107-.065.037.135-.408.974-.396.751-1.14 2.497-.122 3.854a8.123 8.123 0 01.647-2.876c.564-1.278 1.743-3.504 1.836-5.268.048.036.217.135.289.202.218.133.38.333.59.465.21.201.477.335.876.335.039.003.075.006.11.006.412 0 .73-.134.997-.268.29-.134.52-.334.74-.4h.005c.467-.135.835-.402 1.044-.7zm2.185 8.958c.037.6.343 1.245.882 1.377.588.134 1.434-.333 1.791-.765l.211-.01c.315-.007.577.01.847.268l.003.003c.208.199.305.53.391.876.085.4.154.78.409 1.066.486.527.645.906.636 1.14l.003-.007v.018l-.003-.012c-.015.262-.185.396-.498.595-.63.401-1.746.712-2.457 1.57-.618.737-1.37 1.14-2.036 1.191-.664.053-1.237-.2-1.574-.898l-.005-.003c-.21-.4-.12-1.025.056-1.69.176-.668.428-1.344.463-1.897.037-.714.076-1.335.195-1.814.12-.465.308-.797.641-.984l.045-.022zm-10.814.049h.01c.053 0 .105.005.157.014.376.055.706.333 1.023.752l.91 1.664.003.003c.243.533.754 1.064 1.189 1.637.434.598.77 1.131.729 1.57v.006c-.057.744-.48 1.148-1.125 1.294-.645.135-1.52.002-2.395-.464-.968-.536-2.118-.469-2.857-.602-.369-.066-.61-.2-.723-.4-.11-.2-.113-.602.123-1.23v-.004l.002-.003c.117-.334.03-.752-.027-1.118-.055-.401-.083-.71.043-.94.16-.334.396-.4.69-.533.294-.135.64-.202.915-.47h.002v-.002c.256-.268.445-.601.668-.838.19-.201.38-.336.663-.336zm7.159-9.074c-.435.201-.945.535-1.488.535-.542 0-.97-.267-1.28-.466-.154-.134-.28-.268-.373-.335-.164-.134-.144-.333-.074-.333.109.016.129.134.199.2.096.066.215.2.36.333.292.2.68.467 1.167.467.485 0 1.053-.267 1.398-.466.195-.135.445-.334.648-.467.156-.136.149-.267.279-.267.128.016.034.134-.147.332a8.097 8.097 0 01-.69.468zm-1.082-1.583V5.64c-.006-.02.013-.042.029-.05.074-.043.18-.027.26.004.063 0 .16.067.15.135-.006.049-.085.066-.135.066-.055 0-.092-.043-.141-.068-.052-.018-.146-.008-.163-.065zm-.551 0c-.02.058-.113.049-.166.066-.047.025-.086.068-.14.068-.05 0-.13-.02-.136-.068-.01-.066.088-.133.15-.133.08-.031.184-.047.259-.005.019.009.036.03.03.05v.02h.003z"/></svg>',
};
export const Ic = ({ i }) => html`<span class="ic" dangerouslySetInnerHTML=${{ __html: ICON[i] || "" }}></span>`;

// A titled, icon-headed group panel — the primary way related info is clustered
// (server details / health / vitals / config). tone tints the icon square.
export function Panel({ icon, title, count, actions, tone, children, pad, lead }) {
  return html`<section class="panel">
    <div class="panel-head">
      ${icon ? html`<span class=${"panel-ic" + (tone ? " t-" + tone : "")}><${Ic} i=${icon}/></span>` : null}
      <h3>${title}</h3>${count != null ? html`<span class="panel-count">${count}</span>` : null}
      ${lead || null}<span class="grow"></span>${actions || null}
    </div>
    <div class=${"panel-body" + (pad === false ? " flush" : "")}>${children}</div>
  </section>`;
}

// ───────────────────────── toasts (imperative; outside the Preact tree) ─────────────────────────
export function toast(msg, kind = "info", ms = 5500) {
  const host = $("#toasts"); if (!host) return;
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.innerHTML = (ICON[kind] || ICON.info) + "<span>" + esc(msg) + "</span>";
  host.appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 250); }, ms);
}
export function copy(text, what) { navigator.clipboard.writeText(text); toast((what || T("Copied")) + ".", "ok", 1500); }

// ───────────────────────── mutations (optimistic, status-on-failure) ─────────────────────────
//
// Single funnel for every write. The optimistic `patch` (if given) is applied to the store
// immediately so the UI reacts instantly; the API call runs; on success the patch is kept until
// the next poll supersedes it (no blink); on failure it's reverted and an *explained* error is
// pinned to the row (rowErrors[key]) plus a toast. A safety timeout clears a stuck op and resyncs.
// Verify-only actions (create / rekey / anything revealing a secret) simply pass no `patch`.
let _mutSeq = 0;
// Optimistically claim an observed-but-unclaimed peer: write the roster entry the server is about to create,
// so apply() re-derives it out of the orphans table and into the peers grid on the click instead of a poll
// later. The id is a placeholder — the server assigns the real one, and the next poll supersedes this whole
// overlay — so nothing downstream may key off it.
export function adoptOrphanPatch(o) {
  return s => {
    const target = { node: o.node, iface: o.iface, ip: (o.allowed_ips || "").split("/")[0] };
    const peers = (s.roster && s.roster.peers) || {};
    const mine = Object.entries(peers).find(([, p]) => p && p.pubkey === o.pubkey);
    if (mine) {                                   // known peer gaining a deployment → just add the target
      const p = mine[1];
      if (!(p.targets || []).some(t => t && t.node === target.node && t.iface === target.iface))
        p.targets = (p.targets || []).concat([target]);
      return;
    }
    peers["adopting:" + o.node + "|" + o.iface + "|" + o.pubkey] = {
      user_id: null, title: "", pubkey: o.pubkey, psk: o.preshared_key || "",
      targets: [target], created_at: Math.floor(Date.now() / 1000),
    };
  };
}
export function mutate({ key, patch, call, onOk, timeout = 8000 }) {
  const id = "m" + (++_mutSeq);
  if (key) delete Store.rowErrors[key];
  if (patch) { Store.pending[id] = { apply: patch, done: false }; }
  if (patch || key) Store.apply();
  const timer = setTimeout(() => { if (Store.pending[id]) { delete Store.pending[id]; Store.poll().catch(() => {}); } }, timeout);
  return (async () => {
    let r;
    try { r = await call(); }
    catch (e) { r = { ok: false, error: String((e && e.message) || e) }; }
    clearTimeout(timer);
    if (!r || !r.ok) {
      delete Store.pending[id];                                  // revert optimistic change
      if (key) Store.rowErrors[key] = { msg: (r && (srvText(r) || r.code)) || T("request failed"), at: Date.now() };
      Store.apply();
      toast((r && (srvText(r) || r.code)) || T("Action failed."), "err", 4500);
      return r || { ok: false };
    }
    if (key) delete Store.rowErrors[key];
    if (onOk) { try { onOk(r); } catch (_) {} }
    if (Store.pending[id]) Store.pending[id].done = true;        // keep applied until the next poll supersedes
    await Store.poll().catch(() => {});
    return r;
  })();
}
export function rowError(key) { return Store.rowErrors[key] || null; }
export function dismissError(key) { if (Store.rowErrors[key]) { delete Store.rowErrors[key]; Store.apply(); } }

// ───────────────────────── modal ─────────────────────────
// Modal STACK. openModal replaces the current top (so every legacy single-modal flow behaves exactly
// as before — the stack is just length 1), pushModal stacks a CHILD over its parent (parent stays
// open behind it), closeModal pops back to the parent. _stack is a synchronous mirror of the state.
let _setStack = () => {};
let _stack = [];
let _modalSeq = 0;   // bumps on every open/close — lets a confirm tell if onConfirm replaced the modal
function _applyStack(next) { _stack = next; _modalSeq++; _setStack(next); }
export function openModal(node) { _applyStack(_stack.length ? [..._stack.slice(0, -1), node] : [node]); }
export function pushModal(node) { _applyStack([..._stack, node]); }
function _blurActive() { requestAnimationFrame(() => { const a = document.activeElement; if (a && a.blur && a.tagName !== "BODY") a.blur(); }); }
export function closeModal() { _applyStack(_stack.slice(0, -1)); _blurActive(); }   // drop the focus ring the trigger regains on ESC/close
export function closeAllModals() { _applyStack([]); _blurActive(); }
let _sheetStack = [];   // mounted Sheet tokens (LIFO) — only the topmost handles Esc/Enter/Tab

// Row activation: a single click runs `fn` after a short delay; a double click cancels that and runs `dbl`
// instead (open the QR modal). Clicks on interactive children (buttons/links/inputs/the assign combo) pass
// through untouched. One shared timer is enough — a person clicks one row at a time.
let _rowClickT = null;
const _rowInteractive = e => !!(e.target.closest && e.target.closest("button, a, input, select, textarea, label, .assigncell, .rowacts, .selwrap"));
export function rowSingle(e, fn) { if (_rowInteractive(e)) return; clearTimeout(_rowClickT); _rowClickT = setTimeout(() => { _rowClickT = null; fn(); }, 200); }
export function rowDouble(e, fn) { if (_rowInteractive(e)) return; clearTimeout(_rowClickT); _rowClickT = null; fn(); }
export const rowNoSelect = e => { if (e.detail > 1) e.preventDefault(); };   // stop the 2nd click of a double-click from selecting the row text

// Minimal portal — renders children into a body-level node. A position:fixed popover that lives inside a
// card paints BEHIND a later sibling once its own card forms a stacking context (turn cards lift with a
// transform on hover; a `.down` card carries opacity:.5) — z-index can't rescue it across contexts.
// Rendering at <body> escapes every ancestor context. Preact core has no createPortal, so we drive a
// detached container with render().
export function Portal({ children }) {
  const host = useRef(null);
  if (!host.current) host.current = document.createElement("div");
  useEffect(() => { const el = host.current; document.body.appendChild(el); return () => { render(null, el); el.remove(); }; }, []);
  useEffect(() => { render(children, host.current); });
  return null;
}

// Generic hover/click bubble (the DepBadge mechanics, reusable): hover opens, click pins (touch),
// position:fixed anchored to the trigger so overflow:hidden can't clip it. The bubble is PORTALED to
// <body> so it floats above sibling cards regardless of their stacking contexts.
// hoverOnly: no click-to-pin — clicks fall through to whatever the trigger sits inside (e.g. a card link),
// so a badge can show a hover bubble AND still navigate on click.
export function Popover({ trigger, cls, popCls, alignRight, children, hoverOnly, autoOpen, flipFit, clickOnly }) {
  const [open, setOpen] = useState(false), [pinned, setPinned] = useState(!!autoOpen), [pos, setPos] = useState(null);
  const ref = useRef(null), popRef = useRef(null), closeT = useRef(null);
  const show = open || pinned;
  const cancelClose = () => clearTimeout(closeT.current);
  const scheduleClose = () => { cancelClose(); closeT.current = setTimeout(() => setOpen(false), 140); };
  // alignRight: anchor the popover's left to the trigger's RIGHT edge, then translateX(-100%) so its own right
  // edge lines up there (under the value, not the label) — scrollbar-proof, no width guessing.
  const place = () => { const el = ref.current; if (!el) return; const r = el.getBoundingClientRect();
    // flip ABOVE the trigger when there's little room below and more room above (bounded popovers scroll internally)
    const ph = (popRef.current && popRef.current.offsetHeight) || 340;
    const pw = (popRef.current && popRef.current.offsetWidth) || 300;
    const below = window.innerHeight - r.bottom, above = r.top, flip = !!flipFit && below < ph + 12 && above > below;
    // left-anchored popovers can run off the RIGHT edge (a trigger near the viewport edge) — clamp into view (8px margin).
    let left = alignRight ? r.right + 3 : Math.max(8, Math.min(r.left, window.innerWidth - pw - 8));
    setPos({ left: Math.round(left), top: Math.round(flip ? r.top - 6 : r.bottom + 6), flip }); };   // alignRight: +3px so the bubble's right edge sits a touch past where the value ends
  useEffect(() => {
    if (!show) return; place();
    const onMove = () => place();
    const onDoc = e => { const t = e.target; if (!((ref.current && ref.current.contains(t)) || (popRef.current && popRef.current.contains(t)))) { setPinned(false); setOpen(false); } };
    window.addEventListener("scroll", onMove, true); window.addEventListener("resize", onMove);
    if (pinned) document.addEventListener("mousedown", onDoc, true);
    return () => { window.removeEventListener("scroll", onMove, true); window.removeEventListener("resize", onMove); document.removeEventListener("mousedown", onDoc, true); };
  }, [show, pinned]);
  useEffect(() => () => clearTimeout(closeT.current), []);
  return html`<span class=${(cls || "") + (show ? " on" : "")} ref=${ref}
    onClick=${hoverOnly ? null : (e => { e.stopPropagation(); e.preventDefault(); setPinned(p => !p); })}
    onMouseEnter=${clickOnly ? null : () => { cancelClose(); setOpen(true); }} onMouseLeave=${clickOnly ? null : scheduleClose}>${trigger}
    ${show && pos ? html`<${Portal}><div ref=${popRef} class=${"deppop onlpop " + (popCls || "") + (pos.flip ? " flip" : "")} style=${"left:" + pos.left + "px;top:" + pos.top + "px;transform:" + (alignRight ? "translateX(-100%)" : "") + (pos.flip ? " translateY(-100%)" : "")}
      onClick=${e => e.stopPropagation()} onMouseEnter=${cancelClose} onMouseLeave=${scheduleClose}>${children}</div><//>` : null}
  </span>`;
}

/* Every label table below is built ONCE, on first use — never at module load. T() only answers correctly
   after loadLang() has resolved, and these modules are imported before that; a table frozen at import time
   would be English forever. Caching for the process is safe because setLang() reloads the page. */
const once = build => { let v; return () => (v !== undefined ? v : (v = build())); };

// Display label overrides where the internal status key differs from the word shown. Two remaps, both
// display-only (keys stay put so persisted settings / filters / deep-links don't move):
//   disabled → "blocked"    — the access-revoke settled state (key mirrors the roster `disabled` flag)
//   blocked  → "restricted" — the DPI/no-handshake FAULT (freed the word "blocked" for the revoke state)
export const STATUS_LABEL = { disabled: "blocked", blocked: "restricted" };
/* The panel's status vocabulary — one table, because these words are the thing an operator reads on every
   badge, filter and column, and they have to mean the same everywhere. Keys carry a `status|` context: the
   same English word translates differently as a status than as a verb elsewhere ("Restoring" the noun-state
   vs "restoring" the running op below), and the context is stripped for the English fallback. */
const STATUS_WORDS = once(() => ({
  online: T("status|Online"), ready: T("status|Ready"), pending: T("status|Pending"), creating: T("status|Creating"),
  rotating: T("status|Rotating"), restoring: T("status|Restoring"), partial: T("status|Partial"),
  dangling: T("status|Dangling"), broken: T("status|Broken"), faulty: T("status|Faulty"),
  blocked: T("status|Blocked"), restricted: T("status|Restricted"), expired: T("status|Expired"),
  expiring: T("status|Expiring"), blocking: T("status|Blocking"), unknown: T("status|Unknown"),
  unassigned: T("status|Unassigned"), orphan: T("status|Orphan"), removing: T("status|Removing"), empty: T("status|Empty"),
}));
// badges show a capitalised label (Online / Dangling / Broken …); an unlisted status falls back to its key
export const statusLabel = s => { const k = STATUS_LABEL[s] || s || ""; return STATUS_WORDS()[k] || (k.charAt(0).toUpperCase() + k.slice(1)); };

// ── deferred navigation intent: "open Settings, on THIS section" ────────────────────────────────
// The target screen may not be mounted yet (a fresh navigation) or may already be (a modal asking to jump
// there), so both paths exist: a pending value the screen picks up on mount, and a setter the mounted
// screen registers. It lives here rather than in the router because opening Settings from inside a modal
// has to close the modal stack first, and that stack is this module's.
let _pendingSection = null, _pendingTurnIps = false, _setSection = () => {};
export function goSettings(section) { _pendingSection = section; closeAllModals(); go("#/panel/settings"); }
export function goSettingsTurnIps() { _pendingSection = "turn"; _pendingTurnIps = true; closeAllModals(); go("#/panel/settings"); }
export const setPendingSection = s => { _pendingSection = s; };
export const takePendingSection = () => { const s = _pendingSection; _pendingSection = null; return s; };
export const takePendingTurnIps = () => { const v = _pendingTurnIps; _pendingTurnIps = false; return v; };
export const registerSectionSetter = fn => { _setSection = fn || (() => {}); };
export const gotoSettingsSection = s => _setSection(s);

// The generic inline tag chip — every dense row signature is built from these. `color` tints via --tgc.
export function Tag({ kind, label, color, muted }) {
  return html`<span class=${"tg tg-" + (kind || "gen") + (muted ? " muted" : "")} style=${color && !muted ? "--tgc:" + color : ""}>${label}</span>`;
}

// ───────────────────────── sheets, section furniture, confirms ─────────────────────────
// The recurring section header: <h2>title</h2> + an optional .count pill + a right-hand spacer.
// title/count may be a string or html; count null → no pill; grow===false → no spacer. The few
// headers with a styled/classed h2 or extra children (the Live .tags) stay inline.
/* `anchor` is a STABLE identity for the section, independent of the words in its heading. The Overview rail
   jumps between sections and scroll-spies them; it used to find them by matching the <h2> text, which is
   exactly the coupling that breaks the moment the heading is translated — silently, since a nav button that
   finds nothing simply does nothing. Anything that needs to locate a section must key off data-sec. */
export function secTitle(title, count, grow, anchor) {
  return html`<div class="section-title" data-sec=${anchor || null}><h2>${title}</h2>${count != null ? html`<span class="count">${count}</span>` : null}${grow === false ? null : html`<span class="grow"></span>`}</div>`;
}

// The shared toolbar search box (Peers / Users / Activity / Live / expanded-peer grids): a magnifier
// icon + a filter input. Only placeholder / value / onInput vary per screen.
export function SearchBox({ placeholder, value, onInput }) {
  return html`<div class="search"><${Ic} i="search"/><input placeholder=${placeholder} value=${value} onInput=${onInput}/></div>`;
}

// The standard modal footer action row: [optional `left` buttons] · spacer · Cancel · one primary/danger action.
// Collapses the ~15 dialogs that share this exact shape into one call; irregular footers (multiple actions,
// a left-aligned Cancel) stay inline. `danger` paints the action red; `actionCls` overrides the class outright;
// `title`/`disabled` are only emitted when passed, so the rendered DOM stays byte-identical to the old inline form.
export function footRow({ left, cancelLabel, onCancel, action, onAction, danger, actionCls, disabled, title }) {
  return html`<${Fragment}>${left || null}<span class="grow"></span><button class="btn btn-ghost" onClick=${onCancel}>${cancelLabel || T("Cancel")}</button>${action != null ? html`<button class=${actionCls || ("btn " + (danger ? "btn-danger" : "btn-primary"))} disabled=${disabled} ...${title != null ? { title } : {}} onClick=${onAction}>${action}</button>` : null}<//>`;
}
// subject = {kind:"peer"|"user", id} — when that peer/user is blocked, the whole modal takes the red "blocked"
// treatment (border + header tint + a BLOCKED chip). Looked up live (useStore) so it reacts to block/unblock
// done from within the modal, on every modal that carries a subject (QR / view / edit / targets / turn).
export function subjectBlocked(subject) {
  if (!subject || !subject.id) return false;
  const rec = subject.kind === "user" ? Store.user(subject.id) : Store.peer(subject.id);
  return !!(rec && rec.disabled);
}
export function Sheet({ title, children, foot, onClose, width, headExtra, dirtyRef, closeRef, onBack, noGuard, subject }) {
  useStore();                                    // track live block/unblock while the modal is open
  onClose = onClose || closeModal;
  const blocked = subjectBlocked(subject);
  const ref = useRef(null);
  const dirty = useRef(false);   // set by a real user edit — programmatic value changes don't fire input/change
  const discardRef = useRef(false);             // armed once; read live so the captured onKey closure stays correct
  const [discard, setDiscardState] = useState(false);
  const setDiscarding = v => { discardRef.current = v; setDiscardState(v); };
  const fields = () => Array.from(ref.current ? ref.current.querySelectorAll("input,textarea,select") : []);
  // closing a dirty sheet swaps the footer into an inline "discard?" confirm instead of a native dialog. `dirtyRef`
  // lets a caller flag changes the input/change listener can't see (e.g. click-toggled grids). `noGuard` opts out
  // entirely — view modals (QR / turn configs) save every field inline, so there's nothing to discard.
  const tryClose = () => { if (!noGuard && (dirty.current || (dirtyRef && dirtyRef.current)) && !discardRef.current) { setDiscarding(true); return; } onClose(); };
  if (closeRef) closeRef.current = tryClose;   // expose the guarded close so a footer Cancel routes through it too
  // The keydown listener below is registered ONCE (useEffect []), but openModal REPLACES one <Sheet> with
  // another at the same position, so Preact reuses this instance and only updates props — the effect never
  // re-runs. Without this ref, Esc would keep calling the FIRST render's onClose: a config sheet reached via a
  // `back` (turn configs → back to QR) closed everything on Esc while ✕/backdrop/Back (recreated each render)
  // correctly went back. Route Esc through the live tryClose instead.
  const tryCloseRef = useRef(tryClose); tryCloseRef.current = tryClose;
  const noGuardRef = useRef(noGuard); noGuardRef.current = noGuard;   // read live (the Sheet instance is reused across openModal)

  useEffect(() => {
    const root = ref.current; if (!root) return;
    const onEdit = () => { dirty.current = true; };
    root.addEventListener("input", onEdit, true);
    root.addEventListener("change", onEdit, true);
    // fields can opt out of autofocus with [data-noautofocus] (e.g. the VK box); and a view modal (noGuard)
    // never grabs focus onto a button as a fallback
    let first = root.querySelector("[autofocus]") || root.querySelector("input:not([data-noautofocus]),textarea:not([data-noautofocus]),select,button.btn-primary");
    if (first && noGuardRef.current && first.tagName === "BUTTON") first = null;
    if (first) setTimeout(() => { try { first.focus(); } catch (_) {} }, 0);
    const tok = {}; _sheetStack.push(tok);   // only the TOP stacked Sheet reacts to Esc/Enter/Tab
    const onKey = e => {
      if (_qrZoomOpen()) return;   // a QR enlargement is open — let it handle Esc (collapse it, keep the modal)
      if (_sheetStack[_sheetStack.length - 1] !== tok) return;   // a child modal is on top — defer to it
      if ((e.key === "Enter" || e.key === "Escape") && e.target && e.target.dataset && e.target.dataset.enter === "self") return;   // input handles its own Enter/Esc (e.g. inline rename) — don't submit/close the sheet
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); tryCloseRef.current(); return; }
      if (e.key === "Enter" && !noGuardRef.current && e.target.tagName !== "TEXTAREA" && !e.shiftKey) {
        // view modals (QR / turn) have no single submit action — Enter must not fire a random primary button
        // (e.g. "Enable subscription"); their own fields (the VK box) handle Enter themselves
        const primary = root.querySelector(".sheet-foot .btn-primary:not([disabled])") || root.querySelector(".btn-primary:not([disabled])");
        if (primary) { e.preventDefault(); primary.click(); }
        return;
      }
      if (e.key === "Tab") {                                   // focus trap
        const f = fields().concat(Array.from(root.querySelectorAll("button"))).filter(el => !el.disabled && el.offsetParent !== null);
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey, true);          // capture so it works regardless of focus
    return () => {
      document.removeEventListener("keydown", onKey, true);
      _sheetStack = _sheetStack.filter(t => t !== tok);
      root.removeEventListener("input", onEdit, true);
      root.removeEventListener("change", onEdit, true);
    };
  }, []);

  return html`<div class="overlay show" onClick=${e => { if (e.target.classList.contains("overlay")) tryClose(); }}>
    <div class=${"sheet" + (blocked ? " blocked" : "")} role="dialog" aria-modal="true" ref=${ref} style=${width ? "width:" + width + "px;max-width:calc(100vw - 32px)" : ""}>
      <div class="sheet-head"><h3>${title}</h3>${blocked ? html`<span class="blocked-tag"><${Ic} i="off"/> ${T("status|Blocked")}</span>` : null}${headExtra || null}${onBack
        ? html`<button class="sheet-back" onClick=${tryClose}><${Ic} i="back"/> ${T("Back")}</button>`
        : html`<button class="x" onClick=${tryClose}>×</button>`}</div>
      <div class="sheet-body">${children}</div>
      ${(foot || discard) ? html`<div class="sheet-foot">${discard
        ? html`<${Fragment}><span class="discard-msg"><${Ic} i="warn"/> ${T("Discard unsaved changes?")}</span><span class="grow"></span>
            <button class="btn btn-ghost" onClick=${() => setDiscarding(false)}>${T("Keep editing")}</button>
            <button class="btn btn-danger" onClick=${onClose}>${T("Discard")}</button></>`
        : foot}</div>` : null}
    </div></div>`;
}

// Designed confirmation modal — the in-app replacement for native confirm(). `danger` paints the
// action button red; `danger`/`warn` give the notice a warn tint + icon (else a neutral info note).
// `back` (optional) = where Cancel / Esc returns to (e.g. reopen the peer view it was launched from);
// default just closes. After a confirmed action we always close, since the action changed the state.
// Error/log bodies (captured installer output, command errors) carry ANSI colour codes + newlines that read
// as one mashed line. `log:` renders them line-by-line, ANSI stripped for humans ("rendered"), with a toggle
// to the unprocessed log ("raw", ESC shown as ␛, still line-by-line). Used by every error/detail modal.
export function logRendered(s) { return String(s == null ? "" : s).replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g, "").replace(/\r/g, "").replace(/[ \t]+$/gm, ""); }
export function logRaw(s) { return String(s == null ? "" : s).replace(/\x1b/g, "␛").replace(/\r/g, ""); }
export function LogBody({ text, raw }) {
  const t = (raw ? logRaw(text) : logRendered(text)).replace(/\n+$/, "");
  return html`<div class=${"logview" + (raw ? " raw" : "")}>${t.split("\n").map(l => html`<div class="logline">${l === "" ? " " : l}</div>`)}</div>`;
}
// Opened from within a modal → stack it as a child (parent stays mounted; ✕/Esc/Cancel pop back). Opened
// standalone (from a table/card) → open as the root. This is the one rule: a modal opened from a modal is
// a child. `openChildOrRoot` captures it for every opener that can be reached both ways.
export function openChildOrRoot(node) { (_stack.length ? pushModal : openModal)(node); }
export function openConfirm(opts) { openChildOrRoot(html`<${ConfirmSheet} ...${opts}/>`); }

/* "Confirm by typing <b>NAME</b>" — a placeholder that has to be BOLD, so it cannot be one text node. It is
   still ONE translatable sentence: split the translation on its own {name} marker and render the parts around
   the bold word. That keeps each language's word order (Russian puts the name last) without concatenating. */
function typePrompt(word) {
  const [before, after] = Tsplit("Confirm by typing {name}", "name");
  return html`<${Fragment}>${before}<b>${word}</b>${after}<//>`;
}
export function ConfirmSheet({ title, body, note, log, confirmLabel, busyLabel, cancelLabel, danger, warn, onConfirm, back, requireType }) {
  back = back || closeModal;
  const [busy, setBusy] = useState(false);
  const [raw, setRaw] = useState(false);
  const [typed, setTyped] = useState("");
  const isLog = log != null && String(log) !== "";
  const canToggle = isLog && logRaw(log) !== logRendered(log);   // only offer raw/rendered when they differ (ANSI present)
  const typeOk = !requireType || typed.trim() === requireType;   // type-to-confirm gate for destructive actions
  const go = async () => { if (busy || !typeOk) return; if (!onConfirm) return back(); setBusy(true); const seq = _modalSeq;
    try { await onConfirm(); } finally { if (_modalSeq === seq) closeModal(); } };   // skip close if onConfirm opened another modal (no flicker)
  const tone = danger || warn;
  return html`<${Sheet} title=${title} onClose=${back}
    foot=${html`<${Fragment}>
      ${canToggle ? html`<button class="btn btn-ghost logtoggle" onClick=${() => setRaw(r => !r)}>${raw ? T("Display rendered") : T("Display raw")}</button>` : null}
      <span class="grow"></span>
      <button class=${"btn " + (onConfirm ? "btn-ghost" : "btn-primary")} onClick=${back}>${onConfirm ? (cancelLabel || T("Cancel")) : (confirmLabel || T("Close"))}</button>
      ${onConfirm ? html`<button class=${"btn " + (danger ? "btn-danger" : "btn-primary")} disabled=${busy || !typeOk} onClick=${go}>${busy ? html`<span class="spin sm"></span>${busyLabel || T("Working…")}` : (confirmLabel || T("Confirm"))}</button>` : null}</>`}>
    ${isLog
      ? html`<${LogBody} text=${log} raw=${raw}/>`
      : html`<${Fragment}>
          <div class=${"notice" + (tone ? " warn" : "")}><${Ic} i=${tone ? "warn" : "info"}/><span>${body}</span></div>
          ${note || null}
          ${requireType ? html`<label class="confirm-type"><span>${typePrompt(requireType)}</span>
            <input class="ctype-input" type="text" autofocus spellcheck="false" autocomplete="off" placeholder=${requireType} value=${typed}
              onInput=${e => setTyped(e.target.value)} onKeyDown=${e => { if (e.key === "Enter") go(); }}/></label>` : null}
        <//>`}
  <//>`;
}

// A QR enlargement (see qrZoom) is a plain DOM overlay outside the Preact tree, and while one is open Esc
// must collapse IT rather than close the sheet underneath. That overlay lives in the config/QR layer, above
// this module, so the sheet asks through an injected probe instead of importing upward.
let _qrZoomOpen = () => false;
export const setQrZoomProbe = fn => { _qrZoomOpen = fn; };

// App registers how a modal stack actually renders (see the header note).
export const setModalRenderer = fn => { _setStack = fn; };
// How deep the modal stack is. Openers ask this to decide "replace the top" vs "stack a child", and the
// service-issue alert uses it to avoid popping over a modal the operator already has open.
export const modalDepth = () => _stack.length;
// Drop every modal WITHOUT the focus-blur closeModal does. The hash router calls this on navigation: the
// screen underneath is being replaced anyway, and blurring there would fight the new screen's autofocus.
export const clearModalStack = () => _applyStack([]);
export const blurActive = () => _blurActive();

// ───────────────────────── drag-to-reorder ─────────────────────────
// Order `items` by their position in `savedOrder` (a list of ids); ids not in the saved order keep
// their original relative order and go LAST (so a newly-reported iface/turn appears at the end).
export function orderById(items, savedOrder, idOf) {
  const ord = savedOrder || [];
  if (!ord.length) return items;
  const pos = new Map(ord.map((id, i) => [id, i]));
  return items.map((it, i) => [it, i]).sort((a, b) => {
    const pa = pos.has(idOf(a[0])) ? pos.get(idOf(a[0])) : Infinity;
    const pb = pos.has(idOf(b[0])) ? pos.get(idOf(b[0])) : Infinity;
    return pa - pb || a[1] - b[1];
  }).map(x => x[0]);
}
// 6-dot grip glyph used as the drag handle on reorderable cards.
export const GRIP_SVG = `<svg width="11" height="16" viewBox="0 0 11 16" fill="currentColor"><circle cx="3" cy="3" r="1.4"/><circle cx="8" cy="3" r="1.4"/><circle cx="3" cy="8" r="1.4"/><circle cx="8" cy="8" r="1.4"/><circle cx="3" cy="13" r="1.4"/><circle cx="8" cy="13" r="1.4"/></svg>`;
// HTML5 drag-reorder. `ids` is the CURRENT visible order; `onReorder(newIds)` persists it. Returns
// per-item props: grip(id) for the handle, zone(id) for the card wrapper, plus the live dragId.
// FLIP: after a reorder re-renders the (keyed) cards into new positions, slide each from where it WAS
// (`first` rects, snapshot at drop time) to where it now is, so it's visible what moved and where.
export function flipPlay(container, first) {
  requestAnimationFrame(() => {
    const moved = [];
    for (const el of container.querySelectorAll("[data-rid]")) {
      const f = first.get(el.dataset.rid); if (!f) continue;
      const l = el.getBoundingClientRect();
      const dx = f.left - l.left, dy = f.top - l.top;
      if (dx || dy) { el.style.transition = "none"; el.style.transform = "translate(" + dx + "px," + dy + "px)"; moved.push(el); }   // INVERT
    }
    if (!moved.length) return;
    requestAnimationFrame(() => { for (const el of moved) { el.style.transition = "transform .24s cubic-bezier(.2,.7,.2,1)"; el.style.transform = ""; } });   // PLAY
    setTimeout(() => { for (const el of moved) { el.style.transition = ""; el.style.transform = ""; } }, 320);
  });
}
export function useReorder(ids, onReorder, axis = "x", sel = {}) {   // axis "x" = horizontal grid (left/right edges); "y" = vertical list (top/bottom); sel = {container, card} CSS selectors
  const CONT_SEL = sel.container || ".ifgrid, .nodegrid";   // the drop container (dragEnd has no event target for it)
  const CARD_SEL = sel.card || ".ifcard, .ncard";           // the draggable row/card (for the floating ghost + FLIP)
  const [drag, setDrag] = useState(null);     // { id, k } — for the highlight (k = insertion index among the OTHER cards)
  const dragId = drag && drag.id;
  const prev = useRef(null);      // our floating translucent preview
  const off = useRef([0, 0]);     // cursor offset within the grabbed card
  const cont = useRef(null);      // container element (dragEnd has no event target for it)
  const liveK = useRef(-1);       // CURRENT insertion index — a ref so dragEnd never reads a stale closure
  const idRef = useRef(null);     // the dragged id
  const esc = useRef(false);      // ESC pressed mid-drag → cancel (best-effort; some browsers swallow keydown while dragging)
  const onKey = useRef(null);
  const rest = dragId ? ids.filter(x => x !== dragId) : ids;
  const k = drag ? drag.k : -1;
  const gapL = (k > 0 && k <= rest.length) ? rest[k - 1] : null;
  const gapR = (k >= 0 && k < rest.length) ? rest[k] : null;
  const trail = axis === "y" ? " drop-b" : " drop-r";
  const lead = axis === "y" ? " drop-t" : " drop-l";
  // insertion index from the cursor over the WHOLE container (releasing in a gap / past the ends still
  // lands at the nearest spot, no pixel-precise aiming). Counts the non-dragged cards before the cursor.
  const indexAt = (container, x, y) => {
    let i = 0;
    for (const el of container.querySelectorAll("[data-rid]")) {
      if (el.dataset.rid === dragId) continue;
      const r = el.getBoundingClientRect();
      if (axis === "y") { if (y > r.top + r.height / 2) i++; }
      else if (r.bottom < y) i++;
      else if (y >= r.top && (r.left + r.width / 2) < x) i++;
    }
    return i;
  };
  const movePrev = (x, y) => { if (prev.current) prev.current.style.transform = "translate(" + (x - off.current[0]) + "px," + (y - off.current[1]) + "px)"; };
  const stopPreview = () => { if (prev.current) { prev.current.remove(); prev.current = null; } };
  // Commit on dragEND (always fires) using the LAST highlighted position, so releasing OUTSIDE the
  // container still drops at the highlighted gap. ESC, or never highlighting a spot, returns to origin.
  const finish = () => {
    if (onKey.current) { window.removeEventListener("keydown", onKey.current, true); onKey.current = null; }
    const c = cont.current, kk = liveK.current, did = idRef.current, cancelled = esc.current;
    stopPreview(); cont.current = null; idRef.current = null; liveK.current = -1; esc.current = false;
    setDrag(null);
    if (cancelled || kk < 0 || !c || !did) return;            // ESC / nothing highlighted → back to original
    const first = new Map();                                   // FLIP: snapshot positions before the reorder
    for (const el of c.querySelectorAll("[data-rid]")) first.set(el.dataset.rid, el.getBoundingClientRect());
    const arr = ids.filter(x => x !== did); arr.splice(kk, 0, did);
    if (arr.join(" ") !== ids.join(" ")) { onReorder(arr); flipPlay(c, first); }
  };
  return {
    dragId,
    grip(id) {
      return {
        draggable: true,
        onDragStart: e => {
          cont.current = e.currentTarget.closest(CONT_SEL);
          idRef.current = id; liveK.current = -1; esc.current = false;
          onKey.current = ev => { if (ev.key === "Escape") esc.current = true; };
          window.addEventListener("keydown", onKey.current, true);
          const card = e.currentTarget.closest(CARD_SEL);
          try {
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", id);
            const empty = new Image(); empty.src = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
            e.dataTransfer.setDragImage(empty, 0, 0);
            if (card) {
              const r = card.getBoundingClientRect();
              off.current = [e.clientX - r.left, e.clientY - r.top];
              const g = card.cloneNode(true);
              g.classList.add("drag-ghost");
              g.style.cssText = "position:fixed;left:0;top:0;margin:0;width:" + r.width + "px;height:" + r.height + "px;pointer-events:none;z-index:9999;transform:translate(" + r.left + "px," + r.top + "px)";
              document.body.appendChild(g);
              prev.current = g;
            }
          } catch (_) {}
          setDrag({ id, k: -1 });
        },
        onDrag: e => { if (e.clientX || e.clientY) movePrev(e.clientX, e.clientY); },   // follow the cursor (fires even outside the container)
        onDragEnd: () => finish(),
      };
    },
    container() {
      return {
        onDragOver: e => { if (!dragId) return; e.preventDefault(); try { e.dataTransfer.dropEffect = "move"; } catch (_) {}
          movePrev(e.clientX, e.clientY);
          const nk = indexAt(e.currentTarget, e.clientX, e.clientY);
          liveK.current = nk;
          if (!drag || drag.k !== nk) setDrag({ id: dragId, k: nk }); },
        onDrop: e => { e.preventDefault(); },   // the real commit happens in dragEnd (covers release-outside too)
      };
    },
    item(id) {
      return { rid: id, cls: (dragId === id ? " dragging" : "") + (id === gapL ? trail : "") + (id === gapR ? lead : "") };
    },
  };
}

// ───────────────────────── shared bits ─────────────────────────
// Interface op lifecycle labels, one per verb \u00d7 phase. Accessors rather than tables so the words are
// looked up after the catalog loads (see `once` above); the verb itself is the fallback.
const IFOP_BUSY_W = once(() => ({ start: T("ifop|starting"), stop: T("ifop|stopping"), restart: T("ifop|restarting"), apply: T("ifop|applying"), ignore: T("ifop|ignoring"), unignore: T("ifop|restoring") }));
const IFOP_DONE_W = once(() => ({ start: T("ifop|started"), stop: T("ifop|stopped"), restart: T("ifop|restarted"), apply: T("ifop|applied"), ignore: T("ifop|ignored"), unignore: T("ifop|restored") }));
const IFOP_FAIL_W = once(() => ({ start: T("ifop|failed to start"), stop: T("ifop|failed to stop"), restart: T("ifop|failed to restart"), apply: T("ifop|failed to apply"), ignore: T("ifop|couldn\u2019t ignore"), unignore: T("ifop|couldn\u2019t restore") }));
export const ifopBusy = verb => IFOP_BUSY_W()[verb] || verb;
export const ifopDone = verb => IFOP_DONE_W()[verb] || verb;
export const ifopFail = verb => IFOP_FAIL_W()[verb] || T("ifop|failed");
// Verbs that resolve entirely IN THE PANEL (no node round-trip). trackIfaceOps judges an op by watching the
// interface come up or go down on the node, and its final `else` branch would grab these too and call them
// failed for never changing a datapath they never touch. Their click handler owns the whole lifecycle.
export const IFOP_PANEL = new Set(["ignore", "unignore"]);
// The optimistic op badge for an interface/WDTT card (busy→ok→fail flash, driven by trackIfaceOps). Returns the
// tag vnode or null so a card can show a live "applying/applied/failed" status like every other card.
export function opTag(key) {
  const op = Store.ifaceOp[key]; if (!op) return null;
  if (op.phase === "busy") return html`<span class="tg tg-busy"><${Ic} i="clock"/>${ifopBusy(op.verb)}</span>`;
  if (op.phase === "ok") return html`<span class="tg tg-ready"><${Ic} i="check"/>${ifopDone(op.verb)}</span>`;
  if (op.phase === "fail") return html`<${StatusTag} cls="tg-busy del" icon="warn" label=${ifopFail(op.verb)} msg=${op.err || T("the change failed on the node")} title=${T("Save failed on the node")}/>`;
  return null;
}
export const STATUS_RANK = { disabled: -1, expired: -1, blocking: -1, dangling: 0, broken: 0, blocked: 1, faulty: 1, partial: 1, pending: 2, creating: 2, rotating: 2, restoring: 2, expiring: 4, unknown: 3, unassigned: 4, online: 5, ready: 6 };
export const STATUS_ICON = { online: "check", ready: "clock", partial: "warn", pending: "clock", creating: "clock", rotating: "refresh",
  blocked: "warn", faulty: "warn", dangling: "err", broken: "warn", unknown: "info", unassigned: "user", orphan: "link", removing: "trash", empty: "info",
  disabled: "off", blocking: "off", restoring: "refresh", expired: "warn", expiring: "warn" };

// a node/panel host that's mid re-install or method conversion (signalled before it goes down)
const PROC_LABEL = once(() => ({
  reinstalling: T("re-installing"), "converting-bare": T("converting to bare-metal"), "converting-docker": T("converting to docker"), updating: T("updating"), uninstalling: T("uninstalling"),
  reinstalled: T("re-installed"), "reinstalled-updated": T("re-installed and updated"), "converted-bare": T("converted to bare-metal"), "converted-docker": T("converted to docker"), updated: T("updated"), uptodate: T("up to date"),
  "reinstall-aborted": T("re-install aborted"), "convert-aborted": T("convert aborted"), "update-aborted": T("update aborted"), "uninstall-aborted": T("uninstall aborted"),
  "reinstall-failed": T("re-install failed"), "convert-failed": T("convert failed"), "update-failed": T("update failed"), "uninstall-failed": T("uninstall failed"), failed: T("proc|failed") }));
// a node still AWAITING ENROLL never came up, so a "re-install" of it is really a first install — relabel the reinstall* states
const PROC_LABEL_FRESH = once(() => ({ reinstalling: T("installing"), reinstalled: T("installed"), "reinstalled-updated": T("installed and updated"),
  "reinstall-aborted": T("install aborted"), "reinstall-failed": T("install failed") }));
// The one way to name a proc state. `fresh` picks the first-install wording; an unknown state shows its key.
export const procLabel = (state, fresh) => (fresh && PROC_LABEL_FRESH()[state]) || PROC_LABEL()[state] || state;
// Lifecycle tag categories. inProc = an op actually running (violet clock, blocks actions). Terminals:
// success (green, ~5s, no ×), aborted (grey + ×), failed (red + error popup + ×) — all shown beside the real status.
export const procFailed  = s => !!s && /failed$/.test(s);
export const procAborted = s => !!s && /aborted$/.test(s);
export const procSuccess = s => s === "reinstalled" || s === "reinstalled-updated" || s === "converted-bare" || s === "converted-docker" || s === "updated" || s === "uptodate";   // i18n-keys
export const isUpdateState = s => s === "updating" || s === "updated" || s === "update-failed" || s === "update-aborted" || s === "uptodate";   // the whole UPDATE lifecycle lives ONLY in the dh-ver pill, never as a proc-tag beside the node title   // i18n-keys
export const inProc      = s => !!s && !procFailed(s) && !procAborted(s) && !procSuccess(s);
// in-progress proc-tag colour by op — converting→purple, uninstalling→red, everything else active (re-installing /
// updating / installing) → yellow. (pending→blue and ready→green are handled by the turn/iface lifecycle classes.)
export const procInClass = s => s === "uninstalling" ? "procuninstall" : (s || "").startsWith("converting") ? "procconvert" : "procbusy";   // i18n-keys
export function procTag(state, onX, err, fresh) {
  const lbl = procLabel(state, fresh);
  if (procSuccess(state)) return html`<span class="nstat procok"><${Ic} i="check"/> ${lbl}</span>`;   // green, auto-clears (no ×)
  const xbtn = onX ? html`<button class="xbtn" title=${T("Dismiss — show the node's actual status")} onClick=${e => { e.stopPropagation(); e.preventDefault(); onX(e); }}><${Ic} i="x"/></button>` : null;
  if (procAborted(state)) return html`<span class="nstat procaborted"><${Ic} i="info"/> ${lbl}${xbtn}</span>`;
  if (procFailed(state)) {   // whole tag clickable → details popup (when there's a log tail), distinct hover, no caption
    const open = err ? (e => { e.stopPropagation(); e.preventDefault(); openConfirm({ title: lbl, log: err, confirmLabel: T("Close") }); }) : null;
    return html`<span class=${"nstat procfail" + (open ? " tg-click" : "")} onClick=${open}><${Ic} i="warn"/> ${lbl}${xbtn}</span>`;
  }
  return html`<span class=${"nstat " + procInClass(state)}><${Ic} i="clock"/> ${lbl}</span>`;   // in-progress (colour by op)
}
export function dismissNodeProc(id) {   // optimistic: drop the tag NOW, clear on the server in the background; re-poll only if it fails
  const n = (Store.nodes || []).find(x => x.id === id);
  if (n) { n.proc_status = null; n.proc_err = null; bus.emit(); }
  api.procClearNode(id).then(r => { if (r && r.ok === false) { toast(srvText(r) || T("Couldn't dismiss."), "err"); Store.poll(); } });
}
export function dismissHostProc() {   // optimistic
  Store.hostProc = null; Store.hostProcErr = null; bus.emit();
  api.procClearHost().then(r => { if (r && r.ok === false) { toast(srvText(r) || T("Couldn't dismiss."), "err"); Store.poll(); } });
}
export function Badge({ s, title }) {
  const ic = STATUS_ICON[s];
  // online → a glowing animated dot in the status colour (green), not a check — matches the turn badge
  if (s === "online") return html`<span class="badge b-online" title=${title || ""}><span class="sdot"></span>${statusLabel(s)}</span>`;
  return html`<span class=${"badge b-" + s + (ic ? " ic" : "")} title=${title || ""}>${ic ? html`<${Ic} i=${ic}/>` : null}${statusLabel(s)}</span>`;
}
// Access-lifecycle flag icon shown AFTER the status badge, but only when the badge doesn't already say it (i.e. the
// connectivity status — online / dangling / … — wasn't the neutral "ready" that the lifecycle overwrites). Red
// circle = blocked, red triangle = expired, orange triangle = about to expire. `it` = a reconciled peer or user.
export function lifecycleIcon(it, st) {
  if (!it) return null;
  st = st || it.status;
  if (it.disabled && st !== "disabled") return html`<span class="lc-ic lc-blocked" title=${T("status|Blocked")}><${Ic} i="off"/></span>`;
  if (it.expired && st !== "expired") return html`<span class="lc-ic lc-expired" title=${T("Access expired")}><${Ic} i="warn"/></span>`;
  if (it.expiring && st !== "expiring") return html`<span class="lc-ic lc-expiring" title=${T("About to expire")}><${Ic} i="warn"/></span>`;
  return null;
}

// inline metadata tag (protocol / interface / turn-proxy / generic) — the dense, colored
// row signature. iface tags take the node's colour via --tgc.
// the tags that describe a peer's deployment on a (node,iface): protocol + interface + turn-proxy.
// `muted` greys them out for inactive (offline / dangling / disconnected) rows.
// operator title of a turn-proxy (by service) on a node, if one was set — for the "Connected via" bubble
export function turnProxyTitle(node, service) {
  const tp = ((Store.stats[node] || {}).turn_proxies || []).find(x => x && x.service === service);
  return (tp && tp.title) || "";
}
// The interface badge for one peer-grid row (protocol + iface name).
export function gridIfaceTag(t) {
  return html`<${Tag} kind=${targetType(t)} label=${t.iface} muted=${!t.online}/>`;
}
// Status badge for a peer-grid row. A peer ONLINE through a turn-proxy takes the fork colour on its status
// badge with a glowing animated dot, plus a "Connected via <fork> <title>" hover bubble — consistent in
// every grid regardless of which columns are shown. Otherwise the normal Badge.
const STATUS_REASONS = once(() => ({
  blocked: blockedReason(null),
  faulty: T("connected, but no inbound data is flowing — likely a one-way block / DPI on the return path"),
  broken: T("the interface is up but this peer's IP is outside its subnet — the record needs correcting, not the interface"),
  disabled: T("access is blocked — removed from every server until unblocked"),
  expired: T("the access date has passed — removed from every server until the date is extended"),
  expiring: T("the access date is coming up — will be removed from every server when it passes"),
}));
export const statusReason = s => STATUS_REASONS()[s] || "";
// The blocked "wrong params" hint, naming the datapath the deployment runs (wg → Wireguard, awg → AmneziaWG,
// unknown → both) so it points at the right knobs. Mirrors the dynamic reason reconcile.js sets peer-wide.
// The protocol name is INTERPOLATED, not concatenated: it lands mid-sentence, and only one language puts it there.
export function protoLabel(type) { return type === "awg" ? "AmneziaWG" : type === "wg" ? "Wireguard" : T("Wireguard or AmneziaWG"); }
export function blockedReason(type) { return T("reaching the server but the handshake never completes — likely DPI / MTU / wrong {proto} params", { proto: protoLabel(type) }); }
export function gridStatusBadge(t, p, re) {
  const st = t.status || p.status;
  const reason = (t.down ? T("Interface {iface} is down — {why}", { iface: t.iface, why: t.down })
    : st === "blocked" ? blockedReason(t.type)   // name THIS deployment's datapath (wg / awg) in the "wrong params" hint
    : (p.reason || statusReason(st))) || "";
  if (t.online && t.viaTurn) {
    const tn = turnLabel(t.viaTurn), tc = turnColor(tn), ptitle = turnProxyTitle(t.node, t.viaTurn);
    return html`<span class="turnwrap">
      <span class="badge b-turn" style=${"--tfc:" + tc}><span class="sdot"></span>${statusLabel(st)}</span>
      <span class="turnbub">${T("Connected via")} <span class="tg tg-turn" style=${"--tfc:" + tc}>${tn}</span>${ptitle ? html` <b class="turnbub-t">${ptitle}</b>` : null}</span></span>`;
  }
  // A pinned action failure (e.g. "node hasn't reported <iface> yet") rides the status as a hover bubble —
  // not a persistent inline chip cluttering the row. Dismiss from inside the bubble.
  if (re) {
    return html`<span class="turnwrap">
      <${Badge} s=${st}/>
      <span class="turnbub statusbub err"><span class="statusbub-h" style="color:var(--dangling)"><${Ic} i="err"/>${T("Error")}</span>${re.msg}</span></span>`;
  }
  // Blocked / Faulty carry an explanation — show it in our own hover bubble (like the "Connected via" one) instead
  // of a native title, colour-headed with the status colour so the *why* reads at a glance.
  if ((st === "blocked" || st === "faulty") && reason) {
    const bc = "var(--fault)";
    return html`<span class="turnwrap">
      <${Badge} s=${st}/>
      <span class="turnbub statusbub"><span class="statusbub-h" style=${"color:" + bc}><${Ic} i="warn"/>${st === "blocked" ? "Restricted" : "Faulty"}</span>${reason}</span></span>`;
  }
  return html`<${Badge} s=${st} title=${reason}/>`;
}
// A status Badge that, for the states carrying an explanation (Restricted / Faulty), shows the SAME hover
// bubble as the peers grid — so the peer view modal's badges explain *why* on hover, not just a native title.
export function badgeWithReason(st, reason) {
  reason = reason || statusReason(st);
  if ((st === "blocked" || st === "faulty") && reason) {
    return html`<span class="turnwrap"><${Badge} s=${st}/>
      <span class="turnbub statusbub"><span class="statusbub-h" style="color:var(--fault)"><${Ic} i="warn"/>${st === "blocked" ? "Restricted" : "Faulty"}</span>${reason}</span></span>`;
  }
  return html`<${Badge} s=${st} title=${reason}/>`;
}
// Compact live-status dot for the connections monitor. Same turn language as the peer-grid status badge,
// scaled down to a single dot: online-via-turn → the fork-coloured glowing dot + "Connected via <fork>
// <title>" bubble; online (direct) → a green glowing dot; otherwise a neutral idle dot.
export function connDot(r) {
  if (r.online && r.viaTurn) {
    const tn = turnLabel(r.viaTurn), tc = turnColor(tn), ptitle = turnProxyTitle(r.node, r.viaTurn);
    return html`<span class="turnwrap">
      <span class="condot turn" style=${"--tfc:" + tc}></span>
      <span class="turnbub">${T("Connected via")} <span class="tg tg-turn" style=${"--tfc:" + tc}>${tn}</span>${ptitle ? html` <b class="turnbub-t">${ptitle}</b>` : null}</span></span>`;
  }
  return html`<span class=${"condot " + (r.online ? "on" : "off")} title=${r.online ? "online" : "idle"}></span>`;
}
// Endpoint cell for the live grids. A peer that came IN through a turn-proxy has its endpoint on the node's
// loopback (127.0.0.1) — the relay forwards locally — so instead of the bare IP show "turn-proxy" tinted with
// the fork colour + the same "Connected via <fork>" hover bubble the status dot uses.
//
// This holds once the peer goes OFFLINE too: wg keeps the last endpoint, so `via` is still "turn" and printing
// the raw 127.0.0.1 tells the operator nothing at all. Keep the attribution, dim it, and say "Last connected
// via". If the exact fork can no longer be resolved (the proxy was removed, or the node predates wg_sports) we
// still know it was relayed — say so rather than fall back to a loopback address.
export function endpointCell(t) {
  const obs = t.observed;
  if (t.via === "turn") {
    const tn = t.viaTurn ? turnLabel(t.viaTurn) : null;
    const tc = tn ? turnColor(tn) : "var(--dim)";
    const ptitle = t.viaTurn ? turnProxyTitle(t.node, t.viaTurn) : null;
    return html`<span class="turnwrap">
      <span class=${"addr turnep" + (t.online ? "" : " off")} style=${"color:" + (t.online ? tc : "var(--dim)")}>${T("turn-proxy")}</span>
      <span class="turnbub">${t.online ? T("Connected via") : T("Last connected via")} ${tn
          ? html`<span class="tg tg-turn" style=${"--tfc:" + tc}>${tn}</span>`
          : html`<span class="faint">${T("a turn-proxy")}</span>`}${ptitle ? html` <b class="turnbub-t">${ptitle}</b>` : null}</span></span>`;
  }
  return html`<span class="addr" title=${(obs && obs.endpoint) || ""}>${(obs && ipOf(obs.endpoint)) || "—"}</span>`;
}
// rate cell, green when traffic is flowing
// Throughput display perspective (Panel settings): node-reported rx/tx is from the NODE's view (rx=down,
// tx=up). "peers" flips it to the client's view — the peer's download is what the node uploads (tx), etc.
// dlul(rx, tx) returns [downValue, upValue] for whichever perspective is active. Numbers are unchanged;
// only which one is labelled ↓ vs ↑ swaps.
export const dlul = (rx, tx) => ((Store.panelSettings || {}).throughput_perspective === "peers") ? [tx || 0, rx || 0] : [rx || 0, tx || 0];
export function rateCell(rx, tx) {
  const live = (rx || 0) + (tx || 0) > 0; const [d, u] = dlul(rx, tx);
  return html`<span class=${"ratecell" + (live ? " live" : "")}>↓ ${rate(d)} <span class="up">↑ ${rate(u)}</span></span>`;
}
// cumulative transfer cell — same down/up colours as rateCell (green ↓ / blue ↑ once anything moved). Takes
// already perspective-adjusted down/up byte totals.
export function xferCell(db, ub) {
  const has = (db || 0) + (ub || 0) > 0;
  return html`<span class=${"addr xfer" + (has ? " live" : "")}>↓ ${fmtBytes(db)} <span class="up">↑ ${fmtBytes(ub)}</span></span>`;
}

// "+N" pill listing a peer's other deployments. Hover OR click opens a bubble (click pins it for
// touch); each row is server name · interface tag · right-aligned IP. The bubble is position:fixed
// (anchored to the pill's rect) so the table's overflow:hidden can't clip it.
export function DepBadge({ others }) {
  const [open, setOpen] = useState(false);     // hover preview
  const [pinned, setPinned] = useState(false); // click-pinned (mobile / sticky)
  const [pos, setPos] = useState(null);
  const ref = useRef(null);
  const closeT = useRef(null);
  const show = open || pinned;
  const cancelClose = () => clearTimeout(closeT.current);
  const scheduleClose = () => { cancelClose(); closeT.current = setTimeout(() => setOpen(false), 140); };
  const place = () => { const el = ref.current; if (!el) return; const r = el.getBoundingClientRect(); setPos({ left: Math.round(r.left), top: Math.round(r.bottom + 6) }); };
  useEffect(() => {
    if (!show) return; place();
    const onMove = () => place();
    const onDoc = e => { if (!(ref.current && ref.current.contains(e.target))) { setPinned(false); setOpen(false); } };
    window.addEventListener("scroll", onMove, true); window.addEventListener("resize", onMove);
    if (pinned) document.addEventListener("mousedown", onDoc, true);
    return () => { window.removeEventListener("scroll", onMove, true); window.removeEventListener("resize", onMove); document.removeEventListener("mousedown", onDoc, true); };
  }, [show, pinned]);
  useEffect(() => () => clearTimeout(closeT.current), []);
  return html`<span class=${"depmore" + (show ? " on" : "")} ref=${ref}
    onClick=${e => { e.stopPropagation(); setPinned(p => !p); }}
    onMouseEnter=${() => { cancelClose(); setOpen(true); }} onMouseLeave=${scheduleClose}>+${others.length}
    ${show && pos ? html`<div class="deppop" style=${"left:" + pos.left + "px;top:" + pos.top + "px"}
      onClick=${e => e.stopPropagation()} onMouseEnter=${cancelClose} onMouseLeave=${scheduleClose}>
      ${others.map(d => html`<div class="deprow" key=${tkey(d.node, d.iface)}>
        <span class="dep-name" style=${"color:" + (Store.nodeColor(d.node) || "var(--ink)")}>${Store.nodeName(d.node)}</span>
        <${Tag} kind=${targetType(d)} label=${d.iface} muted=${!d.online}/>
        <span class="dep-ip addr">${d.ip || "—"}</span></div>`)}
    </div>` : null}
  </span>`;
}

// small ⓘ next to a pending/failed command — hover for the node's error, click to read it in full.
// `cls` tones it (e.g. "warn" = yellow for a non-fatal in-progress note); `title` overrides the modal heading.
export function CmdErr({ err, cls, title }) {
  if (!err) return null;   // clickable error icon → details popup (no native tooltip caption)
  return html`<span class=${"cmderr" + (cls ? " " + cls : "")} onClick=${e => { e.stopPropagation(); openConfirm({ title: title || T("Command failed on the node"), log: err, confirmLabel: T("Close") }); }}><${Ic} i="info"/></span>`;
}
// a status tag that, when it carries a node `msg`, makes the WHOLE tag clickable (opens the message) with
// a hover highlight + pointer — so the click target is the tag, not a tiny icon next to it.
export function StatusTag({ cls, icon, label, msg, title }) {
  const ic = icon ? html`<${Ic} i=${icon}/>` : null;
  if (!msg) return html`<span class=${cls} title=${title || ""}>${ic}${label}</span>`;   // plain (non-error) tag keeps its hint
  // an error/detail tag: the WHOLE tag is clickable (→ popup), distinct hover, no native caption
  return html`<span class=${cls + " tg-click"}
    onClick=${e => { e.stopPropagation(); openConfirm({ title: title || T("Details"), log: msg, confirmLabel: T("Close") }); }}>${ic}${label}</span>`;
}

// ───────────────────────── form controls ─────────────────────────
// The app-wide on/off switch (34×19). Used for every enable/disable toggle in Settings.
export const Switch = ({ on, onChange, title, disabled }) => html`<label class=${"swt" + (disabled ? " swt-off" : "")} title=${title || ""}>
  <input type="checkbox" checked=${!!on} disabled=${!!disabled} onChange=${e => onChange(e.target.checked)}/><span class="track"></span><span class="knob"></span></label>`;
// Reusable styled dropdown — a drop-in for a native <select> so every dropdown in the app shares one look (the
// OS-rendered <select> option list can't be styled, hence this). `options` is a flat [{value,label,disabled}] or
// grouped [{group,items:[…]}]. `short(label)` optionally shortens the CLOSED label (e.g. cut at a comma).
export function Dropdown({ value, onChange, options, className, placeholder, disabled, short }) {
  const [open, setOpen] = useState(false), [pos, setPos] = useState(null);
  const ref = useRef(null), popRef = useRef(null);
  const flat = (options || []).flatMap(o => o.items ? o.items : [o]);
  const cur = flat.find(o => String(o.value) === String(value));
  const curLabel = cur ? (short ? short(cur.label) : cur.label) : (placeholder || "");
  const place = () => { const el = ref.current; if (!el) return; const r = el.getBoundingClientRect();
    const below = window.innerHeight - r.bottom - 12, above = r.top - 12; const flip = below < 240 && above > below;
    setPos({ left: Math.round(r.left), top: Math.round(flip ? r.top - 4 : r.bottom + 4), width: Math.round(r.width), flip, maxh: Math.max(180, Math.round(flip ? above : below) - 16) }); };
  useEffect(() => { if (!open) return; place();
    const onMove = () => place();
    const onDoc = e => { const t = e.target; if (!((ref.current && ref.current.contains(t)) || (popRef.current && popRef.current.contains(t)))) setOpen(false); };
    const onKey = e => { if (e.key === "Escape") { setOpen(false); blurActive(); } };
    window.addEventListener("scroll", onMove, true); window.addEventListener("resize", onMove);
    document.addEventListener("mousedown", onDoc, true); document.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("scroll", onMove, true); window.removeEventListener("resize", onMove); document.removeEventListener("mousedown", onDoc, true); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const opt = o => html`<button type="button" disabled=${o.disabled} class=${"ddopt" + (String(o.value) === String(value) ? " sel" : "") + (o.disabled ? " off" : "")}
    onClick=${() => { if (o.disabled) return; onChange(o.value); setOpen(false); }}>${o.label}</button>`;
  return html`<div class=${"dropdown " + (className || "")} ref=${ref}>
    <button type="button" class=${"ddbtn" + (open ? " on" : "")} disabled=${disabled} onClick=${() => !disabled && setOpen(o => !o)}>
      <span class="ddlbl">${curLabel}</span><span class="catpick-caret">▾</span></button>
    ${open && pos ? html`<${Portal}><div ref=${popRef} class=${"ddpop" + (pos.flip ? " flip" : "")} style=${"left:" + pos.left + "px;top:" + pos.top + "px;min-width:" + pos.width + "px;--ddmaxh:" + pos.maxh + "px"}>
      ${(options || []).map(o => o.items ? html`<div class="ddgrp">${o.group}</div>${o.items.map(opt)}` : opt(o))}
    </div><//>` : null}
  </div>`;
}
// grow a textarea to fit its content (starts at one row like a textbox, expands as lines wrap)
export const autoGrow = el => { if (!el) return; el.style.height = "auto"; el.style.height = el.scrollHeight + "px"; };
// Reusable collapsible section (interface + turn-proxy modals): a full-width header (caret · title · right-aligned
// summary) with the body shown only when open. Controlled — parent owns the `open` boolean + `onToggle`. `summary`
// is optional JSX/text; `sumCls` ("on" → green count, "route" → rose count) tints a <b> inside it.
export function Disclosure({ title, summary, sumCls, open, onToggle, children }) {
  return html`<${Fragment}>
    <button type="button" class=${"disc" + (open ? " open" : "")} onClick=${onToggle}>
      <span class="disc-car">▸</span><span class="disc-t">${title}</span>
      ${summary != null ? html`<span class=${"disc-sum" + (sumCls ? " " + sumCls : "")}>${summary}</span>` : null}
    </button>
    ${open ? html`<div class="disc-body">${children}</div>` : null}
  <//>`;
}

// dropdown of a node's known IPs + a trailing free-text "Custom IP / Host…". Shared by the interface
// endpoint field and the turn-proxy listen-IP field so they look/behave identically. Parent owns the
// sel/custom state; resolve the chosen value with ipPickerVal(sel, custom).
export function IpPicker({ ips, sel, setSel, custom, setCustom, placeholder }) {
  return html`<${Fragment}>
    <${Dropdown} value=${sel} onChange=${v => setSel(v)} options=${[
      ...(ips || []).filter(ip => !isPrivIp(ip)).map(ip => ({ value: ip, label: ip })),
      { value: "__custom__", label: T("Custom IP / Host…") }]}/>
    ${sel === "__custom__" ? html`<input style="margin-top:6px" value=${custom} onInput=${e => setCustom(e.target.value)} placeholder=${placeholder || "203.0.113.7"} autocomplete="off"/>` : null}
  <//>`;
}

// ── interface/WDTT op lifecycle: the same optimistic badge treatment nodes get ───────────────────
export function trackIfaceOps() {
  const now = Date.now();
  for (const key of Object.keys(Store.ifaceOp)) {
    const op = Store.ifaceOp[key];
    if (op.phase !== "busy") { if (op.until && now > op.until) delete Store.ifaceOp[key]; continue; }
    if (IFOP_PANEL.has(op.verb)) continue;   // panel-side: settled by its own handler, not by watching the node
    const cut = key.indexOf("|"); const node = key.slice(0, cut), iface = key.slice(cut + 1);
    const nrec = (Store.nodes || []).find(n => n.id === node) || {};
    const _wSnap = ((Store.stats[node] || {}).wdtt || []).find(w => w && w.iface === iface);   // WDTT lives in snap.wdtt, not snap.interfaces
    const istate = _wSnap
      ? { down: _wSnap.active !== "active" && !_wSnap.stopped, stopped: !!_wSnap.stopped }   // active state from the WDTT readback
      : (((Store.stats[node] || {}).interfaces || {})[iface] || {});
    const down = !!istate.down, stopped = !!istate.stopped, notup = down || stopped;   // a stopped iface reports `stopped`, not `down`
    const cerr = (nrec.cmd_errors || {})[iface];
    const starting = (nrec.starting || []).includes(iface);   // panel requests still queued (cleared once the snapshot reflects)
    const stopping = (nrec.stopping || []).includes(iface);
    const restarting = (nrec.restarting || []).includes(iface);
    let done = null;   // { phase, err }
    if (op.verb === "apply") {                                 // up iface live-apply (no restart) → time-based
      if (cerr && now - op.started > 4000) done = { phase: "fail", err: cerr };
      else if (now - op.started > 6000) done = { phase: "ok" };   // node has had a sync to pick it up
    } else if (op.verb === "start") {                          // success once the iface is actually UP (not just "not down")
      if (!notup) done = { phase: "ok" };
      else if (cerr && now - op.started > 4000) done = { phase: "fail", err: cerr };
      else if (!starting && now - op.started > 8000) done = { phase: "fail", err: cerr || T("the interface didn't come up") };
      else if (now - op.started > 20000) done = { phase: "fail", err: cerr || T("timed out") };
    } else if (op.verb === "stop") {                           // success once it's actually down/stopped
      if (notup) done = { phase: "ok" };
      else if (cerr && now - op.started > 4000) done = { phase: "fail", err: cerr };
      else if (!stopping && now - op.started > 8000) done = { phase: "fail", err: cerr || T("the interface didn't stop") };
      else if (now - op.started > 20000) done = { phase: "fail", err: cerr || T("timed out") };
    } else {                                                   // RESTART of an up iface → done when the request clears + it's up
      if (down && cerr) done = { phase: "fail", err: cerr };
      else if (!restarting && now - op.started > 6000) done = down ? { phase: "fail", err: cerr || T("didn't come back up") } : { phase: "ok" };
      else if (now - op.started > 18000) done = down ? { phase: "fail", err: cerr || T("didn't come back up") } : { phase: "ok" };
    }
    if (done) {
      const ms = done.phase === "ok" ? 5000 : 10000;
      Store.ifaceOp[key] = { verb: op.verb, phase: done.phase, until: now + ms, err: done.err || "" };
      setTimeout(() => Store.apply(), 0);        // re-render NOW so the done tag shows on the current screen
      setTimeout(() => Store.apply(), ms + 100); // and again to clear it when it expires
    }
  }
}

// WDTT lifecycle — same optimistic op badge as a normal interface. start/stop ride the `stopped` flag (the node
// enable/disable-s the swg-wdtt service); restart is a nonce the node picks up (systemctl restart). trackIfaceOps
// drives the badge, reading the WDTT snapshot's active state (not snap.interfaces).
export async function startOrRestartWdtt(node, iface, verb) {
  const key = node + "|" + iface;
  Store.ifaceOp[key] = { verb, phase: "busy", started: Date.now() }; Store.apply();
  const body = { node, iface };
  if (verb === "stop") body.stopped = true;
  else if (verb === "start") body.stopped = false;
  else body.restart = Date.now();   // restart nonce → node systemctl restart
  const r = await api.wdttSet(body);
  if (!r.ok) {
    Store.ifaceOp[key] = { verb, phase: "fail", until: Date.now() + 10000, err: srvText(r) || T("request failed") };
    Store.apply(); setTimeout(() => Store.apply(), 10100); return;
  }
  await Store.poll();
}

export async function startOrRestartCsqtt(node, iface, verb) {
  const key = node + "|" + iface;
  Store.ifaceOp[key] = { verb, phase: "busy", started: Date.now() }; Store.apply();
  const body = { node, iface };
  if (verb === "stop") body.stopped = true;
  else if (verb === "start") body.stopped = false;
  else body.restart = Date.now();   // restart nonce → node systemctl restart
  const r = await api.csqttSet(body);
  if (!r.ok) {
    Store.ifaceOp[key] = { verb, phase: "fail", until: Date.now() + 10000, err: srvText(r) || T("request failed") };
    Store.apply(); setTimeout(() => Store.apply(), 10100); return;
  }
  await Store.poll();
}

// pinned, explained failure for a row's last action; dismissable
export function RowError({ k }) {
  const e = rowError(k);
  if (!e) return null;
  return html`<span class="rowerr" title=${e.msg}><${Ic} i="err"/> ${e.msg}<button class="rowerr-x" onClick=${() => dismissError(k)}>×</button></span>`;
}

// dropdown of the node's internet IPs (already excludes wg/awg/swg/docker) + an Auto option; keeps a
// current custom value (e.g. a hostname ingress) selectable even if it isn't in the reported IP list.
// IP picker: only the node's PUBLIC (internet-routable) IPs are listed; internal/private IPs are hidden.
// A "Use custom IP…" entry reveals a free-text field for any address not in the list (also how an already-set
// private/custom value is shown — preserved, editable). value "" = the Auto option.
export function NodeIpPick({ ips, value, onChange, auto, customPlaceholder, disabled }) {
  const pub = (ips || []).filter(ip => !isPrivIp(ip));
  const valIsCustom = !!value && !pub.includes(value);
  const [custom, setCustom] = useState(valIsCustom);
  const sel = (custom || valIsCustom) ? "__custom__" : (value || "");
  const onSel = v => { if (v === "__custom__") setCustom(true); else { setCustom(false); onChange(v); } };
  return html`<${Fragment}>
    <${Dropdown} value=${sel} onChange=${onSel} disabled=${disabled} options=${[
      { value: "", label: auto },
      ...pub.map(ip => ({ value: ip, label: ip })),
      { value: "__custom__", label: T("Use custom…") }]}/>
    ${sel === "__custom__" ? html`<input class="ipk-custom" placeholder=${customPlaceholder || T("Custom IP — e.g. 203.0.113.5")} value=${value || ""} onInput=${e => onChange(e.target.value)} disabled=${disabled} spellcheck="false" autocomplete="off"/>` : null}
  </${Fragment}>`;
}

// interface op flashes — the iface twins of the turn* maps, read by the node cards
export const ifaceReady = {};         // "node|iface"   -> expiry ts for the green "ready" flash (5s after an interface comes up)
export const ifaceWasBusy = {};       // "node|iface"   -> was it pending/creating last render

// A label-less pair of colour pickers — DARK then LIGHT — for one themed colour. Hovering a swatch pops a preview
// of `sample(colour)` on that mode's real backdrop, so you see how it reads in that theme before committing. `val`
// is {dark,light} (a legacy string is accepted and shown for both); onChange receives the whole updated object.
export function ThemedSwatch({ val, onChange, sample, title }) {
  const v = (val && typeof val === "object") ? val : { dark: val || "", light: val || "" };
  const cell = mode => html`<span class="tsw">
    <input type="color" class="tf-color" value=${v[mode]}
      title=${(title ? title + " · " : "") + (mode === "dark" ? T("Dark theme") : T("Light theme"))}
      onInput=${e => onChange({ ...v, [mode]: e.target.value })}/>
    ${/* the CLASS keeps the raw mode (it selects the backdrop); only the caption is spelled out, and as
          two literal keys rather than T(mode) so the extractor can see them */""}
    <span class=${"tsw-bub tsw-" + mode}>${sample(v[mode], mode)}
      <span class="tsw-cap">${mode === "dark" ? T("theme|dark") : T("theme|light")}</span></span>
  </span>`;
  return html`<span class="tswrow">${cell("dark")}${cell("light")}</span>`;
}

// A type-to-filter user picker (the "assign to" control for unassigned peers).
// Anchored-dropdown positioning: a fixed-position list at the trigger's rect so it escapes a grid/table's
// overflow:hidden (and any stacking context) — the list is PORTALED to <body>. Returns refs + pos; the
// caller renders <Portal> with the list and wires close-on-outside via the returned handlers.
export function useAnchoredList(open, setOpen, deps) {
  const wrapRef = useRef(null), listRef = useRef(null);
  const [pos, setPos] = useState(null);
  const place = () => { const el = wrapRef.current; if (!el) return; const r = el.getBoundingClientRect();
    setPos({ left: Math.round(r.left), top: Math.round(r.bottom + 4), width: Math.round(r.width) }); };
  useEffect(() => {
    if (!open) { setPos(null); return; }
    place();
    const onMove = () => place();
    const onDoc = e => { const t = e.target;   // close when the click is outside BOTH the input and the portaled list
      if (!((wrapRef.current && wrapRef.current.contains(t)) || (listRef.current && listRef.current.contains(t)))) setOpen(false); };
    window.addEventListener("scroll", onMove, true); window.addEventListener("resize", onMove);
    document.addEventListener("mousedown", onDoc, true);
    return () => { window.removeEventListener("scroll", onMove, true); window.removeEventListener("resize", onMove); document.removeEventListener("mousedown", onDoc, true); };
  }, [open, ...(deps || [])]);
  return { wrapRef, listRef, pos, popStyle: pos ? ("left:" + pos.left + "px;top:" + pos.top + "px;min-width:" + pos.width + "px") : "" };
}

// ── theme appliers: they read Store and paint the document, so they sit above theme.js ──
// Drive EVERY `.tf-<fork>` element (the .tg-turn tags + .iftype.turn badges scattered across the SPA) from the
// picker override — those use a static CSS class, so without this the colour picker would only reach the handful of
// inline-styled sites. One injected <style> keeps the whole app in sync with turn_fork_colors after each poll.
export function applyForkColors() {
  let el = document.getElementById("tf-colors");
  if (!el) { el = document.createElement("style"); el.id = "tf-colors"; (document.head || document.documentElement).appendChild(el); }
  el.textContent = turnForkList().map(f => ".tf-" + f.id + "{--tfc:" + turnColor(f.id) + "}").join("");
}
// ---- palette overrides (Panel settings → Interfaces / Display) ----
// Interface protocol colours (wg / awg), peer-health colours (blocked / faulty) and the brand/theme colour
// are all operator-tunable. A Panel-settings override wins over these built-in defaults; nothing is hardcoded
// at the render sites — the wg/awg/blocked/faulty CSS classes and the --brand custom property are driven from
// here via applyThemeColors() after every poll, exactly like applyForkColors() does for the turn tags.
// Every operator-tunable colour carries a value PER light/dark mode ({dark,light}); the active mode's value is
// resolved by pickThemed(). Nothing is hardcoded at the render sites — the wg/awg CSS classes and the --brand
// property are injected by applyThemeColors() after every poll, exactly like applyForkColors() does for the tags.
export function ifaceColor(type) {
  const t = (type || "").toLowerCase();
  const ov = (Store.panelSettings && Store.panelSettings.iface_colors) || {};
  const k = t === "awg" ? "awg" : t === "wdtt" ? "wdtt" : t === "csqtt" ? "csqtt" : "wg";   // WDTT + csqtt (keyless proxy targets) are operator-tunable too
  return pickThemed(ov[k], IFACE_COLOR_DEFAULTS[k].dark, IFACE_COLOR_DEFAULTS[k].light);
}
// perceived brightness (0–1) of a #rrggbb / #rgb colour — used to pick a contrasting ink for text on the brand.
// the brand accent for the ACTIVE light/dark mode — each mode has its own picker (else its built-in default).
export function themeColor() {
  const ps = Store.panelSettings || {};
  return resolvedTheme() === "light" ? (ps.theme_color_light || THEME_COLOR_LIGHT_DEFAULT)
                                     : (ps.theme_color || THEME_COLOR_DEFAULT);
}
// Drive the whole palette from the picker overrides: set --brand (and its lighter/chart siblings) on <html> so
// every var(--brand) site follows the theme colour, and inject one <style> overriding the static wg/awg/blocked/
// faulty classes (they don't read a custom property, so like the turn tags they need an explicit rule).
let _themeSig = null;
export function applyThemeColors() {
  const theme = themeColor(), wg = ifaceColor("wg"), awg = ifaceColor("awg"), wdtt = ifaceColor("wdtt"), csqtt = ifaceColor("csqtt");
  const sig = [resolvedTheme(), theme, wg, awg, wdtt, csqtt].join("|");
  if (sig === _themeSig) return;   // nothing changed since last poll → skip the DOM write
  _themeSig = sig;
  const de = document.documentElement, cm = (c, p, m) => "color-mix(in srgb, " + c + " " + p + "%, " + m + ")";
  const brand = clampBrand(theme, resolvedTheme() === "light");   // legible against the active background
  de.style.setProperty("--brand", brand);
  de.style.setProperty("--brand-2", cm(brand, 70, "#fff"));   // the lighter brand accent
  de.style.setProperty("--tp-rx", brand);                      // throughput chart "down" series tracks the theme
  // text sitting ON the brand colour (primary buttons) must contrast with whatever colour was applied — dark ink on a
  // light brand, light ink on a dark one — so a dark theme colour doesn't make the button label invisible.
  de.style.setProperty("--brand-ink", hexLum(brand) > 0.55 ? "#04232A" : "#EAFBFF");
  let el = document.getElementById("theme-colors");
  if (!el) { el = document.createElement("style"); el.id = "theme-colors"; (document.head || document.documentElement).appendChild(el); }
  el.textContent =
    ".iftype.wg,.tg-wg{background:" + cm(wg, 14, "transparent") + ";color:" + wg + "}" +
    ".iftype.awg,.tg-awg{background:" + cm(awg, 15, "transparent") + ";color:" + awg + "}" +
    ".iftype.wdtt,.tg-wdtt{background:" + cm(wdtt, 15, "transparent") + ";color:" + wdtt + "}" +
    ".iftype.csqtt,.tg-csqtt{background:" + cm(csqtt, 15, "transparent") + ";color:" + csqtt + "}" +
    // the create-interface Protocol chips track the SAME configured type colours (selected state only)
    ".chip.c-wg.on{color:" + wg + ";border-color:" + wg + ";background:" + cm(wg, 15, "transparent") + "}" +
    ".chip.c-awg.on{color:" + awg + ";border-color:" + awg + ";background:" + cm(awg, 15, "transparent") + "}" +
    ".chip.c-wdtt.on{color:" + wdtt + ";border-color:" + wdtt + ";background:" + cm(wdtt, 15, "transparent") + "}" +
    ".chip.c-csqtt.on{color:" + csqtt + ";border-color:" + csqtt + ";background:" + cm(csqtt, 15, "transparent") + "}";
  applyFavicon(theme);
}
// Rebuild the browser-tab favicon (the indicator-LED mark) in the ACTIVE mode's accent colour, with a
// mode-matched centre so it reads on either tab background. Regenerated whenever the theme colour or mode
// changes (called from applyThemeColors, which fires exactly on those changes).
export function applyFavicon(accent) {
  const centre = resolvedTheme() === "light" ? "#FFFFFF" : "#0A0E15";
  const svg = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    + "<rect width='32' height='32' rx='8' fill='" + accent + "'/>"
    + "<circle cx='16' cy='14.5' r='5.5' fill='" + centre + "'/></svg>";
  let link = document.querySelector("link[rel~='icon']");
  if (!link) { link = document.createElement("link"); link.rel = "icon"; (document.head || document.documentElement).appendChild(link); }
  link.setAttribute("href", "data:image/svg+xml," + encodeURIComponent(svg));
}
// ---- light / dark / auto ----
// The header switch cycles auto → light → dark. "auto" follows the OS. The resolved mode drives
// <html data-theme>, which flips the structural palette (app.css :root[data-theme=light]); the brand
// accent is then re-injected per mode by applyThemeColors(). Persisted in localStorage so it survives reloads;
// an inline <head> script in index.html sets data-theme before first paint so there's no dark→light flash.
export function applyThemeMode() {
  document.documentElement.dataset.theme = resolvedTheme();
  _themeSig = null;            // force the accent injection to re-pick this mode's brand colour
  applyThemeColors();
  applyForkColors();           // turn-fork tints are per-mode too
}
export function setThemeMode(mode) { try { localStorage.setItem("swg-theme", mode); } catch (_) {} applyThemeMode(); const b = document.getElementById("theme-btn"); if (b) paintThemeBtn(b); }
export function cycleThemeMode() { const i = THEME_MODES.indexOf(themeMode()); setThemeMode(THEME_MODES[(i + 1) % THEME_MODES.length]); }
export const THEME_ICON = {   // inline SVGs — the button shows the CURRENT mode. auto = the "contrast" glyph (a circle with one
  // half filled), the widely-used convention (GitHub et al.) for "follows the system" — clearer than a monitor.
  light: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4.2"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`,
  dark: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>`,
  auto: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none"/></svg>`,
};
// The language switch: a two-letter code, cycling through the available languages. Deliberately a plain
// cycle rather than a dropdown — with two languages a menu is more chrome than choice, and setLang()
// reloads anyway (every module reads T() at render time, so there is nothing to re-render in place).
export function paintLangBtn(b) {
  if (!b) return;
  // The button shows the language you SWITCH TO, not the one you are in: in English it reads «РУ», in
  // Russian "EN". A control that names the current state leaves you guessing what pressing it does.
  const next = nextLang();
  const row = LANGS.find(([c]) => c === next) || [];
  b.textContent = row[2] || next.toUpperCase();
  b.title = T("Switch to {name}", { name: row[1] || next });
  b.setAttribute("aria-label", b.title);
}
export function cycleLang() {
  const codes = LANGS.map(([c]) => c);
  setLang(codes[(codes.indexOf(lang()) + 1) % codes.length]);
}

export function paintThemeBtn(b) {
  const m = themeMode();
  b.innerHTML = THEME_ICON[m];
  b.title = m === "auto" ? T("Theme: Auto (follows your system) — click for Light")
    : m === "light" ? T("Theme: Light — click for Dark") : T("Theme: Dark — click for Auto");
}

export function StoreOffBanner() {
  if (Store.storeConfigs) return null;
  const docker = !!(Store.env && Store.env.docker);
  const fp = (Store.env && Store.env.fleet_path) || "/etc/swg-panel/fleet.json";
  const sed = `sed -i -E 's/("store_configs":[[:space:]]*)false/\\1true/' ${fp}`;
  const cmd = docker
    ? `docker exec swg-panel ${sed} && docker restart swg-panel`
    : `sudo ${sed} && sudo systemctl restart swg-panel-server`;
  return html`<div class="banner warn"><${Ic} i="warn"/><div class="banner-body">
    <b>${T("Config storage is off.")}</b> ${T("Client configs (with their private keys) aren't kept on the panel, so QR codes and downloads only work right after a peer is created — existing peers can't be re-shared. Run this on the {host} to enable it (existing peers then need a one-time Rotate-keys to capture a config):",
      { host: docker ? T("Docker host") : T("panel host") })}
    <div class="cmdrow"><div class="tokenbox">${cmd}</div><button class="copyaction" onClick=${() => copy(cmd, T("Command copied"))}><${Ic} i="copy"/> ${T("Copy")}</button></div>
  </div></div>`;
}
