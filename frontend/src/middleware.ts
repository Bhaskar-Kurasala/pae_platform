import { NextResponse, type NextRequest } from "next/server";

// Edge gate for the admin console. The cookie is a presentation hint mirrored
// from the zustand auth store ([stores/auth-store.ts]); the backend remains
// the authoritative gate (returns 403 on token-role mismatch).
//
// Why: the existing client-side guard in [admin/layout.tsx] flashes admin
// chrome for ~1 frame before redirecting non-admins. Edge middleware cuts
// that flicker by redirecting before any HTML ships.
const ROLE_COOKIE = "pae_role";

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (!pathname.startsWith("/admin")) return NextResponse.next();

  const role = req.cookies.get(ROLE_COOKIE)?.value;
  if (role === "admin") return NextResponse.next();

  // Anonymous → login with return path. Wrong role → /today (the student home).
  if (!role) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname + req.nextUrl.search)}`;
    return NextResponse.redirect(url);
  }
  const url = req.nextUrl.clone();
  url.pathname = "/today";
  url.search = "";
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/admin/:path*"],
};
