import { Header } from "./header";
import { Footer } from "./footer";

interface PublicLayoutProps {
  children: React.ReactNode;
}

/**
 * Wrapper layout for all public (Zone 1 — marketing) pages.
 *
 * Renders the sticky Header, a flex-1 main content area,
 * and the multi-column Footer.
 */
export function PublicLayout({ children }: PublicLayoutProps) {
  return (
    <div className="min-h-screen flex flex-col">
      <Header />
      <main className="flex-1">{children}</main>
      <Footer />
    </div>
  );
}
