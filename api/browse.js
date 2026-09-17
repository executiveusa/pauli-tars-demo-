// BARS read-only web browse (power-up lane). Public-URL guard: every URL -
// including each redirect hop - is DNS-resolved and private/loopback/
// link-local/CGNAT addresses are refused. Text extraction only: no scripts
// execute, no cookies are sent or stored, nothing is written.
import dns from 'node:dns/promises';
import net from 'node:net';

const MAX_BYTES = 2_000_000, MAX_OUT = 6000, TIMEOUT_MS = 15000, MAX_REDIRECTS = 3;

function isPublicIp(ip) {
  if (net.isIPv6(ip)) {
    const n = ip.toLowerCase();
    if (n.startsWith('::ffff:')) return isPublicIp(n.slice(7));
    if (n === '::1' || n === '::' || n.startsWith('fe8') || n.startsWith('fe9') ||
        n.startsWith('fea') || n.startsWith('feb') || n.startsWith('fc') || n.startsWith('fd')) return false;
    return true;
  }
  const p = ip.split('.').map(Number);
  if (p.length !== 4 || p.some(x => Number.isNaN(x) || x < 0 || x > 255)) return false;
  const [a, b] = p;
  if (a === 0 || a === 10 || a === 127 || a >= 224) return false;
  if (a === 169 && b === 254) return false;                    // link-local / cloud metadata
  if (a === 172 && b >= 16 && b <= 31) return false;           // rfc1918
  if (a === 192 && b === 168) return false;                    // rfc1918
  if (a === 192 && b === 0) return false;                      // protocol assignments
  if (a === 100 && b >= 64 && b <= 127) return false;          // CGNAT
  if (a === 198 && (b === 18 || b === 19)) return false;       // benchmark net
  return true;
}

async function guard(raw) {
  let u;
  try { u = new URL(raw); } catch { throw Object.assign(new Error('not a valid URL.'), { code: 'BadUrl' }); }
  if (!/^https?:$/.test(u.protocol)) throw Object.assign(new Error('only http(s) URLs.'), { code: 'BadUrl' });
  if (u.username || u.password) throw Object.assign(new Error('credentials in URLs are not allowed.'), { code: 'BadUrl' });
  const host = u.hostname;
  if (net.isIP(host)) {
    if (!isPublicIp(host)) throw Object.assign(new Error('that address is not public.'), { code: 'NotPublic' });
    return u;
  }
  const addrs = await dns.lookup(host, { all: true }).catch(() => []);
  if (!addrs.length || !addrs.some(a => isPublicIp(a.address)))
    throw Object.assign(new Error('host does not resolve to a public address.'), { code: 'NotPublic' });
  return u;
}

function extract(html) {
  const title = ((html.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || [])[1] || '').trim();
  const text = html
    .replace(/<(script|style|noscript|svg|head|template)[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>').replace(/&#39;|&apos;/g, "'").replace(/&quot;/g, '"')
    .replace(/\s+/g, ' ').trim();
  return { title, text: text.slice(0, MAX_OUT), truncated: text.length > MAX_OUT };
}

export default async function handler(req, res) {
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') return res.status(405).json({ error: 'MethodNotAllowed', message: 'POST required' });
  const url = String((req.body || {}).url || '').trim();
  if (!url || url.length > 2000) return res.status(400).json({ error: 'BadRequest', message: 'url is required.' });
  try {
    let current = (await guard(url)).toString();
    let resp = null;
    for (let i = 0; i <= MAX_REDIRECTS; i++) {
      resp = await fetch(current, {
        redirect: 'manual',
        signal: AbortSignal.timeout(TIMEOUT_MS),
        headers: { 'User-Agent': 'BARS-readonly-browse/1.0', Accept: 'text/html,text/plain,*/*' },
      });
      if (resp.status >= 300 && resp.status < 400 && resp.headers.get('location')) {
        const next = new URL(resp.headers.get('location'), current);
        current = (await guard(next.toString())).toString();   // every hop re-validated
        continue;
      }
      break;
    }
    const ct = resp.headers.get('content-type') || '';
    const buf = Buffer.from(await resp.arrayBuffer());
    if (buf.length > MAX_BYTES) return res.status(413).json({ ok: false, error: 'TooLarge', message: 'page is over the 2MB read cap.' });
    if (!/html|text|json|xml/.test(ct))
      return res.status(415).json({ ok: false, error: 'UnsupportedType', message: `that page is ${ct || 'an unknown type'} - read-only browse handles web pages and text.` });
    const { title, text, truncated } = extract(buf.toString('utf8'));
    return res.status(200).json({ ok: true, url: current, status: resp.status, title, text, truncated, bytes: buf.length, timestamp: new Date().toISOString() });
  } catch (e) {
    const code = e.code === 'NotPublic' ? 403 : e.code === 'BadUrl' ? 400 : 502;
    return res.status(code).json({ ok: false, error: e.code || 'FetchFailed', message: e.message || 'fetch failed' });
  }
}
