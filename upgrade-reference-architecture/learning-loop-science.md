# The Learning Loop — the Science (companion to G4 + G5)

> **Status:** v1 reference (research-grounded, 2026-06). Companion to G4 (feedback) + G5 (flywheel/
> fine-tuning). The *methodology* behind continuous improvement — feedback signal science,
> preference-data science, and the fine-tuning decision discipline.

## 0. The law
**Improvement comes from reality, not guessing — but raw feedback must never become the eval set.**
Feedback *informs* labels; the regression set stays separately curated. Otherwise the loop optimizes
the metric instead of the product (Goodhart).

## 1. Feedback signal science
- **Explicit** (thumbs, ratings, corrections, regenerate-pairwise, HITL): *intentional but sparse
  and biased* (thumbs skew, selection bias).
- **Implicit** (abandonment, re-ask, copy, dwell, tool-retry): *abundant but noisy* — abandonment
  can mean "satisfied and left." Calibrate every implicit signal against a real outcome.
- **Downstream outcome** (ticket resolved? PR merged? task completed?) is the **gold** signal —
  weight it highest.
- **Pairwise > absolute:** the ChatGPT *regenerate → better/worse/same* prompt yields a clean
  pairwise preference (same reason pairwise beats absolute in eval-science).
- **Combine all three layers** — no single signal is trustworthy alone.

## 2. Preference-data science
- **DPO defines an implicit reward without a separate reward model** — and **implicit preference
  data from production is abundant and low-cost** (acquired passively, no labeling overhead).
- **Shallow preference signals:** the distinguishing signal often sits in *early tokens*; models
  trained on truncated preferences can match full-length — cheaper, and a hint about what to capture.
- **Data selection at scale:** as preference sets grow, select the most *informative* examples
  (e.g., by DPO implicit reward gap) rather than training on everything.

## 3. The flywheel (MAPE control loop)
Monitor (collect signals) → Analyze (label + curate) → Plan (eval-gate the candidate) → Execute
(fine-tune → shadow → canary). This is Doc-1's drift/closed-loop applied to agents; HITL-in-the-loop
makes it self-improving. Production results to anchor expectations: routing **70B → 8B @ 96%, 10×
smaller, 70% faster**; query-rephrasal fine-tune **+3.7% acc, 40% latency**.

## 4. Fine-tuning decision discipline (usually: don't)
Walk the tree before training anything:
1. Done the **harness/context/prompt** work? 80% of "need to fine-tune" is "need better tool
   descriptions / context assembly."
2. **Verifiable** task (programmatic checker)? → RLVR/RFT fits. Else SFT/DPO.
3. Have/can-generate **≥~1000 quality examples**? Below that, few-shot beats fine-tuning.
4. Volume high enough that **cost dominates**, or **latency-critical**? → distillation/LoRA.
→ Fine-tune only if (3) AND (verifiable or DPO-data) AND (volume OR latency). Otherwise keep
iterating the harness. **Improvements to the harness compound; a fine-tune is one-time.**

- **Per-tenant LoRA** + multi-LoRA serving = per-customer quality without per-customer models.
- **Distillation** (frontier teacher → small student) for high-volume narrow steps (10–100× cost).

## 5. The failure modes that wreck learning loops
- **Reward hacking** → held-out verifier ≠ training verifier; **multi-objective** reward (accuracy ×
  faithfulness × readability) — DeepSeek-R1-Zero's readability collapse is the canonical caution.
- **Entropy collapse (RLVR/GRPO)** → narrow-and-confident; validate on OOD; monitor diversity.
- **Eval contamination** → the firewall (G4): raw feedback never auto-enters the regression set.
- **Distillation bias amplification** → human spot-check + eval for known teacher failures.
- **Goodhart on the proxy** → keep the gold outcome signal in the loop, not just the proxy.

## 6. Sources
- Explicit/implicit feedback (Nebuly): https://www.nebuly.com/blog/explicit-implicit-llm-user-feedback-quick-guide
- Adaptive Data Flywheel — MAPE (arXiv:2510.27051): https://arxiv.org/html/2510.27051v1
- Agent-in-the-Loop data flywheel (arXiv:2510.06674): https://arxiv.org/html/2510.06674v2
- DPO implicit rewards (arXiv:2406.09760): https://arxiv.org/pdf/2406.09760
- ImplicitRM — reward modeling from implicit preferences (arXiv:2603.23184): https://arxiv.org/pdf/2603.23184
- NVIDIA data flywheel: https://developer.nvidia.com/blog/maximize-ai-agent-performance-with-data-flywheels-using-nvidia-nemo-microservices/
