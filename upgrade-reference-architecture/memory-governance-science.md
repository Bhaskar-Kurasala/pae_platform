# Memory Governance — the Science (companion to C2)

> **Status:** v1 reference (research-grounded, 2026-06). Companion to
> [C2-memory-governance.md](./C2-memory-governance.md). The *architecture* is there; this is the
> *threat model + defense science + measurement.*

## 0. The one law
**Memory is a belief store, and beliefs are harder to defend than actions.** Prompt injection ends
when the conversation closes; **memory poisoning persists across sessions and fires later**,
triggered by unrelated interactions. Defenses that screen *actions* (tool contracts, circuit
breakers, I/O moderation) miss it because the corruption is in *what the agent believes*, not what
it just did. [arXiv:2601.05504; Christian Schneider; OWASP ASI06:2026]

## 1. Attack taxonomy
| Attack | Mechanism | Why it's nasty |
|---|---|---|
| **MINJA** | poison via *normal queries* using plausible reasoning steps | payload is indistinguishable from legit input; **>95% injection, 70% success, no privileges** |
| **AgentPoison** | poison the retrieval/RAG memory corpus | corrupts what gets recalled |
| **MemoryGraft** | transplant attacker beliefs into long-term store | persists across sessions |
OWASP added **memory poisoning as ASI06:2026** to the Agentic Security Top 10.

## 2. Defense primitives (why C2 is shaped the way it is)
1. **Memory contracts** — declare *what an agent is allowed to believe* (kinds, sources, schemas);
   reject out-of-contract memories.
2. **Context provenance tracking** — every memory carries where it came from (run, source, trust).
3. **Cryptographic provenance** — Ed25519-sign each entry at creation; tampered entries detected
   and **quarantined on read**.
4. **Trust scoring + trust-aware retrieval** — low-trust/unvalidated memories are not eligible to
   drive side-effecting decisions (they can inform, not authorize).
5. **Belief-drift detection** — flag when the agent starts *defending beliefs it should never have
   learned* (the behavioral tell of a successful poison).
6. **Promotion gate** — raw → validated → promoted, like code; nothing acts from un-promoted memory.

## 3. The science of evolving memory (consolidation, conflict, decay)
- **Consolidation** merges related episodics into semantics; most frameworks (even Letta) leave the
  automated pipeline unimplemented — production must build it.
- **Conflict** (fact changed: X in March, ¬X in April) → **temporal resolution**: keep both with
  validity windows (Zep/Graphiti style), don't silently overwrite.
- **Decay/eviction** by importance + recency + TTL; freshness scoring on retrieval.
- **Multi-agent consistency** is the hard edge: concurrent writes to one user's memory create
  ordering/visibility races — v1 = last-write-wins + temporal validity, flagged known-weak.
- **Enterprise governance gap:** all 8 major frameworks lack glossary / lineage / entity-resolution
  — ARIA adds these on top of whichever store it picks.

## 4. The 2026 framework landscape (pick by job, don't conflate)
| Framework | Strength |
|---|---|
| **Mem0** | personalization, lowest setup friction |
| **Zep / Graphiti** | temporal knowledge graph (how facts change over time) |
| **LangMem** | LangChain/LangGraph-native; semantic/episodic/procedural |
| **Letta / MemGPT** | long-running agents that manage their own memory |
Market consolidation expected within ~18 months — another reason to keep our governance layer
*above* the chosen store, not coupled to it.

## 5. Measuring memory (eval that's specific to memory)
| Metric | What it catches |
|---|---|
| **poisoning-resistance** | % MINJA/AgentPoison attempts quarantined (red-team corpus) |
| **conflict-handling** | correct answer after a fact changes (temporal benchmark) |
| **stale-fact rate** | acting on outdated beliefs |
| **recall precision/relevance** | retrieves the right memory, not recency-biased noise |
| **cross-tenant isolation** | 0 leakage across `(tenant,user,agent)` |
| **provenance coverage** | % entries signed + quarantine-on-tamper working |

## 6. Sources
- Memory Poisoning Attack & Defense (arXiv:2601.05504): https://arxiv.org/abs/2601.05504
- Persistent memory poisoning (Christian Schneider): https://christian-schneider.net/blog/persistent-memory-poisoning-in-ai-agents/
- SSGM governed-memory framework (arXiv:2603.11768): https://arxiv.org/html/2603.11768v1
- mguard defense library: https://github.com/mguard-ai/mguard
- State of AI Agent Memory 2026: https://mem0.ai/blog/state-of-ai-agent-memory-2026
- AI memory security best practices: https://mem0.ai/blog/ai-memory-security-best-practices
