# Latest-main GPU smoke — PASS

Main: `4ab720e6557b44d07bde471ed52a178795298f1a`. Feature: `d1140b5ec5c320a440fc35b0704f78dbdff31449`.
Full Python/test source overlay from git archive; same pinned CUDA image/model.

29 tests passed, zero failed/skipped, including both previously skipped CUDA
transfer regressions. Three A/B/C trials at a500ms synthetic tool gap, n=1.
All32 output IDs matched producer. B consumed4080 storage tokens, C consumed4080
host tokens; initial device hits0. B/C each read255 unique pages /116981760 bytes.
C published L2 before request submission; no duplicate reads or relevant eviction.
Terminal inflight0/cleanupfalse. Wasted-prefetch normal flush restored139520 slots.

TTFT: A575.05ms, B537.18ms, C182.85ms. This is a correctness/sanity run,
not a new statistically supported performance claim; pinned45-trial data unchanged.

L4, driver580.178.04, CUDA13.0, PyTorch2.13.0+cu130. Exit0.
Conservative wall/charged upper bound: 18.11min, $0.265
(VM+150GiB disk+IPv4, until confirmed deletion; estimate, not invoice).
Created 2026-10-03T16:19:33.216-07:00; deleted 2026-10-03T23:37:40Z. Native55min DELETE plus local60min
timer, neither extended. Guest shutdown then explicit deletion; VM/disk lists empty.

Pinned ToolGap v0.1 unchanged. The latest-main checkpoint/H2D/generation path
is now GPU smoke-validated. No architecture or image changes; no second execution.
