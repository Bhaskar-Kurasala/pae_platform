# B3 companion — Sandbox research (live, 2026-06-08)

> Live multi-source research (deep-research harness, run `wf_ba4c61a0-808`): **23 sources fetched,
> 112 claims extracted, 25 adversarially verified — 23 confirmed, 2 refuted.** Feeds **B3
> tool-supply-chain-sandbox** and the **dedicated sandbox phase** (P3a's successor). Per ARIA build
> standard, libraries verified live, not from memory. Versions are point-in-time (2026-06-08) and
> fast-moving — **re-validate before production reliance.**

## The load-bearing premise (3-0 confirmed)

**A plain Docker / Podman / k3d container is NOT a security boundary for untrusted code.** Containers
share the host kernel via namespaces/cgroups/seccomp; a single kernel exploit escapes. The
vendor-neutral **CoSAI WS4 (OASIS) MCP-security standard** (published 2026-01-27; contributors
Google/IBM/Microsoft/NVIDIA/Meta/Snyk) states verbatim that MCP servers which access files, run
commands, open network connections, or execute LLM-generated code **"should always run in a sandbox"**
and **"Containers should not be relied upon as a strong security boundary… Consider additional
sandboxing (gVisor, Kata Containers, SELinux sandboxes)."** Corroborated by CVE-2025-23266
(NVIDIAScape container escape) and the 2026 "Your Container Is Not a Sandbox" consensus.
Source: `github.com/cosai-oasis/ws4-secure-design-agentic-systems/blob/main/model-context-protocol-security.md`

## Isolation tiers (strongest → weakest), verified

| Tier | Mechanism | Verified note | Source |
|---|---|---|---|
| **microVM (Firecracker / libkrun)** | KVM hardware virt, **separate guest kernel per sandbox**; threat model treats **all guest vCPU threads as malicious from boot**; <125ms boot, <5MB/VM; seccomp by default | Strongest practical tier; same KVM tech underpinning AWS Lambda/Fargate | `firecracker-microvm/firecracker/docs/design.md` |
| **gVisor (`runsc`)** | userspace kernel (**Sentry**) intercepts + independently reimplements ~200 syscalls; **no untrusted syscall reaches the host**; Sentry itself makes only ~68 seccomp-restricted host calls; apps can't craft host syscall args | Structurally reduces (not eliminates) host attack surface; blocked real kernel bug CVE-2020-14386; runs as a **Docker runtimeClass** — lighter than a VM; **weaker than a microVM** (Sentry compromise = residual risk) | `gvisor.dev/docs/architecture_guide/security` |
| **plain container** | namespaces + cgroups + seccomp, **shared host kernel** | **Not a boundary** for untrusted code (premise above) | CoSAI WS4 |

## Self-hostable / local-first options (verified)

- **microsandbox** — Apache-2.0, **v0.5.5 (released 2026-06-05, 38+ releases)**, **libkrun microVMs**
  (KVM on Linux / Hypervisor.framework on Apple Silicon — a true guest kernel per sandbox, NOT
  namespace/cgroup containers), and **ships a native MCP server** (`npx -y microsandbox-mcp`).
  Strongest open-source local-first option to run untrusted code NOW. ⚠️ README labels it **beta** —
  pin + validate; needs Linux+KVM. Source: `github.com/microsandbox/microsandbox`
- **E2B** — Apache-2.0 open-core (JS+Python SDKs), **Firecracker microVMs over KVM** ("each sandbox is
  a Firecracker microVM made to run untrusted workflows"), self-host via Terraform (`e2b-dev/infra`).
  Self-host matrix (2-1 vote): **GCP production, AWS beta (needs bare-metal instances for Firecracker —
  nested KVM unavailable on most managed instance types), Azure none.** "Clean local→AWS path" is real
  but AWS is beta. Sources: `e2b.dev`, `github.com/e2b-dev/E2B`
- **llm-sandbox** — ⚠️ **NOT an independent security boundary.** Only Docker/Kubernetes/Podman
  backends; NO Firecracker/microVM/gVisor. Its boundary == the underlying container runtime (not a true
  boundary); it only layers policy/resource management. It *can* be pointed at a gVisor runtimeClass but
  does not manage that itself. Choosing it does NOT convert a container into a real boundary.
  Source: `github.com/vndee/llm-sandbox`
- **Docker MCP Gateway / MCP Catalog** — Docker's pattern for fronting MCP servers (allowlist, auth,
  audit) — relevant to the *gateway* layer, not a kernel boundary on its own.
  Source: `docker.com/blog/docker-mcp-gateway-secure-infrastructure-for-agentic-ai`

## AWS production target (verified) + the critical warning

- **Bedrock AgentCore Runtime / Code Interpreter** — **per-session microVM** isolation (Firecracker-
  style KVM, same tech as Lambda/Fargate); each session gets a dedicated microVM, **terminated +
  memory-sanitized** after the session; AWS markets "complete session isolation… thousands of sessions
  in seconds." Code Interpreter runs agent-generated Python/JS/TS in those microVMs — BeyondTrust calls
  it the strongest compute-level isolation among agent-as-a-service vendors. (Nuance: AWS docs say
  "microVM" not literally "Firecracker"; AgentCore does not enforce session-to-user mapping — client
  responsibility.) Sources: AWS `bedrock-agentcore` runtime-sessions doc + `agentcore/pricing`.
- **⚠️ CRITICAL — marketed-secure ≠ true boundary (3-0 confirmed):** AgentCore Code Interpreter's
  **"Sandbox" network mode**, originally advertised as "complete isolation with no external access,"
  **permits public DNS A/AAAA queries**, which BeyondTrust/Phantom Labs weaponized into a bidirectional
  **DNS-based command-and-control + data-exfiltration** channel (CVSS 7.5, disclosed 2025-09-01). AWS
  declared it *intended functionality*, declined to patch, and only updated docs. **True network
  isolation requires VPC Mode** (VPC endpoints, security groups, NACLs, Route53 DNS Firewall). The
  compute boundary held; the advertised network boundary did not.
  Sources: `beyondtrust.com/blog/entry/pwning-aws-agentcore-code-interpreter`,
  `github.com/BeyondTrust/pwning-agentcore-code-interpreter`
- **Two AWS marketing claims REFUTED (0-3, excluded):** "complete separation from other workloads and
  AWS infrastructure," and "a fully isolated network mode that prevents agent code reaching external
  systems." (`aws.amazon.com/blogs/machine-learning/introducing-the-amazon-bedrock-agentcore-code-interpreter`)

## What sandboxing does NOT solve (MCP-specific, verified)

Compute isolation does not address **MCP supply-chain** (untrusted third-party MCP-server provenance)
or **prompt-injection-via-tool-output** (retrieved/tool content as an injection vector). These need
pinning + provenance + output-treated-as-untrusted, *in addition to* the kernel boundary. (A Firecracker
VM can still happily exfiltrate data if egress is open — hence egress control matters more than the VM
for the dominant breach class.) Sources: OWASP MCP Top-10 MCP05 (command injection);
`simonwillison.net/2025/Apr/9/mcp-prompt-injection`.

## Decision for ARIA (staged; threat-model-driven)

The threat surface differs by **what runs** — ARIA must not over- or under-build:

1. **P3a (retrieval over first-party tools) — live need is content + egress, NOT a microVM.** The
   deep-research agent calls *retrieval* tools, so live threats are (a) **prompt-injection-via-tool-
   output** and (b) **network egress / SSRF / exfil** — not arbitrary untrusted code. Controls (cheap,
   mostly reuse): a thin **`SandboxProvider` seam** (`NoSandboxProvider`); **default-deny egress +
   domain allowlist** (model the VPC-Mode boundary locally NOW); route tool output through the **P1
   injection-screen** as untrusted; **capability-scoped tools** (read-only `search`/`fetch`);
   tool-manifest **version pinning + source provenance**. *(This is what P3a ships.)*
2. **Untrusted-code execution → the DEDICATED SANDBOX PHASE (P3a's successor; implements B3) → P4
   hardening.** When the agent runs a **`code_exec`/analysis tool** (LLM-generated Python = untrusted by
   definition), plug a REAL backend into the seam: **gVisor `runsc` primary** (Docker runtimeClass —
   works in the WSL2/Docker/k3d env, teachable userspace-kernel model, GKE-Sandbox prod story) + a
   **microVM/libkrun (microsandbox) demo**; egress/resource controls; **escape/exfil break-its**; a
   student `concept.md`; AWS lift → **AgentCore Runtime + MANDATORY VPC Mode** (never the Sandbox
   network mode), or self-hosted E2B/Firecracker (beta, bare-metal). The seam makes this a **swap, not a
   redesign.**
3. **Never** rely on a plain container as a boundary; **never** trust a marketed network mode without
   verification — enforce egress allowlisting at every tier.

## Open questions carried forward (sandbox phase / P4 / P8)

- microsandbox-MCP-server-fronting-tools vs MCP-under-gVisor-`runsc` — which maps cleanest to AgentCore
  Runtime + VPC Mode? (decide when building the sandbox phase)
- Can ARIA's AWS target run Firecracker/E2B (bare-metal/nested-virt) cost-effectively, or is managed
  **AgentCore Runtime + VPC Mode + Route53 DNS Firewall** the production boundary? (P8 lift)
- Local egress controls to pre-empt the DNS-exfil class (default-deny + DNS sinkhole/allowlist) so the
  local seam already models the VPC-Mode boundary.
- MCP supply-chain + tool-output-injection standards beyond compute isolation (pinning/provenance/
  output-sanitization) — overlaps C2 memory-provenance.

## Caveats (from the research synthesis)

Versions current as of 2026-06-08 and will drift — microsandbox v0.5.5 (3 days old at report time) is
fast-moving and self-labeled BETA. E2B AWS self-host is BETA and needs bare-metal for Firecracker. AWS
docs say "microVM" not literally "Firecracker" for AgentCore (Firecracker attribution is a well-
supported inference, not a verbatim AgentCore statement). The BeyondTrust "stronger than other vendors"
comparison is qualitative editorial, not a benchmark. Isolation is always defense-in-depth, not a single
absolute boundary — even gVisor/Kata don't fully eliminate host-kernel attack surface, and gVisor is
weaker than hardware-virtualized microVMs.

## Sources (primary unless noted)

CoSAI WS4 OASIS MCP-security · `gvisor.dev` security · Firecracker `design.md` (+ DeepWiki threat-model) ·
microsandbox repo · `e2b.dev` + `e2b-dev/E2B` · `vndee/llm-sandbox` · AWS AgentCore runtime-sessions +
pricing · BeyondTrust AgentCore disclosure (+ repo) · OWASP MCP Top-10 (MCP05) · Docker MCP Gateway +
MCP Catalog · `simonwillison.net` MCP prompt-injection · practitioner refs (Northflank, Modal,
`restyler/awesome-sandbox`).
