import { Suspense } from "react";
import { StudioScreen } from "@/components/v8/screens/studio-screen";

export const metadata = {
  title: "Studio · CareerForge",
};

export default function StudioPage() {
  return (
    <Suspense fallback={null}>
      <StudioScreen />
    </Suspense>
  );
}
