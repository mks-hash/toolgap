# API and ownership

Endpoint: `POST /hicache/prefetch`, existing SGLang ADMIN_OPTIONAL authentication.
Do not expose an unauthenticated admin endpoint on a public interface.

Submit:
```json
{"action":"submit","operation_id":"trajectory-1-tool-1","input_ids":[123,456],"cache_salt":"trajectory-1","ttl_ms":10000}
```
Status/cancel:
```json
{"action":"status","operation_id":"trajectory-1-tool-1"}
```
```json
{"action":"cancel","operation_id":"trajectory-1-tool-1"}
```
Token examples show the shape only: use an exact bounded prefix above the storage
threshold (64 in the benchmark). Align down to full pages (16 tokens in the
benchmark). An exact 4096-token continuation normally restores its first 4080
full-page tokens, excluding the final token. Model, tokenizer, prefix and salt
must match the KV source. Salt must also be present on `/generate` if used.

Response: `{ "success": true, "message": "", "result": {...} }`.
Invalid requests return HTTP 400 with success=false and a message.
Result includes operation_id, state, requested_tokens, restored_tokens,
restored_bytes, elapsed_ms, cleanup_pending, host_available_tokens, inflight_tokens.
`restored_tokens` counts newly loaded storage span, not existing cached pages.

One active operation; 32 recent records. operation_id is 1..128 characters,
cache_salt ≤256 characters, TTL 1..60000ms. Same ID with same page-normalized
prefix/salt/TTL returns its historical outcome, even after cache eviction.
Different payload under the same retained ID is rejected. Once an ID falls out
of the bounded registry it can be reused; use unique IDs instead. Status for an
unknown/forgotten ID returns an error. New ID is required to retry a restore.

States: RUNNING, SUCCESS, MISS, FAILURE, CANCELLED, EXPIRED; CACHED is an already
matched prefix and DECLINED means existing controller admission did not enqueue.
Partial MISS may have restored a span; counters and normal matching determine
usable pages. FAILURE corresponds to finite backend I/O failure.

TTL cancels in-flight work, not published cache residency. During a cancelled
allocated read, cleanup_pending stays true until the existing terminal ACK drains;
new control work is rejected until this tail has relinquished ownership.
A cancelled query without allocation can finish later, but cannot allocate or
publish into a replacement handle. Handles are unique independently of user IDs.
The lifecycle prerequisite consumes terminal ACK once to avoid double reclamation.

Matching early continuation joins an in-flight restore. An unrelated prefix/salt
or replacement Req does not inherit the join. The queued request reference is
released at completion/cancel. Cancelling generation does not imply cancel of
the independent restore: explicitly cancel its operation if no continuation is
expected. A published restore is ordinary evictable L2; cancelling SUCCESS does
not remove its shared KV. No pin, lease, demote or proactive H2D is provided.

Fixed-model process only. Do not hot-update weights or reuse another model's
storage namespace. Dynamic backend changes require restarting the server for
new control submits. Status/cancel can still report/clean the existing record.
