// Тесты Worker nastolki-api на моке KV, без сети и без Cloudflare.
// Запуск: node --test worker/test   (или ./test.sh)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/index.js';

const BASE = 'https://nastolki-api.example.workers.dev';
const KEY = 'test-edit-key';
const ORIGIN = 'https://nastolki-catalog.pages.dev';

function mockKV() {
  const m = new Map();
  return {
    m,
    async get(k, opt) {
      if (!m.has(k)) return null;
      const { v } = m.get(k);
      if (opt && opt.type === 'json') return JSON.parse(v);
      return v;
    },
    async getWithMetadata(k) {
      if (!m.has(k)) return { value: null, metadata: null };
      const { v, metadata } = m.get(k);
      return { value: v, metadata: metadata || null };
    },
    async put(k, v, opt) { m.set(k, { v, metadata: opt && opt.metadata }); },
    async delete(k) { m.delete(k); },
  };
}

const env = () => ({ EDIT_KEY: KEY, OVERRIDES: mockKV() });
const req = (path, init = {}) => new Request(BASE + path, { ...init, headers: { Origin: ORIGIN, ...(init.headers || {}) } });
const put = (e, body, key = KEY) => worker.fetch(req('/overrides', {
  method: 'PUT',
  headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + key },
  body: JSON.stringify(body),
}), e);

test('GET /overrides без seller — 400', async () => {
  const r = await worker.fetch(req('/overrides'), env());
  assert.equal(r.status, 400);
});

test('GET /overrides пустой продавец — {} и CORS для своего origin', async () => {
  const r = await worker.fetch(req('/overrides?seller=Someone'), env());
  assert.equal(r.status, 200);
  assert.deepEqual(await r.json(), {});
  assert.equal(r.headers.get('Access-Control-Allow-Origin'), ORIGIN);
});

test('чужой origin не получает CORS', async () => {
  const r = await worker.fetch(new Request(BASE + '/overrides?seller=x', { headers: { Origin: 'https://evil.example' } }), env());
  assert.equal(r.headers.get('Access-Control-Allow-Origin'), null);
});

test('PUT без ключа или с неверным ключом — 401', async () => {
  const e = env();
  assert.equal((await put(e, { key: 'A|bob|01.01.2026', seller: 'bob', patch: { p: 1 } }, 'wrong')).status, 401);
  const r = await worker.fetch(req('/overrides', { method: 'PUT', body: '{}' }), e);
  assert.equal(r.status, 401);
});

test('PUT: ключ должен принадлежать продавцу', async () => {
  const r = await put(env(), { key: 'A|alice|01.01.2026', seller: 'bob', patch: { p: 1 } });
  assert.equal(r.status, 400);
});

test('PUT: валидация полей', async () => {
  const e = env();
  const k = { key: 'A|bob|01.01.2026', seller: 'bob' };
  assert.equal((await put(e, { ...k, patch: { evil: 1 } })).status, 400);
  assert.equal((await put(e, { ...k, patch: { p: -5 } })).status, 400);
  assert.equal((await put(e, { ...k, patch: { l: 'FR' } })).status, 400);
  assert.equal((await put(e, { ...k, patch: { bgg_url: 'javascript:alert(1)' } })).status, 400);
  assert.equal((await put(e, { ...k, patch: { img: 'https://evil.example/x.png' } })).status, 400);
  assert.equal((await put(e, { ...k, patch: { bgg_id: 5, bgg_url: 'https://boardgamegeek.com/boardgame/6/x' } })).status, 400);
});

test('PUT сохраняет правку, GET её отдаёт, null откатывает', async () => {
  const e = env();
  const k = { key: 'Title|Bob|01.01.2026', seller: 'Bob' };
  let r = await put(e, { ...k, patch: { p: 15000, n: ' note ', x: true } });
  assert.equal(r.status, 200);
  r = await worker.fetch(req('/overrides?seller=bob'), e);
  assert.deepEqual(await r.json(), { [k.key]: { p: 15000, n: 'note', x: true } });
  await put(e, { ...k, patch: { p: null, n: null, x: null } });
  assert.equal(e.OVERRIDES.m.has('seller:bob'), false);
});

test('ключ с "|" в названии режется с конца', async () => {
  const r = await put(env(), { key: 'A|B|bob|01.01.2026', seller: 'bob', patch: { hidden: true } });
  assert.equal(r.status, 200);
});

test('POST /img: только настоящая картинка, не больше 60 КБ', async () => {
  const e = env();
  const png = new Uint8Array(64); png.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const up = (body, ct) => worker.fetch(req('/img', { method: 'POST', headers: { 'Content-Type': ct, Authorization: 'Bearer ' + KEY }, body }), e);
  assert.equal((await up(new Uint8Array(64), 'image/png')).status, 415);
  assert.equal((await up(png, 'image/jpeg')).status, 415);
  assert.equal((await up(new Uint8Array(61 * 1024), 'image/png')).status, 413);
  const r = await up(png, 'image/png');
  assert.equal(r.status, 200);
  const { id, url } = await r.json();
  assert.match(id, /^[a-f0-9]{32}$/);
  const g = await worker.fetch(req('/img/' + id), e);
  assert.equal(g.status, 200);
  assert.equal(g.headers.get('Content-Type'), 'image/png');
  // ссылку на свою картинку можно сохранить в листинг
  const p = await put(e, { key: 'A|bob|01.01.2026', seller: 'bob', patch: { img: url } });
  assert.equal(p.status, 200);
});

test('неизвестный путь — 404, исключения — 500 без деталей', async () => {
  assert.equal((await worker.fetch(req('/nope'), env())).status, 404);
  const broken = { EDIT_KEY: KEY, OVERRIDES: { get() { throw new Error('secret detail'); } } };
  const r = await worker.fetch(req('/overrides?seller=x'), broken);
  assert.equal(r.status, 500);
  assert.deepEqual(await r.json(), { error: 'internal error' });
});
