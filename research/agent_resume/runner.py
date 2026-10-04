"""Live multi-round harness: actual model IDs and useful tool results."""

import asyncio
import hashlib
import json
import time
import uuid

from .adapters import aligned_prefix
from .workloads import SCHEMA


class GenerationTransport:
    """Borrow an explicitly configured server. Never launch, flush or provision."""

    def __init__(self, http, *, max_new_tokens=256):
        self.http = http
        self.max_new_tokens = max_new_tokens
        self.request_id_prefix = "tg-"

    async def generate(self, ids, salt):
        submitted = time.monotonic_ns()
        first, last = None, None
        rid = self.request_id_prefix + uuid.uuid4().hex
        payload = dict(
            input_ids=ids,
            rid=rid,
            cache_salt=salt,
            stream=True,
            return_logprob=True,
            sampling_params=dict(
                temperature=0, max_new_tokens=self.max_new_tokens, sampling_seed=42
            ),
        )
        async with self.http.stream("POST", "/generate", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: ") or line[6:] == "[DONE]":
                    continue
                last = json.loads(line[6:])
                if "error" in last:
                    raise RuntimeError(str(last["error"]))
                if last.get("output_ids") and first is None:
                    first = time.monotonic_ns()
        if last is None or first is None:
            raise ValueError("Server did not return generated token IDs")
        ids = last["output_ids"]
        if (
            not isinstance(ids, list)
            or not ids
            or any(type(i) is not int or i < 0 for i in ids)
        ):
            raise ValueError("Invalid generated token IDs")
        return dict(
            output_ids=ids,
            submitted_ns=submitted,
            first_token_ns=first,
            completed_ns=time.monotonic_ns(),
            meta_info=last.get("meta_info", {}),
            rid=rid,
        )


async def settle_owned(policy, submissions, *, session_id, abandoned, timeout=3):
    """Bounded observation/cancel; time expiry is never proof of reclamation."""
    records = []

    async def settle():
        leases = []
        for task in submissions:
            lease = await asyncio.shield(task)
            leases.append(lease)
        # An interrupted submit can retain ownership without returning a lease.
        if (
            policy.active is not None
            and policy.active.session_id == session_id
            and policy.active not in leases
        ):
            leases.append(policy.active)
        for lease in leases:
            state = await (lease.cancel() if abandoned else lease.status())
            while state.get("cleanup_pending"):
                await asyncio.sleep(0.01)  # control polling, not tool latency
                state = await lease.status()
            lease.finish(used_tokens=0 if abandoned else None)
            records.append(
                dict(state=state, decision=lease.decision, timing=lease.timing)
            )

    try:
        await asyncio.wait_for(settle(), timeout)
    except Exception as exc:
        records.append(
            dict(cleanup_confirmed=False, error=f"{type(exc).__name__}: {exc}")
        )
    finally:
        for task in submissions:
            if not task.done():
                task.cancel()
        await asyncio.gather(*submissions, return_exceptions=True)
    if policy.active is not None and policy.active.session_id == session_id:
        records.append(
            dict(cleanup_confirmed=False, retained_owner=policy.active.state)
        )
    return records


def initial_messages(adapter, task):
    return adapter.normalize_messages(
        [
            dict(
                role="system",
                content="Use repository tools to obtain evidence. Return final JSON only: "
                '{"answer":"value","evidence":[{"path":"file","line":1}]}. '
                "Call one tool at a time. Never invent file/line evidence.",
            ),
            dict(
                role="user",
                content=task["question"]
                + (
                    "\n\nPinned source context:\n" + task["context_pack"]
                    if task.get("context_pack")
                    else ""
                ),
            ),
        ]
    )


async def run_task(
    adapter,
    tokenizer,
    model,
    tools,
    task,
    *,
    policy=None,
    hint=None,
    max_tool_rounds=4,
    context_limit=8192,
    on_record=None,
    cache_salt=None,
    on_boundary=None,
):
    """One live trajectory; no prescribed model decisions or forced cache state."""
    row = dict(
        task_id=task["id"],
        family=adapter.family,
        mode="proactive" if policy else "request_time",
        status="FAILED",
        task_success=False,
        tools=[],
        generations=[],
        prefetch=[],
        cache_state="UNMEASURED",
        physical_io="UNMEASURED",
        started_ns=time.monotonic_ns(),
        cache_salt=cache_salt if cache_salt is not None else uuid.uuid4().hex,
    )
    messages = initial_messages(adapter, task)
    submissions = []

    async def submit_step(step):
        lease = await policy.submit(
            row["cache_salt"],
            step["prefix_ids"],
            cache_salt=row["cache_salt"],
            hint=hint,
        )
        step["prefetch_operation_id"] = lease.operation_id
        step["prefetch_decision"] = lease.decision
        return lease

    try:
        ids = adapter.prompt(tokenizer, messages, SCHEMA)
        if (
            task.get("initial_input_ids") is not None
            and ids != task["initial_input_ids"]
        ):
            raise ValueError("Prepared native initial token IDs changed")
        for turn in range(max_tool_rounds + 1):
            if len(ids) + getattr(model, "max_new_tokens", 0) > context_limit:
                raise ValueError("Conversation exceeds declared input token limit")
            generation = await model.generate(ids, row["cache_salt"])
            generation["input_ids"] = list(ids)
            row["generations"].append(generation)
            if row["tools"]:
                step = row["tools"][-1]
                step.update(
                    continuation_submitted_ns=generation["submitted_ns"],
                    continuation_first_token_ns=generation["first_token_ns"],
                    continuation_ttft_ms=(
                        generation["first_token_ns"] - generation["submitted_ns"]
                    )
                    / 1e6,
                    tool_dispatch_to_first_token_ms=(
                        generation["first_token_ns"] - step["dispatched_ns"]
                    )
                    / 1e6,
                )
            raw = tokenizer.decode(generation["output_ids"], skip_special_tokens=False)
            call = adapter.parse(raw, {s["function"]["name"] for s in SCHEMA})
            if call is None:
                row["output"] = adapter.strip_end(raw)
                row["task_success"] = tools.grade(task, row["output"], row["tools"])
                row["status"] = "COMPLETED"
                break
            if turn == max_tool_rounds:
                raise ValueError("Tool-round budget exhausted")
            saved = ids + generation["output_ids"]
            prefix = aligned_prefix(saved)
            step = dict(
                call=dict(
                    name=call.name, arguments=call.arguments, call_id=call.call_id
                ),
                boundary_ns=time.monotonic_ns(),
                prefix_ids=prefix,
                prefix_sha256=hashlib.sha256(json.dumps(prefix).encode()).hexdigest(),
            )
            row["tools"].append(step)
            if on_boundary is not None:
                sample_start = time.monotonic_ns()
                step["cache_before_dispatch"] = await on_boundary(
                    prefix, row["cache_salt"]
                )
                step["observation_wait_ms"] = (time.monotonic_ns() - sample_start) / 1e6
            step["dispatched_ns"] = time.monotonic_ns()
            tool_task = asyncio.create_task(tools(call))
            if policy is not None and prefix:
                submissions.append(asyncio.create_task(submit_step(step)))
            try:
                result = await tool_task
            finally:
                if not tool_task.done():
                    tool_task.cancel()
                await asyncio.gather(tool_task, return_exceptions=True)
                step["completed_ns"] = time.monotonic_ns()
            step["result"] = result
            step["duration_ms"] = (step["completed_ns"] - step["dispatched_ns"]) / 1e6
            # Ordinary continuation never waits for the control submission.
            ids, messages = adapter.continuation(
                tokenizer, messages, SCHEMA, ids, generation["output_ids"], call, result
            )
    except asyncio.CancelledError:
        row["status"] = "CANCELLED"
        raise
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        row["completed_ns"] = time.monotonic_ns()
        row["full_task_ms"] = (row["completed_ns"] - row["started_ns"]) / 1e6
        if policy is not None:
            row["prefetch"] = await settle_owned(
                policy,
                submissions,
                session_id=row["cache_salt"],
                abandoned=row["status"] != "COMPLETED",
            )
        row["finalized_ns"] = time.monotonic_ns()
        if on_record is not None:
            on_record(row)
    return row
