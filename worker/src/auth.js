// Вход владельца листингов через Telegram Login Widget и короткоживущий токен сессии.
// Секреты (wrangler secret): TG_LOGIN_BOT_TOKEN — токен бота виджета, SESSION_SECRET — ключ подписи сессий.
// https://core.telegram.org/widgets/login#checking-authorization

export const AUTH_MAX_AGE = 86400;      // данные виджета не старше суток
export const SESSION_TTL = 12 * 3600;   // токен сессии живёт 12 часов
const CLOCK_SKEW = 300;                 // допуск часов, сек

const enc = new TextEncoder();

function hex(buf) {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}
function b64url(bytes) {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function unb64url(str) {
  const s = atob(str.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((str.length + 3) % 4));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}

// Сравнение без утечки по времени
export function safeEqual(a, b) {
  const x = enc.encode(String(a)), y = enc.encode(String(b));
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] || 0) ^ (y[i] || 0);
  return diff === 0;
}

async function hmac(keyBytes, msg) {
  const key = await crypto.subtle.importKey('raw', keyBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return crypto.subtle.sign('HMAC', key, enc.encode(msg));
}

export const normNick = (s) => String(s || '').trim().replace(/^@/, '').toLowerCase();

// Проверка данных Telegram Login Widget.
// Возвращает {ok:true, username, id} или {ok:false, code, error}.
export async function verifyTelegramLogin(data, botToken, now = Math.floor(Date.now() / 1000)) {
  if (!botToken) return { ok: false, code: 'not_configured', error: 'Вход через Telegram ещё не настроен' };
  if (!data || typeof data !== 'object' || Array.isArray(data) || typeof data.hash !== 'string')
    return { ok: false, code: 'bad_signature', error: 'Нет подписи Telegram' };
  const check = Object.keys(data)
    .filter((k) => k !== 'hash' && data[k] !== undefined && data[k] !== null)
    .sort()
    .map((k) => k + '=' + data[k])
    .join('\n');
  const secret = await crypto.subtle.digest('SHA-256', enc.encode(botToken));
  const want = hex(await hmac(new Uint8Array(secret), check));
  if (!safeEqual(want, data.hash.toLowerCase())) return { ok: false, code: 'bad_signature', error: 'Подпись Telegram не сошлась' };
  const ad = Number(data.auth_date);
  if (!Number.isFinite(ad) || ad > now + CLOCK_SKEW || now - ad > AUTH_MAX_AGE)
    return { ok: false, code: 'expired', error: 'Вход устарел — войди через Telegram ещё раз' };
  const username = normNick(data.username);
  if (!username) return { ok: false, code: 'no_username', error: 'В твоём Telegram не задан username (@ник) — задай его в настройках Telegram и войди снова' };
  return { ok: true, username, id: data.id };
}

// Токен сессии: base64url(JSON{u,exp}) + "." + base64url(HMAC-SHA256(SESSION_SECRET, payload))
export async function makeSession(username, secret, now = Math.floor(Date.now() / 1000), ttl = SESSION_TTL) {
  if (!secret) throw new Error('SESSION_SECRET is not set');
  const payload = b64url(enc.encode(JSON.stringify({ u: normNick(username), exp: now + ttl })));
  const sig = b64url(new Uint8Array(await hmac(enc.encode(secret), payload)));
  return { token: payload + '.' + sig, exp: now + ttl };
}

// Возвращает {ok:true, username, exp} или {ok:false, code, error}
export async function verifySession(token, secret, now = Math.floor(Date.now() / 1000)) {
  if (!secret || typeof token !== 'string') return { ok: false, code: 'bad_token', error: 'Нужно войти через Telegram' };
  const parts = token.split('.');
  if (parts.length !== 2 || !parts[0] || !parts[1]) return { ok: false, code: 'bad_token', error: 'Нужно войти через Telegram' };
  const want = b64url(new Uint8Array(await hmac(enc.encode(secret), parts[0])));
  if (!safeEqual(want, parts[1])) return { ok: false, code: 'bad_token', error: 'Сессия недействительна — войди через Telegram ещё раз' };
  let p;
  try { p = JSON.parse(new TextDecoder().decode(unb64url(parts[0]))); } catch { return { ok: false, code: 'bad_token', error: 'Сессия недействительна — войди через Telegram ещё раз' }; }
  if (!p || typeof p.u !== 'string' || !p.u || !Number.isFinite(p.exp)) return { ok: false, code: 'bad_token', error: 'Сессия недействительна — войди через Telegram ещё раз' };
  if (now >= p.exp) return { ok: false, code: 'expired', error: 'Сессия истекла — войди через Telegram ещё раз' };
  return { ok: true, username: p.u, exp: p.exp };
}

// Можно ли этому пользователю править листинги продавца seller (ник без регистра и без @)
export function ownsSeller(username, seller) {
  const u = normNick(username), s = normNick(seller);
  return !!u && u === s;
}
