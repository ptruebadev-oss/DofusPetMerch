// Runs the DofusPetMerch Apps Script against an in-memory mock of SpreadsheetApp.
// Usage: node tests/apps_script_test.js
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const here = p => path.join(__dirname, p);
const src = fs.readFileSync(here('../src/dofuspetmerch/sheets/apps_script.js'), 'utf8');

function makeSheet(name, initial) {
  const data = (initial || []).map(r => r.slice());
  const width = () => data.reduce((w, r) => Math.max(w, r.length), 0);
  const lastCol = () => { let w = 0; data.forEach(r => r.forEach((c, j) => { if (c !== '' && c !== undefined && c !== null) w = Math.max(w, j + 1); })); return w; };
  const cell = (r, c) => { data[r - 1] = data[r - 1] || []; return data[r - 1]; };
  return {
    data, getName: () => name,
    appendRow: r => data.push(r.slice()),
    deleteRow: i => data.splice(i - 1, 1),
    insertRowBefore: i => data.splice(i - 1, 0, []),
    getLastRow: () => data.length,
    getLastColumn: lastCol,
    // Like Sheets: a rectangular grid padded with '' ([['']] for an empty sheet).
    getDataRange: () => ({ getValues: () => {
      if (!data.length) return [['']];
      const w = Math.max(1, width());
      return data.map(r => { const o = []; for (let j = 0; j < w; j++) o.push(r[j] === undefined ? '' : r[j]); return o; });
    } }),
    getRange: (r, c, nr = 1, nc = 1) => ({
      setValue: v => { cell(r, c)[c - 1] = v; },
      setValues: vals => { for (let i = 0; i < nr; i++) for (let j = 0; j < nc; j++) cell(r + i, c + j)[c - 1 + j] = vals[i][j]; },
      getValues: () => { const o = []; for (let i = 0; i < nr; i++) { const row = []; for (let j = 0; j < nc; j++) { const v = (data[r - 1 + i] || [])[c - 1 + j]; row.push(v === undefined ? '' : v); } o.push(row); } return o; },
    }),
  };
}

// A fresh spreadsheet per scenario; `xpData` pre-fills the XP tab as the user left it.
function setup(xpData) {
  const sheets = {};
  if (xpData) sheets['XP'] = makeSheet('XP', xpData);
  const ss = { getSheetByName: n => sheets[n] || null, insertSheet: n => (sheets[n] = makeSheet(n)) };
  const SpreadsheetApp = { getActive: () => ss };
  const ContentService = { MimeType: { JSON: 'json' }, createTextOutput: t => ({ text: t, setMimeType() { return this; } }) };
  const LockService = { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) };
  const api = new Function('SpreadsheetApp', 'ContentService', 'LockService',
    src + '\nreturn {doGet, doPost, onEdit, layout_, num_, cell_};')(SpreadsheetApp, ContentService, LockService);
  const post = (ops, token = 'cambia-esto') => JSON.parse(api.doPost({ postData: { contents: JSON.stringify({ token, ops }) } }).text);
  const get = (token = 'cambia-esto') => JSON.parse(api.doGet({ parameter: { token } }).text);
  const edit = (sh, row, col, lastCol = col) => api.onEdit({ range: { getSheet: () => sh, getColumn: () => col, getLastColumn: () => lastCol, getRow: () => row, getLastRow: () => row } });
  return { sheets, api, post, get, edit };
}

// ---------------------------------------------------------------- basics
{
  const { sheets, post, get, edit } = setup();
  assert.deepStrictEqual(get('mal'), { ok: false, error: 'token' });
  assert.strictEqual(post([], 'mal').error, 'token');
  let s = post([{ op: 'upsert', name: 'Gobio', xp: 0.5, updated_at: 100 }, { op: 'upsert', name: 'Trucha de río', xp: 3, updated_at: 100 }]);
  assert.ok(s.ok); assert.strictEqual(s.rows.length, 2);
  // older upsert rejected, newer accepted (accent/case-insensitive match)
  s = post([{ op: 'upsert', name: 'gobio', xp: 9, updated_at: 50 }]);
  assert.deepStrictEqual(s.rejected, ['gobio']); assert.strictEqual(s.rows.find(r => r.name === 'Gobio').xp, 0.5);
  s = post([{ op: 'upsert', name: 'TRUCHA DE RIO', xp: 4, updated_at: 200 }]);
  assert.strictEqual(s.rows.length, 2); assert.ok(s.rows.some(r => r.name === 'TRUCHA DE RIO' && r.xp === 4));
  // invalid xp rejected
  assert.deepStrictEqual(post([{ op: 'upsert', name: 'X', xp: 0, updated_at: 300 }]).rejected, ['X']);
  // delete creates tombstone; older re-add rejected; newer re-add removes tombstone
  s = post([{ op: 'delete', name: 'Gobio', deleted_at: Date.now() }]);
  assert.strictEqual(s.rows.length, 1); assert.strictEqual(s.tombstones.length, 1);
  assert.deepStrictEqual(post([{ op: 'upsert', name: 'Gobio', xp: 1, updated_at: 150 }]).rejected, ['Gobio']);
  s = post([{ op: 'upsert', name: 'Gobio', xp: 1, updated_at: Date.now() + 1000 }]);
  assert.strictEqual(s.rows.length, 2); assert.strictEqual(s.tombstones.length, 0);
  // delete of a row edited later is rejected
  assert.deepStrictEqual(post([{ op: 'delete', name: 'Gobio', deleted_at: 10 }]).rejected, ['Gobio']);
  // old tombstones expire (> 90 days)
  post([{ op: 'delete', name: 'Viejo', deleted_at: Date.now() - 100 * 864e5 }]);
  assert.strictEqual(get().tombstones.filter(t => t.name === 'Viejo').length, 0);
  // onEdit stamps "Actualizado" for manual edits of name/XP
  const xp = sheets['XP']; xp.appendRow(['Manual', 7, '']);
  const row = xp.data.length;
  edit(xp, row, 2);
  assert.ok(Number(xp.data[row - 1][2]) > 0);
  // duplicates in the sheet: delete removes all of them, upsert keeps one
  xp.appendRow(['Dup', 1, 5]); xp.appendRow(['dup', 2, 6]);
  post([{ op: 'delete', name: 'DUP', deleted_at: Date.now() }]);
  assert.strictEqual(get().rows.filter(r => r.name.toLowerCase() === 'dup').length, 0);
  xp.appendRow(['Dos', 1, 5]); xp.appendRow(['dos', 2, 6]);
  post([{ op: 'upsert', name: 'Dos', xp: 3, updated_at: Date.now() }]);
  assert.deepStrictEqual(get().rows.filter(r => r.name.toLowerCase() === 'dos').map(r => r.xp), [3]);
  // updated_at 0 (old local table, never edited in the app) never overwrites an existing row
  xp.appendRow(['Hoja', 5, 0]);
  assert.deepStrictEqual(post([{ op: 'upsert', name: 'Hoja', xp: 0.5, updated_at: 0 }]).rejected, ['Hoja']);
  assert.strictEqual(get().rows.find(r => r.name === 'Hoja').xp, 5);
  // ...but is added when the sheet doesn't have it
  assert.deepStrictEqual(post([{ op: 'upsert', name: 'Nuevo0', xp: 2, updated_at: 0 }]).rejected, []);
}

// ------------------------------------------------- user-made sheet layouts
// No header at all: GET reads it without touching it, POST inserts a header row.
{
  const { sheets, post, get } = setup([['Gobio', 0.5], ['Trucha', 3]]);
  const before = JSON.stringify(sheets['XP'].data);
  assert.deepStrictEqual(get().rows.map(r => [r.name, r.xp]), [['Gobio', 0.5], ['Trucha', 3]]);
  assert.strictEqual(JSON.stringify(sheets['XP'].data), before, 'GET must not modify the sheet');
  post([{ op: 'upsert', name: 'Nuevo', xp: 2, updated_at: 500 }]);
  const d = sheets['XP'].data;
  assert.deepStrictEqual(d[0], ['Objeto', 'XP', 'Actualizado']);
  assert.deepStrictEqual(d.slice(1).map(r => [r[0], r[1]]), [['Gobio', 0.5], ['Trucha', 3], ['Nuevo', 2]]);
}

// Swapped columns with Spanish/English aliases and an extra notes column.
{
  const { sheets, post, get } = setup([['Experiencia', 'Nombre', 'Notas'], [0.5, 'Gobio', 'río'], ['3', 'Trucha', '']]);
  assert.deepStrictEqual(get().rows.map(r => [r.name, String(r.xp)]), [['Gobio', '0.5'], ['Trucha', '3']]);
  post([{ op: 'upsert', name: 'Gobio', xp: 1, updated_at: 900 }, { op: 'upsert', name: 'Pez', xp: 4, updated_at: 900 }]);
  const d = sheets['XP'].data;
  assert.deepStrictEqual(d[0], ['Experiencia', 'Nombre', 'Notas', 'Actualizado']);
  assert.deepStrictEqual(d[1], [1, 'Gobio', 'río', 900], 'notes column must be preserved');
  assert.deepStrictEqual(d[3], [4, 'Pez', '', 900]);
  post([{ op: 'delete', name: 'trucha', deleted_at: Date.now() }]);
  assert.deepStrictEqual(sheets['XP'].data.map(r => r[1]), ['Nombre', 'Gobio', 'Pez']);
}

// Custom header ("Item | Exp."), title rows above it, existing timestamp column "Modificado".
{
  const { sheets, post, get } = setup([['Mi tabla de mascotas', ''], ['', ''], ['Item', 'Exp.', 'Modificado'], ['Gobio', '0,5', 100]]);
  const g = get();
  assert.deepStrictEqual(g.rows, [{ name: 'Gobio', xp: '0,5', updated_at: 100 }]);
  post([{ op: 'upsert', name: 'Gobio', xp: 2, updated_at: 200 }]);
  const d = sheets['XP'].data;
  assert.deepStrictEqual(d[0], ['Mi tabla de mascotas', ''], 'title untouched');
  assert.deepStrictEqual(d[2], ['Item', 'Exp.', 'Modificado'], 'no extra timestamp column when one exists');
  assert.deepStrictEqual(d[3], ['Gobio', 2, 200]);
}

// A user "Fecha" column with real dates is NOT used as timestamp and is never overwritten.
{
  const when = new Date(2026, 5, 1);
  const { sheets, post } = setup([['Objeto', 'XP', 'Fecha'], ['Gobio', 1, when]]);
  post([{ op: 'upsert', name: 'Gobio', xp: 2, updated_at: 300 }]);
  const d = sheets['XP'].data;
  assert.deepStrictEqual(d[0], ['Objeto', 'XP', 'Fecha', 'Actualizado']);
  assert.strictEqual(d[1][2], when, 'date cell untouched');
  assert.deepStrictEqual([d[1][1], d[1][3]], [2, 300]);
}

// Header with unknown labels ("Cosa | Valor"): a header row is INSERTED above, nothing renamed.
{
  const { sheets, post } = setup([['Cosa', 'Valor'], ['Gobio', 1], ['Trucha', 2]]);
  post([]);
  assert.deepStrictEqual(sheets['XP'].data[0], ['Objeto', 'XP', 'Actualizado']);
  assert.deepStrictEqual(sheets['XP'].data.slice(1).map(r => r.slice(0, 2)), [['Cosa', 'Valor'], ['Gobio', 1], ['Trucha', 2]]);
}

// A first data row with XP 0 is data, not a header: it is never overwritten.
{
  const { sheets, post } = setup([['Gobio', 0], ['Trucha', 3], ['Pez', 2]]);
  post([]);
  assert.deepStrictEqual(sheets['XP'].data.map(r => r[0]), ['Objeto', 'Gobio', 'Trucha', 'Pez']);
}

// A data row whose name starts like an alias and has a note like "experimental" is data.
{
  const { get } = setup([['Objeto raro', 5, 'experimental'], ['Gobio', 1, '']]);
  assert.deepStrictEqual(get().rows.map(r => [r.name, r.xp]), [['Objeto raro', 5], ['Gobio', 1]]);
}

// Two numeric columns and no header: refuse (no guessing, no writes) with error "layout".
{
  const { sheets, post, get } = setup([['Precio', 'Cosa', 'Valor'], [100, 'Gobio', 1], [200, 'Trucha', 2]]);
  const before = JSON.stringify(sheets['XP'].data);
  assert.deepStrictEqual(get(), { ok: false, error: 'layout' });
  assert.deepStrictEqual(post([{ op: 'upsert', name: 'Gobio', xp: 9, updated_at: 900 }]), { ok: false, error: 'layout' });
  assert.strictEqual(JSON.stringify(sheets['XP'].data), before, 'sheet untouched');
}

// A list of names with no XP yet: header inserted with "Actualizado" AFTER the (empty) XP
// column, names untouched; a second POST changes nothing.
for (const rows of [[['Gobio'], ['Trucha']], [['Gobio', ''], ['Trucha', '']]]) {
  const { sheets, post } = setup(rows);
  assert.ok(post([]).ok);
  const d = sheets['XP'].data;
  assert.deepStrictEqual(d[0], ['Objeto', 'XP', 'Actualizado']);
  assert.deepStrictEqual(d.slice(1).map(r => r[0]), ['Gobio', 'Trucha']);
  const after = JSON.stringify(d);
  assert.ok(post([]).ok);
  assert.strictEqual(JSON.stringify(sheets['XP'].data), after, 'second POST must not change the sheet');
  post([{ op: 'upsert', name: 'Gobio', xp: 2, updated_at: 50 }]);
  assert.deepStrictEqual(sheets['XP'].data[1].slice(0, 3), ['Gobio', 2, 50]);
}

// A number elsewhere in the header row ("2024", "Total 42") does not invalidate the header.
{
  const { sheets, post, get } = setup([['Objeto', 'XP', '2024'], ['Gobio', 1, '']]);
  assert.deepStrictEqual(get().rows.map(r => [r.name, r.xp]), [['Gobio', 1]]);
  post([{ op: 'upsert', name: 'Gobio', xp: 3, updated_at: 700 }]);
  assert.deepStrictEqual(sheets['XP'].data[0], ['Objeto', 'XP', '2024', 'Actualizado']);
  assert.deepStrictEqual(sheets['XP'].data[1], ['Gobio', 3, '', 700]);
}

// "Objeto raro | experimental | 5" is data: XP goes to column 3, the notes column is never written.
{
  const { sheets, post, get } = setup([['Objeto raro', 'experimental', 5], ['Gobio', '', 1]]);
  assert.deepStrictEqual(get().rows.map(r => [r.name, r.xp]), [['Objeto raro', 5], ['Gobio', 1]]);
  post([{ op: 'upsert', name: 'Pez', xp: 7, updated_at: 10 }, { op: 'upsert', name: 'Objeto raro', xp: 6, updated_at: 20 }]);
  const d = sheets['XP'].data;
  assert.deepStrictEqual(Array.from(d[0], c => c === undefined ? '' : c), ['Objeto', '', 'XP', 'Actualizado']);
  assert.deepStrictEqual(d[1], ['Objeto raro', 'experimental', 6, 20], 'notes preserved');
  assert.deepStrictEqual(d[3], ['Pez', '', 7, 10]);
}

// Typing names by hand under the header the script created: onEdit keeps stamping, GET never
// returns the timestamp as XP, POST never adds a second header.
{
  const { sheets, post, get, edit } = setup([]);
  post([]);  // empty tab -> Objeto | XP | Actualizado
  const xp = sheets['XP'];
  xp.appendRow(['Gobio']); edit(xp, 2, 1);
  xp.appendRow(['Trucha']); edit(xp, 3, 1);
  assert.ok(Number(xp.data[1][2]) > 0 && Number(xp.data[2][2]) > 0, 'both rows stamped');
  assert.deepStrictEqual(get().rows.map(r => [r.name, r.xp]), [['Gobio', ''], ['Trucha', '']]);
  post([{ op: 'upsert', name: 'Gobio', xp: 7, updated_at: Date.now() + 1000 }]);
  assert.deepStrictEqual(xp.data[0], ['Objeto', 'XP', 'Actualizado'], 'no second header');
  assert.strictEqual(xp.data[1][1], 7, 'XP written in the XP column');
  assert.strictEqual(xp.data.length, 3);
}

// Header with an extra numeric column (Precio) and empty XP: still the header, price untouched.
{
  const { sheets, post, get } = setup([['Objeto', 'XP', 'Precio'], ['Gobio', '', 100]]);
  assert.deepStrictEqual(get().rows.map(r => [r.name, r.xp]), [['Gobio', '']]);
  post([{ op: 'upsert', name: 'Gobio', xp: 2, updated_at: 40 }]);
  assert.deepStrictEqual(sheets['XP'].data, [['Objeto', 'XP', 'Precio', 'Actualizado'], ['Gobio', 2, 100, 40]]);
}

// "Objeto | XP | 2024" rejected as header (XP empty, numbers in "2024"): the old header row is
// kept in the sheet but never returned as an item called "Objeto".
{
  const { sheets, post, get } = setup([['Objeto', 'XP', '2024'], ['Gobio', '', 5]]);
  assert.deepStrictEqual(get().rows.map(r => r.name), ['Gobio']);
  assert.deepStrictEqual(post([]).rows.map(r => r.name), ['Gobio']);
  assert.deepStrictEqual(sheets['XP'].data.slice(1).map(r => r.slice(0, 3)), [['Objeto', 'XP', '2024'], ['Gobio', '', 5]]);
  // an item literally called "Objeto" is a new row: the old header row is never overwritten/deleted
  post([{ op: 'upsert', name: 'Objeto', xp: 3, updated_at: 60 }]);
  assert.deepStrictEqual(sheets['XP'].data[1].slice(0, 3), ['Objeto', 'XP', '2024']);
  post([{ op: 'delete', name: 'Objeto', deleted_at: Date.now() }]);
  assert.deepStrictEqual(sheets['XP'].data[1].slice(0, 3), ['Objeto', 'XP', '2024']);
}

// Title row without a recognised header: header inserted on top, the title stays.
{
  const { sheets, post } = setup([['Tabla mascotas', 'Junio'], ['Gobio', 1], ['Trucha', 2]]);
  post([]);
  assert.deepStrictEqual(sheets['XP'].data.map(r => r.slice(0, 2)), [['Objeto', 'XP'], ['Tabla mascotas', 'Junio'], ['Gobio', 1], ['Trucha', 2]]);
}

// An item literally called "Exp" stays data (its XP cell is a number).
{
  const { get } = setup([['Exp', 5], ['Gobio', 1]]);
  assert.deepStrictEqual(get().rows.map(r => r.name), ['Exp', 'Gobio']);
}

// onEdit: stamps the detected timestamp column, ignores the notes column and the header.
{
  const { sheets, post, edit } = setup([['Nombre', 'XP', 'Notas'], ['Gobio', 1, '']]);
  post([]);  // adds "Actualizado" in column 4
  const xp = sheets['XP'];
  edit(xp, 2, 3);  // notes edited -> no stamp
  assert.ok(!xp.data[1][3]);
  edit(xp, 2, 2);  // XP edited -> stamp
  assert.ok(Number(xp.data[1][3]) > 0);
  edit(xp, 1, 1);  // header edited -> nothing
  assert.strictEqual(xp.data[0][3], 'Actualizado');
}

// Empty existing XP tab gets the default header.
{
  const { sheets, post } = setup([]);
  post([{ op: 'upsert', name: 'Gobio', xp: 1, updated_at: 5 }]);
  assert.deepStrictEqual(sheets['XP'].data, [['Objeto', 'XP', 'Actualizado'], ['Gobio', 1, 5]]);
}

// Cases shared with the Python twins (detect_layout, parse_number, _cell).
{
  const { api } = setup();
  for (const c of JSON.parse(fs.readFileSync(here('layout_cases.json'), 'utf8'))) {
    const L = api.layout_(c.rows);
    assert.deepStrictEqual([L.name, L.xp, L.header, L.start], c.expect, JSON.stringify(c.rows));
    assert.strictEqual(L.ambiguous, !!c.ambiguous, 'ambiguous: ' + JSON.stringify(c.rows));
  }
  const parity = JSON.parse(fs.readFileSync(here('parity_cases.json'), 'utf8'));
  for (const [text, want] of parity.numbers) assert.strictEqual(api.num_(text), want, 'num_ ' + JSON.stringify(text));
  for (const [raw, want] of parity.trim) assert.strictEqual(api.cell_([raw], 0), want, 'cell_ ' + JSON.stringify(raw));
}
console.log('Apps Script OK');
