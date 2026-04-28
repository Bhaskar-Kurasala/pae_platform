import { redirect } from "next/navigation";

/**
 * P-Practice1: /studio is now a permanent redirect to the unified
 * /practice surface (Capstone mode). The capstone bundle now lives inside
 * the Practice workspace alongside the exercise catalog.
 */
export default function StudioRedirect() {
  redirect("/practice?mode=capstone");
}
