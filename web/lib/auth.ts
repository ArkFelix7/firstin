// Hosted-mode access code (deploy/DEPLOY.md). Locally (no NEXT_PUBLIC_API_URL, or one on
// localhost/LAN) none of this is active and no token is ever sent.
//
// - API (FastAPI, FIRSTIN_ACCESS_CODE): `Authorization: Bearer <code>` on fetch,
//   `?key=<code>` on EventSource / <audio> / <img> / static URLs.
// - Pages (proxy.ts, SITE_ACCESS_CODE): cookie `firstin_key`, set by /signin. The API token falls
//   back to that cookie, so one code entry unlocks pages and API when both codes are the same.

export const TOKEN_KEY = "firstin_key";

/** True when NEXT_PUBLIC_API_URL points at a non-local API (the only case that may need a code). */
export function remoteApi(): boolean {
  const env = process.env.NEXT_PUBLIC_API_URL;
  if (!env) return false;
  try {
    const h = new URL(env).hostname;
    return !/^(localhost|127\.\d+\.\d+\.\d+|\[::1\]|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|.*\.local)$/.test(h);
  } catch {
    return false;
  }
}

function cookieToken(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|;\s*)firstin_key=([^;]*)/);
  return m ? decodeURIComponent(m[1]) || null : null;
}

/** Current access code: sessionStorage first, then the page cookie set by the sign-in screen / proxy. */
export function getToken(): string | null {
  if (typeof window === "undefined" || !remoteApi()) return null;
  try {
    return sessionStorage.getItem(TOKEN_KEY) || cookieToken();
  } catch {
    return cookieToken();
  }
}

/** API token for this tab only (the gate's sign-in screen). Never touches the page cookie. */
export function setApiToken(code: string) {
  try {
    sessionStorage.setItem(TOKEN_KEY, code);
  } catch {}
}

/** Page cookie checked by proxy.ts (the /signin screen). Session cookie, not HttpOnly so the API can reuse it. */
export function setSiteCookie(code: string) {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${TOKEN_KEY}=${encodeURIComponent(code)}; Path=/; SameSite=Lax${secure}`;
}

/** Headers for fetch() to the API. Empty when no code is in use. */
export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}
