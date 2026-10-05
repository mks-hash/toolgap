# Bounded release review — 2026-10-04

Reviewed scheduler submission/admission/idle/pause/abort and the control manager,
with existing finite-I/O fixtures. No scheduler or cache-ownership redesign.

- Cancellation/TTL: existing release_aborted_request owns abort; allocated reads
  retain their tail until terminal ACK; new control work waits for cleanup.
- Early continuation: exact token prefix and cache salt join; ordinary matching
  and H2D resume after publication; unrelated/replacement Req does not inherit
  cached join. The immutable origin prefix is compared once per matching object.
- Request abort: independent restore may continue until completion/TTL; the one
  retained waiting Req is released at terminal/cancel. This is bounded, not an
  immediate reference-drop guarantee on generation abort.
- Repeated IDs: 32 historical outcomes, no residency lease; new ID after eviction.
- Cleanup: unique private handle, existing terminal ACK consumption, accounting
  discarded after drain. Published host slots are intentionally ordinary cache.
- Backend mismatch: found a missing guard after dynamic replacement. Release
  adds six runtime lines rejecting changed/disabled backend on submit, tested
  with a replacement fixture. Existing status/cancel still work.
- Model mismatch: fixed-model process required. Hot weight updates and KV from
  another model are unsupported; token IDs alone cannot authenticate KV identity.
  Documentation requires matching model/tokenizer/salt/store and restart isolation.

Release has **341 runtime additions across five files**, versus the 335-line
GPU-validated implementation. Guard does not change normal file restore or
inference; it has CPU validation only. Two new CPU tests bring total to 27.

## Checks performed

- Clean checkout at exact upstream SHA; prerequisite then feature apply: PASS.
- Whitespace and shell syntax; Python compile; reverse patch checks: PASS.
- Packaged checkout imports plus controller/API suite: 27 passed, zero failed.
- Offline evidence replay: 45 unique trials, identical output correctness,
  exact consumption/page counts, medians, terminal cleanup and wasted flush: PASS.
- TTFT chart generated from recorded rows and visually checked.
- Runtime demo is the validated A/B/C runner restricted to one repetition and
  a synthetic 500ms gap, plus producer and no-continuation cleanup. Entrypoint
  syntax and offline replay checked; release Dockerfile/GPU demo were not newly
  built/executed. No new GPU costs were incurred.

Existing full GPU validation remains the evidence for the measured implementation.
This release does not claim clean-machine CUDA dependency installation or new
GPU execution of the assembled release image. Those are reproduction instructions,
not reported test passes. Historical Stage reports retain their original status;
README and this file describe the release status.
