// DofusPetMerch - sincronización de la tabla XP de mascotas.
// 1) Pega este código en la hoja: Extensiones > Apps Script (sustituye todo).
// 2) Cambia TOKEN por una palabra secreta y ponla también en DofusPetMerch.
// 3) Implementar > Nueva implementación > Tipo: Aplicación web
//    Ejecutar como: Yo  ·  Quién tiene acceso: Cualquier usuario  > Implementar (autoriza).
// 4) Copia la URL que termina en /exec y pégala en DofusPetMerch.
// Si cambias este código: Implementar > Gestionar implementaciones > Editar > Nueva versión.
//
// La pestaña XP puede tener o no cabecera, columnas en cualquier orden y columnas extra
// (se respetan). Cabeceras reconocidas: Objeto/obj/nombre/item... y XP/exp/experiencia...
// En la primera sincronización se añade la cabecera (si falta) y la columna "Actualizado".
const TOKEN = 'cambia-esto';
const SHEET = 'XP';
const TOMBS = '_borrados';
const TOMB_TTL_DAYS = 90;
// Mismas listas que en DofusPetMerch (sheets/layout.py), salvo TS_ALIASES. Una sola línea cada una.
const NAME_ALIASES = ["objeto", "objet", "object", "item", "items", "nombre", "name", "nom", "articulo", "recurso", "ressource", "resource", "alimento", "comida", "ingrediente", "producto"];
const NAME_PREFIXES = ["obj", "nomb", "item", "artic", "recur", "ress", "alim"];
const XP_TOKENS = ["xp", "pex"];
const XP_PREFIXES = ["exp"];
const TS_ALIASES = ["actualizado", "updated", "update", "modificado", "timestamp", "ts"];
const HEADER_SEARCH_ROWS = 5;
const GUESS_SAMPLE_ROWS = 20;

function norm_(s) { return String(s).normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, ' ').trim().toLowerCase(); }
function out_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
const WS_RE = /^[ \t\n\r\f\v    ﻿]+|[ \t\n\r\f\v    ﻿]+$/g;
function cell_(row, j) { const c = row[j]; return (c === undefined || c === null || c instanceof Date) ? '' : String(c).replace(WS_RE, ''); }
function toks_(c) { return norm_(c).replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(Boolean); }
function isName_(c) { const t = toks_(c); if (!t.length) return false;
  return NAME_ALIASES.indexOf(t[0]) >= 0 || NAME_ALIASES.indexOf(t.join(' ')) >= 0 || NAME_PREFIXES.some(p => t[0].indexOf(p) === 0); }
function isXp_(c) { return toks_(c).some(x => XP_TOKENS.indexOf(x) >= 0 || XP_PREFIXES.some(p => x.indexOf(p) === 0)); }
function isTs_(c) { const t = toks_(c); return t.length > 0 && TS_ALIASES.indexOf(t[0]) >= 0; }
// Number as typed in Spanish ("20.000", "0,5") or a real number cell.
function num_(v) {
  if (typeof v === 'number') return isFinite(v) ? v : null;
  let s = String(v === undefined || v === null || v instanceof Date ? '' : v).replace(/[ \t\n\r\f\v    ﻿]/g, '');
  if (s.indexOf(',') >= 0 && s.indexOf('.') >= 0 && s.lastIndexOf('.') > s.lastIndexOf(',')) s = s.replace(/,/g, '');
  else if (s.indexOf(',') >= 0) s = s.replace(/\./g, '').replace(/,/g, '.');
  else if (/^-?[1-9][0-9]{0,2}(\.[0-9]{3})+$/.test(s)) s = s.replace(/\./g, '');
  if (!/^-?([0-9]+(\.[0-9]*)?|\.[0-9]+)$/.test(s)) return null;
  return Number(s);
}
function numText_(c) { return num_(c) !== null; }
// Cell as seen by the layout guess: dates count as empty.
function lcell_(row, j) { const c = cell_(row, j); return /^[0-9]{1,4}[\/.-][0-9]{1,2}[\/.-][0-9]{1,4}([ T].*)?$/.test(c) ? '' : c; }
function xpv_(v) { const n = num_(v); return n !== null && n > 0 ? n : null; }

// An old header left as data (same as looks_like_header in DofusPetMerch): never an item.
function looksLikeHeader_(row, nameCol) {
  if (NAME_ALIASES.indexOf(toks_(cell_(row, nameCol)).join(' ')) < 0) return false;
  return row.some((c, j) => j !== nameCol && isXp_(cell_(row, j)));
}
// Rows under a candidate header agree with it: nobody has a valid XP yet, or some row
// has one in column x (same as _xp_column_fits in DofusPetMerch).
function xpFits_(below, x) {
  const data = below.filter(r => r.some((c, j) => cell_(r, j) !== '')).slice(0, GUESS_SAMPLE_ROWS);
  const anyXp = data.some(r => r.some((c, j) => xpv_(cell_(r, j)) !== null));
  return !anyXp || data.some(r => xpv_(cell_(r, x)) !== null);
}

// Same rules as detect_layout() in DofusPetMerch. Returns 0-based columns and rows.
function layout_(v) {
  for (let i = 0; i < Math.min(HEADER_SEARCH_ROWS, v.length); i++) {
    const row = v[i]; let n = -1, x = -1, t = -1;
    for (let j = 0; j < row.length; j++) if (n < 0 && isName_(cell_(row, j))) n = j;
    for (let j = 0; j < row.length; j++) if (x < 0 && j !== n && isXp_(cell_(row, j))) x = j;
    if (n < 0 || x < 0) continue;
    // Same rule as detect_layout(): no number between name and XP; a number elsewhere only if
    // the rows below agree with that XP column.
    const lo = Math.min(n, x), hi = Math.max(n, x);
    let numInSpan = false, numOutside = false;
    for (let j = 0; j < row.length; j++) if (numText_(cell_(row, j))) { if (j >= lo && j <= hi) numInSpan = true; else numOutside = true; }
    if (!numInSpan && (!numOutside || xpFits_(v.slice(i + 1), x))) {
      for (let j = 0; j < row.length; j++) if (t < 0 && j !== n && j !== x && isTs_(cell_(row, j))) t = j;
      return { name: n, xp: x, ts: t, header: i, start: i + 1, alias: true, ambiguous: false };
    }
  }
  const sample = [];
  for (let i = 0; i < v.length && sample.length < GUESS_SAMPLE_ROWS; i++)
    if (v[i].some((c, j) => lcell_(v[i], j) !== '')) sample.push(i);
  let ncols = 0; sample.forEach(i => { ncols = Math.max(ncols, v[i].length); });
  if (ncols < 2) return { name: 0, xp: 1, ts: -1, header: -1, start: 0, alias: false, ambiguous: false };
  let xp = 1, best = -1, numericCols = 0;
  for (let j = 0; j < ncols; j++) {
    let ne = 0, ok = 0;
    sample.forEach(i => { const c = lcell_(v[i], j); if (c !== '') { ne++; if (xpv_(c) !== null) ok++; } });
    const share = ne ? ok / ne : 0;
    if (share >= 0.5) { numericCols++; if (share > best) { xp = j; best = share; } }
  }
  let name = -1;
  for (let j = 0; j < ncols && name < 0; j++) {
    if (j === xp) continue;
    let ne = 0, txt = 0;
    sample.forEach(i => { const c = lcell_(v[i], j); if (c !== '') { ne++; if (num_(c) === null) txt++; } });
    if (ne && txt / ne > 0.5) name = j;
  }
  if (name < 0) name = xp === 0 ? 1 : 0;
  const ambiguous = numericCols > 1;
  const f = sample[0], head = v[f];
  // Unknown labels ("Cosa | Valor"): the XP cell is text, not a number (so "Gobio | 0" is data).
  if (lcell_(head, name) && lcell_(head, xp) && num_(lcell_(head, xp)) === null &&
      sample.slice(1).some(i => lcell_(v[i], name) && xpv_(lcell_(v[i], xp)) !== null))
    return { name: name, xp: xp, ts: -1, header: f, start: f + 1, alias: false, ambiguous: ambiguous };
  return { name: name, xp: xp, ts: -1, header: -1, start: 0, alias: false, ambiguous: ambiguous };
}

function sheet_(name, header) {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(name);
  if (!sh) { sh = ss.insertSheet(name); sh.appendRow(header); }
  return sh;
}
function xp_() { return sheet_(SHEET, ['Objeto', 'XP', 'Actualizado']); }
function tb_() { return sheet_(TOMBS, ['Objeto', 'Borrado']); }

// Only under the lock (doPost). Never overwrites the user's cells: when the tab has no
// recognised header it INSERTS a new header row (above the first row, or above the unknown
// labels), and the "Actualizado" column goes after the last used column.
function ensureLayout_(sh) {
  const v = sh.getDataRange().getValues();
  if (!v.some(r => r.some((c, j) => cell_(r, j) !== ''))) {
    sh.getRange(1, 1, 1, 3).setValues([['Objeto', 'XP', 'Actualizado']]);
    return layout_(sh.getDataRange().getValues());
  }
  const L = layout_(v);
  if (L.ambiguous) throw new Error('layout');
  if (L.alias && L.ts >= 0) return L;
  // Plan the change on a copy, check it gives a valid layout, and only then write.
  const tsCol = Math.max(sh.getLastColumn(), L.name + 1, L.xp + 1) + 1;  // 1-based, after all content
  const width = tsCol;
  const pad = r => { const o = r.slice(); while (o.length < width) o.push(''); return o; };
  let plan = v.map(pad), at = -1;
  if (!L.alias) {
    at = (L.header >= 0 && L.header < HEADER_SEARCH_ROWS) ? L.header + 1 : 1;
    const hdr = pad([]); hdr[L.name] = 'Objeto'; hdr[L.xp] = 'XP'; hdr[tsCol - 1] = 'Actualizado';
    plan.splice(at - 1, 0, hdr);
  } else {
    plan[L.header][tsCol - 1] = 'Actualizado';
  }
  const L2 = layout_(plan);
  if (!L2.alias || L2.ts < 0 || L2.ambiguous) throw new Error('layout');
  if (at > 0) {
    sh.insertRowBefore(at);
    sh.getRange(at, L.name + 1).setValue('Objeto');
    sh.getRange(at, L.xp + 1).setValue('XP');
    sh.getRange(at, tsCol).setValue('Actualizado');
  } else {
    sh.getRange(L.header + 1, tsCol).setValue('Actualizado');
  }
  return layout_(sh.getDataRange().getValues());
}

function state_() {
  const rows = [], tombstones = [];
  const v = xp_().getDataRange().getValues(), L = layout_(v);
  if (L.ambiguous) return { ok: false, error: 'layout' };
  for (let i = L.start; i < v.length; i++) {
    const n = cell_(v[i], L.name);
    if (n && !looksLikeHeader_(v[i], L.name)) rows.push({ name: n, xp: v[i][L.xp], updated_at: L.ts >= 0 ? (Number(v[i][L.ts]) || 0) : 0 });
  }
  const t = tb_().getDataRange().getValues();
  for (let i = 1; i < t.length; i++) if (cell_(t[i], 0))
    tombstones.push({ name: cell_(t[i], 0), deleted_at: Number(t[i][1]) || 0 });
  return { ok: true, now: Date.now(), rows: rows, tombstones: tombstones };
}

function doGet(e) {
  if (TOKEN && (e.parameter.token || '') !== TOKEN) return out_({ ok: false, error: 'token' });
  return out_(state_());
}

function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return out_({ ok: false, error: 'json' }); }
  if (TOKEN && body.token !== TOKEN) return out_({ ok: false, error: 'token' });
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const rejected = apply_(body.ops || []);
    const s = state_(); s.rejected = rejected; return out_(s);
  } catch (err) {
    if (String(err && err.message) === 'layout') return out_({ ok: false, error: 'layout' });
    throw err;
  } finally { lock.releaseLock(); }
}

function apply_(ops) {
  const xs = xp_(), ts = tb_(), now = Date.now(), rejected = [];
  const L = ensureLayout_(xs);
  // Every row of a name (the sheet may contain duplicates), newest timestamp first.
  const index = (sh, nameCol, tsCol, start) => { const m = {}; const v = sh.getDataRange().getValues();
    for (let i = start; i < v.length; i++) if (cell_(v[i], nameCol) && !(sh === xs && looksLikeHeader_(v[i], nameCol))) {
      const k = norm_(cell_(v[i], nameCol)); const t = tsCol >= 0 ? (Number(v[i][tsCol]) || 0) : 0;
      if (!m[k]) m[k] = { r: i + 1, ts: t, rows: [] };
      m[k].rows.push(i + 1); if (t > m[k].ts) m[k].ts = t;
    } return m; };
  const delRows = (sh, rows) => rows.slice().sort((a, b) => b - a).forEach(r => sh.deleteRow(r));
  const stamp = v => (v === undefined || v === null || v === '' || isNaN(Number(v))) ? now : Number(v);
  const writeRow = (r, name, xp, at) => {
    xs.getRange(r, L.name + 1).setValue(name); xs.getRange(r, L.xp + 1).setValue(xp); xs.getRange(r, L.ts + 1).setValue(at); };
  const appendRow = (name, xp, at) => {
    const width = Math.max(xs.getLastColumn(), L.name + 1, L.xp + 1, L.ts + 1);
    const arr = []; for (let j = 0; j < width; j++) arr.push('');
    arr[L.name] = name; arr[L.xp] = xp; arr[L.ts] = at; xs.appendRow(arr); };
  ops.forEach(function (op) {
    const k = norm_(op.name || ''); if (!k) return;
    const row = index(xs, L.name, L.ts, L.start)[k], tomb = index(ts, 0, 1, 1)[k];
    if (op.op === 'upsert') {
      const at = stamp(op.updated_at), xp = Number(op.xp);
      if (!(xp > 0)) { rejected.push(op.name); return; }
      // at == 0: value never edited in the app (old table) -> never overwrites the sheet
      if ((row && (row.ts > at || at === 0)) || (tomb && tomb.ts > at)) { rejected.push(op.name); return; }
      if (row) { writeRow(row.r, op.name, xp, at); delRows(xs, row.rows.slice(1)); }
      else appendRow(op.name, xp, at);
      if (tomb) delRows(ts, tomb.rows);
    } else if (op.op === 'delete') {
      const at = stamp(op.deleted_at);
      if (row && row.ts > at) { rejected.push(op.name); return; }
      if (row) delRows(xs, row.rows);
      if (tomb) { delRows(ts, tomb.rows); }
      ts.appendRow([op.name, Math.max(at, tomb ? tomb.ts : 0)]);
    }
  });
  const v = ts.getDataRange().getValues(), limit = now - TOMB_TTL_DAYS * 864e5;
  for (let i = v.length - 1; i >= 1; i--) if ((Number(v[i][1]) || 0) < limit) ts.deleteRow(i + 1);
  return rejected;
}

// Marca la hora cuando editas a mano el objeto o la XP en la hoja.
function onEdit(e) {
  const sh = e.range.getSheet();
  if (sh.getName() !== SHEET) return;
  const top = sh.getRange(1, 1, Math.max(1, Math.min(HEADER_SEARCH_ROWS, sh.getLastRow())), Math.max(1, sh.getLastColumn())).getValues();
  const L = layout_(top);
  if (!L.alias || L.ts < 0) return;
  const c0 = e.range.getColumn(), c1 = e.range.getLastColumn();
  const touches = c => c >= c0 && c <= c1;
  if (!touches(L.name + 1) && !touches(L.xp + 1)) return;
  const r0 = Math.max(L.start + 1, e.range.getRow()), r1 = e.range.getLastRow();
  if (r1 < r0) return;
  const now = Date.now(), vals = [];
  for (let r = r0; r <= r1; r++) vals.push([now]);
  sh.getRange(r0, L.ts + 1, vals.length, 1).setValues(vals);
}
