// nastolki-api — правки листингов продавца поверх каталога (index.html).
// KV OVERRIDES:
//   "seller:<ник в нижнем регистре>" → {"<t|s|d>": {p, n, x, hidden, bgg_url, bgg_id, title, l, img}}
//   "img:<id>" → байты обложки (WebP/JPEG/PNG ≤ 60 КБ), metadata {ct}
// GET    /overrides?seller=<ник>      — публично, только правки этого продавца
// PUT    /overrides {key, seller, patch} — нужен Authorization: Bearer <EDIT_KEY>
// POST   /img      (тело — картинка)  — EDIT_KEY; отдаёт {id, url}
// GET    /img/<id>                    — публично, Cache-Control immutable
// DELETE /img/<id>                    — EDIT_KEY (уборка)
// POST   /img/proxy {url}             — EDIT_KEY; скачивает картинку по ссылке и отдаёт байты
//                                       (чтобы страница могла сжать её в canvas без CORS)

const MAX_STR = 200;
const MAX_TITLE = 120;
const MAX_BODY = 4096;
const MAX_ENTRIES = 500;
const MAX_IMG = 60 * 1024;
const MAX_PROXY = 8 * 1024 * 1024;
const FIELDS = ['p', 'n', 'x', 'hidden', 'bgg_url', 'bgg_id', 'title', 'l', 'img'];
const LANGS = ['ENG', 'РУС'];
const BGG_RE = /^https:\/\/(www\.)?boardgamegeek\.com\/boardgame(expansion)?\/(\d+)(\/[\w\-%.]*)?$/;
const IMG_ID_RE = /^[a-f0-9]{32}$/;
const IMG_TYPES = ['image/webp', 'image/jpeg', 'image/png'];

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
    h['Access-Control-Allow-Methods'] = 'GET, PUT, POST, DELETE, OPTIONS';
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

// Тип картинки по первым байтам (не верим Content-Type на слово)
function sniff(bytes) {
  const b = (i) => bytes[i];
  if (bytes.length > 12 && b(0) === 0x52 && b(1) === 0x49 && b(2) === 0x46 && b(3) === 0x46 && b(8) === 0x57 && b(9) === 0x45 && b(10) === 0x42 && b(11) === 0x50) return 'image/webp';
  if (bytes.length > 3 && b(0) === 0xff && b(1) === 0xd8 && b(2) === 0xff) return 'image/jpeg';
  if (bytes.length > 8 && b(0) === 0x89 && b(1) === 0x50 && b(2) === 0x4e && b(3) === 0x47) return 'image/png';
  return null;
}

// id картинки из URL override (только свой /img/<id>)
function imgIdFromUrl(v, base) {
  let u;
  try { u = new URL(v); } catch { return null; }
  if (u.origin !== base || u.search || u.hash) return null;
  const m = u.pathname.match(/^\/img\/([a-f0-9]{32})$/);
  return m ? m[1] : null;
}

// Проверка патча. null удаляет поле (возврат к данным каталога); n:"" — очистить примечание, bgg_url:"" — убрать ссылку.
async function validatePatch(patch, env, base) {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) return 'patch must be an object';
  for (const k of Object.keys(patch)) {
    if (!FIELDS.includes(k)) return 'unknown field: ' + k;
    const v = patch[k];
    if (v === null) continue;
    if (k === 'p' && !(typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 10000000)) return 'p must be a number 0..10000000';
    if (k === 'n' && !(typeof v === 'string' && v.length <= MAX_STR)) return 'n must be a string <= 200';
    if ((k === 'x' || k === 'hidden') && typeof v !== 'boolean') return k + ' must be boolean';
    if (k === 'title' && !(typeof v === 'string' && v.trim().length <= MAX_TITLE)) return 'Название — не длиннее 120 символов';
    if (k === 'l' && !LANGS.includes(v)) return 'Язык — только ENG или РУС';
    if (k === 'bgg_id' && !(Number.isInteger(v) && v > 0 && v < 100000000)) return 'bgg_id — целое число';
    if (k === 'bgg_url') {
      if (typeof v !== 'string' || v.length > MAX_STR) return 'bgg_url must be a string <= 200';
      if (v.trim() !== '' && !BGG_RE.test(v.trim())) return 'Ссылка BGG должна быть вида https://boardgamegeek.com/boardgame/ID/…';
    }
    if (k === 'img') {
      if (typeof v !== 'string' || v.length > MAX_STR) return 'img must be a string';
      const id = imgIdFromUrl(v, base);
      if (!id) return 'Обложка — только загруженная через этот сайт';
      if (!(await env.OVERRIDES.get('img:' + id, { type: 'arrayBuffer' }))) return 'Обложка не найдена — загрузи её заново';
    }
  }
  // bgg_id и bgg_url должны указывать на одну игру
  if (typeof patch.bgg_id === 'number' && typeof patch.bgg_url === 'string' && patch.bgg_url.trim()) {
    const m = patch.bgg_url.trim().match(BGG_RE);
    if (!m || Number(m[3]) !== patch.bgg_id) return 'bgg_id не совпадает с ID в ссылке BGG';
  }
  return null;
}

function applyPatch(entry, patch) {
  const out = { ...entry };
  for (const [k, v] of Object.entries(patch)) {
    const s = typeof v === 'string' ? v.trim() : v;
    if (v === null || (k === 'hidden' && v === false) || (k === 'title' && s === '')) delete out[k];
    else out[k] = s;
  }
  return out;
}

async function handleImg(req, env, url) {
  const id = url.pathname.slice(5);
  if (req.method === 'GET') {
    if (!IMG_ID_RE.test(id)) return json(req, 404, { error: 'not found' });
    const { value, metadata } = await env.OVERRIDES.getWithMetadata('img:' + id, { type: 'arrayBuffer' });
    if (!value) return json(req, 404, { error: 'not found' });
    return new Response(value, {
      headers: {
        'Content-Type': (metadata && IMG_TYPES.includes(metadata.ct)) ? metadata.ct : 'image/webp',
        'Cache-Control': 'public, max-age=31536000, immutable',
        'X-Content-Type-Options': 'nosniff',
        ...cors(req),
      },
    });
  }
  if (req.method === 'DELETE') {
    if (!authorized(req, env)) return json(req, 401, { error: 'unauthorized' });
    if (!IMG_ID_RE.test(id)) return json(req, 404, { error: 'not found' });
    await env.OVERRIDES.delete('img:' + id);
    return json(req, 200, { ok: true });
  }
  return json(req, 405, { error: 'method not allowed' });
}

async function uploadImg(req, env, url) {
  if (!authorized(req, env)) return json(req, 401, { error: 'unauthorized' });
  const ct = (req.headers.get('Content-Type') || '').split(';')[0].trim().toLowerCase();
  if (!IMG_TYPES.includes(ct)) return json(req, 415, { error: 'Можно только JPG, PNG или WebP' });
  const len = Number(req.headers.get('Content-Length') || 0);
  if (len > MAX_IMG) return json(req, 413, { error: 'Картинка больше 60 КБ после сжатия' });
  const buf = await req.arrayBuffer();
  if (buf.byteLength > MAX_IMG) return json(req, 413, { error: 'Картинка больше 60 КБ после сжатия' });
  if (buf.byteLength < 16) return json(req, 400, { error: 'Пустой файл' });
  const real = sniff(new Uint8Array(buf));
  if (!real || real !== ct) return json(req, 415, { error: 'Файл не похож на картинку JPG/PNG/WebP' });
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', buf));
  const id = [...hash.slice(0, 16)].map((b) => b.toString(16).padStart(2, '0')).join('');
  await env.OVERRIDES.put('img:' + id, buf, { metadata: { ct: real } });
  return json(req, 200, { ok: true, id, url: url.origin + '/img/' + id, size: buf.byteLength });
}

async function proxyImg(req, env) {
  if (!authorized(req, env)) return json(req, 401, { error: 'unauthorized' });
  const raw = await req.text();
  if (raw.length > MAX_BODY) return json(req, 413, { error: 'body too large' });
  let src;
  try { src = new URL(JSON.parse(raw).url); } catch { return json(req, 400, { error: 'Нужна ссылка на картинку' }); }
  if (src.protocol !== 'https:') return json(req, 400, { error: 'Ссылка должна начинаться с https://' });
  let res;
  try { res = await fetch(src.toString(), { redirect: 'follow', headers: { 'Accept': 'image/webp,image/jpeg,image/png' } }); }
  catch { return json(req, 502, { error: 'Не удалось скачать картинку по ссылке' }); }
  if (!res.ok) return json(req, 502, { error: 'Сайт картинки ответил ошибкой ' + res.status });
  const len = Number(res.headers.get('Content-Length') || 0);
  if (len > MAX_PROXY) return json(req, 413, { error: 'Картинка по ссылке больше 8 МБ' });
  const buf = await res.arrayBuffer();
  if (buf.byteLength > MAX_PROXY) return json(req, 413, { error: 'Картинка по ссылке больше 8 МБ' });
  const real = sniff(new Uint8Array(buf));
  if (!real) return json(req, 415, { error: 'По ссылке не картинка JPG/PNG/WebP' });
  return new Response(buf, { headers: { 'Content-Type': real, 'Cache-Control': 'no-store', ...cors(req) } });
}

// Картинки, на которые больше никто из продавца не ссылается, удаляем
async function dropOrphanImgs(oldEntry, all, env, base) {
  const old = oldEntry && oldEntry.img && imgIdFromUrl(oldEntry.img, base);
  if (!old) return;
  const used = Object.values(all).some((e) => e && e.img && imgIdFromUrl(e.img, base) === old);
  if (!used) await env.OVERRIDES.delete('img:' + old);
}

async function handle(req, env) {
  const url = new URL(req.url);
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors(req) });
  if (url.pathname === '/img' && req.method === 'POST') return uploadImg(req, env, url);
  if (url.pathname === '/img/proxy' && req.method === 'POST') return proxyImg(req, env);
  if (url.pathname.startsWith('/img/')) return handleImg(req, env, url);
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
    const err = await validatePatch(patch, env, url.origin);
    if (err) return json(req, 400, { error: err });

    const all = (await env.OVERRIDES.get(kvKey(seller), { type: 'json' })) || {};
    const prev = all[key] || {};
    const next = applyPatch(prev, patch);
    if (Object.keys(next).length) all[key] = next; else delete all[key];
    if (Object.keys(all).length > MAX_ENTRIES) return json(req, 400, { error: 'too many entries' });
    if (Object.keys(all).length) await env.OVERRIDES.put(kvKey(seller), JSON.stringify(all));
    else await env.OVERRIDES.delete(kvKey(seller));
    if (prev.img && prev.img !== next.img) await dropOrphanImgs(prev, all, env, url.origin);
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
