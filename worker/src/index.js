// nastolki-api — правки листингов продавца поверх каталога (index.html).
// KV OVERRIDES: ключ "seller:<ник в нижнем регистре>" → {"<t|s|d>": {p, n, x, hidden, bgg_url}}
// GET  /overrides?seller=<ник>  — публично, только правки этого продавца
// PUT  /overrides {key, seller, patch} — нужен Authorization: Bearer <EDIT_KEY>

const MAX_STR = 200;
const MAX_BODY = 4096;
const MAX_ENTRIES = 500;
const FIELDS = ['p', 'n', 'x', 'hidden', 'bgg_url'];

function originAllowed(origin) {
  if (!origin) return false;
  let u;
  try { u = new URL(origin); } catch { return false; }
  if (u.protocol === 'https:' && (u.hostname === 'nastolki-catalog.pages.dev' || u.hostname.endsWith('.nastolki-catalog.pages.dev'))) return true;
  if (u.protocol === 'http:' && (u.hostname === 'localhost' || u.hostname === '127.0.0.1')) return true;
  return false;
}

function cors(req) {
  const origin = req.headers.get('Origin');
  const h = { 'Vary': 'Origin' };
  if (originAllowed(origin)) {
    h['Access-Control-Allow-Origin'] = origin;
    h['Access-Control-Allow-Methods'] = 'GET, PUT, OPTIONS';
    h['Access-Control-Allow-Headers'] = 'Content-Type, Authorization';
    h['Access-Control-Max-Age'] = '86400';
  }
  return h;
}

function json(req, status, data, extra = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...cors(req), ...extra },
  });
}

const norm = (s) => String(s || '').trim().toLowerCase();
const kvKey = (seller) => 'seller:' + norm(seller);

// Сравнение без утечки по времени
function safeEqual(a, b) {
  const enc = new TextEncoder();
  const x = enc.encode(a), y = enc.encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] || 0) ^ (y[i] || 0);
  return diff === 0;
}

function authorized(req, env) {
  const h = req.headers.get('Authorization') || '';
  const m = h.match(/^Bearer\s+(.+)$/);
  if (!m || !env.EDIT_KEY) return false;
  return safeEqual(m[1].trim(), env.EDIT_KEY);
}

// Проверка патча. null или hidden:false удаляют поле (возврат к данным каталога); n:"" — очистить примечание.
function validatePatch(patch) {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) return 'patch must be an object';
  for (const k of Object.keys(patch)) {
    if (!FIELDS.includes(k)) return 'unknown field: ' + k;
    const v = patch[k];
    if (v === null) continue;
    if (k === 'p' && !(typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 10000000)) return 'p must be a number 0..10000000';
    if (k === 'n' && !(typeof v === 'string' && v.length <= MAX_STR)) return 'n must be a string <= 200';
    if ((k === 'x' || k === 'hidden') && typeof v !== 'boolean') return k + ' must be boolean';
    if (k === 'bgg_url') {
      if (typeof v !== 'string' || v.length > MAX_STR) return 'bgg_url must be a string <= 200';
      if (v !== '' && !/^https:\/\/(www\.)?boardgamegeek\.com\/boardgame(expansion)?\/\d+(\/[\w\-%.]*)?$/.test(v)) return 'bgg_url must be a boardgamegeek.com/boardgame/ID link';
    }
  }
  return null;
}

function applyPatch(entry, patch) {
  const out = { ...entry };
  for (const [k, v] of Object.entries(patch)) {
    if (v === null || (k === 'hidden' && v === false)) delete out[k];
    else out[k] = k === 'n' || k === 'bgg_url' ? v.trim() : v;
  }
  return out;
}

async function handle(req, env) {
  const url = new URL(req.url);
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors(req) });
  if (url.pathname !== '/overrides') return json(req, 404, { error: 'not found' });

  if (req.method === 'GET') {
    const seller = url.searchParams.get('seller') || '';
    if (!norm(seller) || seller.length > MAX_STR) return json(req, 400, { error: 'seller required' });
    const data = (await env.OVERRIDES.get(kvKey(seller), { type: 'json' })) || {};
    return json(req, 200, data);
  }

  if (req.method === 'PUT') {
    if (!authorized(req, env)) return json(req, 401, { error: 'unauthorized' });
    const raw = await req.text();
    if (raw.length > MAX_BODY) return json(req, 413, { error: 'body too large' });
    let body;
    try { body = JSON.parse(raw); } catch { return json(req, 400, { error: 'invalid json' }); }
    const { key, seller, patch } = body || {};
    if (typeof key !== 'string' || typeof seller !== 'string' || !key || !norm(seller) || key.length > MAX_STR || seller.length > MAX_STR)
      return json(req, 400, { error: 'key and seller required (<= 200 chars)' });
    // ключ = t|s|d; название t может содержать "|", поэтому режем с конца
    const i2 = key.lastIndexOf('|'), i1 = i2 > 0 ? key.lastIndexOf('|', i2 - 1) : -1;
    if (i1 <= 0 || norm(key.slice(i1 + 1, i2)) !== norm(seller)) return json(req, 400, { error: 'key does not belong to seller' });
    const err = validatePatch(patch);
    if (err) return json(req, 400, { error: err });

    const all = (await env.OVERRIDES.get(kvKey(seller), { type: 'json' })) || {};
    const next = applyPatch(all[key] || {}, patch);
    if (Object.keys(next).length) all[key] = next; else delete all[key];
    if (Object.keys(all).length > MAX_ENTRIES) return json(req, 400, { error: 'too many entries' });
    if (Object.keys(all).length) await env.OVERRIDES.put(kvKey(seller), JSON.stringify(all));
    else await env.OVERRIDES.delete(kvKey(seller));
    return json(req, 200, { ok: true, key, entry: all[key] || null });
  }

  return json(req, 405, { error: 'method not allowed' });
}

export default {
  async fetch(req, env) {
    try { return await handle(req, env); }
    catch { return json(req, 500, { error: 'internal error' }); }
  },
};
