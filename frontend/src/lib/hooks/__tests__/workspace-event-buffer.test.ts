/**
 * Unit tests for the WorkspaceEventBuffer telemetry batcher.
 *
 * The buffer is best-effort: every failure mode must be silent. We pass a
 * stub sender via the constructor so we never touch real `fetch`.
 */
import { describe, expect, it, vi } from "vitest";
import {
  WorkspaceEventBuffer,
} from "@/lib/hooks/use-readiness-events";

describe("WorkspaceEventBuffer", () => {
  it("buffers events under the threshold then flushes on flush()", async () => {
    const sender = vi.fn().mockResolvedValue({ recorded: 3, skipped: 0 });
    const buffer = new WorkspaceEventBuffer(sender);

    buffer.push({ view: "overview", event: "viewed" });
    buffer.push({ view: "overview", event: "scrolled" });
    buffer.push({ view: "proof", event: "viewed" });

    // Below the BATCH_LIMIT — sender should not have fired yet.
    expect(sender).not.toHaveBeenCalled();
    expect(buffer.size).toBe(3);

    await buffer.flush();

    expect(sender).toHaveBeenCalledTimes(1);
    expect(sender).toHaveBeenCalledWith([
      { view: "overview", event: "viewed" },
      { view: "overview", event: "scrolled" },
      { view: "proof", event: "viewed" },
    ]);
    expect(buffer.size).toBe(0);

    // Second flush with an empty buffer is a no-op (no extra send).
    await buffer.flush();
    expect(sender).toHaveBeenCalledTimes(1);
  });

  it("drops gracefully when the sender rejects", async () => {
    const sender = vi.fn().mockRejectedValue(new Error("network down"));
    const buffer = new WorkspaceEventBuffer(sender);

    buffer.push({ view: "overview", event: "viewed" });

    // Must not throw — telemetry is best-effort.
    await expect(buffer.flush()).resolves.toBeUndefined();

    // The failed batch is intentionally NOT requeued (prevents unbounded
    // growth if the backend is wedged), so the buffer should now be empty.
    expect(buffer.size).toBe(0);
    expect(sender).toHaveBeenCalledTimes(1);
  });
});
