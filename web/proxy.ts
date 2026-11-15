// Page lock for the hosted dashboard (Next 16 "proxy", formerly middleware).
// Off unless SITE_ACCESS_CODE is set (Vercel env), so local dev is unchanged.
// Accepts: cookie firstin_key=<code> (set by /signin), ?key=<code> (kiosk links; becomes the
// cookie), or Basic auth with password = code (curl). Otherwise redirects to /signin.
import { NextResponse, type NextRequest } from "next/server";

const COOKIE = "firstin_key";

async function digest(s: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
}

/** Constant-time comparison (fixed-length SHA-256 digests, no early exit). */
async function same(given: string | null | undefined, code: string): Promise<boolean> {
  if (!given) return false;
  const [a, b] = await Promise.all([digest(given), digest(code)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

function basicPassword(header: string | null): string | null {
  if (!header?.toLowerCase().startsWith("basic ")) return null;
  try {
    const pair = atob(header.slice(6).trim());
    return pair.includes(":") ? pair.slice(pair.indexOf(":") + 1) : null;
  } catch {
    return null;
  }
}

const cookieOpts = (req: NextRequest) => ({ path: "/", sameSite: "lax" as const, secure: req.nextUrl.protocol === "https:" });

export async function proxy(req: NextRequest) {
  const code = process.env.SITE_ACCESS_CODE?.trim();
  if (!code || req.nextUrl.pathname === "/signin") return NextResponse.next();

  const key = req.nextUrl.searchParams.get("key");
  if (key !== null) {
    const clean = req.nextUrl.clone();
    clean.searchParams.delete("key");
    if (await same(key, code)) {
      const res = NextResponse.redirect(clean);
      res.cookies.set(COOKIE, key, cookieOpts(req));
      return res;
    }
  }

  const cookie = req.cookies.get(COOKIE)?.value;
  if (await same(cookie, code)) return NextResponse.next();

  const basic = basicPassword(req.headers.get("authorization"));
  if (await same(basic, code)) {
    const res = NextResponse.next();
    res.cookies.set(COOKIE, code, cookieOpts(req));
    return res;
  }

  const signin = new URL("/signin", req.url);
  const next = req.nextUrl.clone();
  next.searchParams.delete("key");
  signin.searchParams.set("next", next.pathname + next.search);
  if (cookie || key !== null) signin.searchParams.set("error", "1");
  return NextResponse.redirect(signin);
}

export const config = {
  // everything except build assets and public files (maplibre worker, images, fonts)
  matcher: ["/((?!_next/static|_next/image|favicon\\.ico|.*\\.(?:mjs|js|css|map|png|jpe?g|webp|svg|ico|woff2?|txt)$).*)"],
};
