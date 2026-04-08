import { PublicLayout } from "@/components/layouts/public-layout";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <PublicLayout>{children}</PublicLayout>;
}
