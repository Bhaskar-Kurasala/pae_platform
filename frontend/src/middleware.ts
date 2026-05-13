import { NextResponse, type NextRequest } from "next/server";

// Edge gate for the admin console. The cookie is a presentation hint mirrored
// from the zustand auth store ([stores/auth-store.ts]); the backend remains
// the authoritative gate (returns 403 on token-role mismatch).
//
// Why: the existing client-side guard in [admin/layout.tsx] flashes admin
// chrome for ~1 frame before redirecting non-admins. Edge middleware cuts
// that flicker by redirecting before any HTML ships.
const ROLE_COOKIE = "pae_role";

function addSecurityHeaders(response: NextResponse): NextResponse {
  response.headers.set(
    "Strict-Transport-Security",
    "max-age=63072000; includeSubDomains; preload"
  );
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=(), payment=()"
  );
  response.headers.set(
    "Content-Security-Policy-Report-Only",
    "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' https://api.razorpay.com https://*.sentry.io; font-src 'self' data:; frame-src https://api.razorpay.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; report-uri /api/v1/csp-report"
  );
  return response;
}

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (!pathname.startsWith("/admin"))
    return addSecurityHeaders(NextResponse.next());

  const role = req.cookies.get(ROLE_COOKIE)?.value;
  if (role === "admin") return addSecurityHeaders(NextResponse.next());

  // Anonymous → login with return path. Wrong role → /today (the student home).
  if (!role) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + req.nextUrl.search)}`;
    return addSecurityHeaders(NextResponse.redirect(url));
  }
  const url = req.nextUrl.clone();
  url.pathname = "/today";
  url.search = "";
  return addSecurityHeaders(NextResponse.redirect(url));
}

export const config = {
  matcher: ["/admin/:path*"],
};
