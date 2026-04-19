import { StubPage } from "../_components/stub-page";

export const metadata = { title: "Security · PAE Platform" };

export default function SecurityPage() {
  return (
    <StubPage
      title="Security"
      description="Data is encrypted in transit (TLS) and at rest (AES-256). Access tokens are short-lived; secrets are never logged. Report vulnerabilities to security@pae.platform — we respond within 48 hours."
    />
  );
}
