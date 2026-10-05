"""Live multi-round harness: actual model IDs and useful tool results."""

import asyncio
import hashlib
import json
import time
import uuid

from .adapters import aligned_prefix
from .contracts import (
    ExecutedTurn,
    FinalAnswer,
    InvalidOutput,
    ModelAdapter,
    ToolCalls,
    UnsupportedOutput,
)
from .workloads import SCHEMA
from .sampling import ToolWindowSamples, sampling_budget, window_summary


class GenerationTransport:
    """Borrow an explicitly configured server. Never launch, flush or provision."""

    def __init__(self, http, *, max_new_tokens=256):
        self.http = http
        self.max_new_tokens = max_new_tokens
        self.request_id_prefix = "tg-"

    async def generate(self, ids, salt):
        evidence = dict(input_ids=list(ids), output_ids=[], stream_events=[])
        try:
            return await self._generate(ids, salt, evidence)
        except BaseException as exc:
            # Failed/cancelled streams are evidence too, never successful turns.
            evidence["completed_ns"] = time.monotonic_ns()
            exc.generation_evidence = evidence
            raise

    async def _generate(self, ids, salt, evidence):
        submitted = time.monotonic_ns()
        first, last = None, None
        rid = self.request_id_prefix + uuid.uuid4().hex
        evidence.update(submitted_ns=submitted, rid=rid, first_token_ns=None)
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
                evidence["stream_events"].append(line[6:])
                event = json.loads(line[6:])
                if "error" in event:
                    raise RuntimeError(str(event["error"]))
                output = event.get("output_ids")
                if not isinstance(output, list) or any(
                    type(i) is not int or i < 0 for i in output
                ):
                    raise ValueError("Invalid streamed token IDs")
                if (
                    last is not None
                    and output[: len(last["output_ids"])] != last["output_ids"]
                ):
                    raise ValueError("Stream rewrote generated token IDs")
                last = event
                evidence.update(
                    output_ids=list(output), meta_info=event.get("meta_info", {})
                )
                if output and first is None:
                    first = time.monotonic_ns()
                    evidence["first_token_ns"] = first
        if last is None or first is None:
            raise ValueError("Server did not return generated token IDs")
        ids = last["output_ids"]
        if (
            not isinstance(ids, list)
            or not ids
            or any(type(i) is not int or i < 0 for i in ids)
        ):
            raise ValueError("Invalid generated token IDs")
        if last.get("meta_info", {}).get("finish_reason") is None:
            raise ValueError("Stream ended without a terminal finish reason")
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
                "Call one tool at a time. Never invent file/line evidence. "
                "Search words or identifiers, not necessarily an exact phrase. "
                "Use list_repository to discover paths when needed. "
                "Cite numbered source lines actually returned by search_repository, "
                "read_source or run_regression; a file listing is not evidence.",
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
    adapter: ModelAdapter,
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
    sampling_config=None,
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
    submissions = []
    windows = []

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
        if on_boundary is not None:
            sampling_config = sampling_budget(sampling_config)
        messages = initial_messages(adapter, task)
        ids = adapter.prompt(tokenizer, messages, SCHEMA)
        if (
            task.get("initial_input_ids") is not None
            and ids != task["initial_input_ids"]
        ):
            raise ValueError("Prepared native initial token IDs changed")
        for turn in range(max_tool_rounds + 1):
            if len(ids) + getattr(model, "max_new_tokens", 0) > context_limit:
                raise ValueError("Conversation exceeds declared input token limit")
            try:
                generation = await model.generate(ids, row["cache_salt"])
            except BaseException as exc:
                if hasattr(exc, "generation_evidence"):
                    partial = exc.generation_evidence
                    partial.update(
                        profile_id=adapter.profile_id,
                        response_outcome="TransportFailure",
                    )
                    row["generations"].append(partial)
                    if row["tools"] and type(partial.get("submitted_ns")) is int:
                        row["tools"][-1]["continuation_submitted_ns"] = partial[
                            "submitted_ns"
                        ]
                raise
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
            finish = generation.get("meta_info", {}).get("finish_reason")
            outcome = adapter.classify(
                raw, {s["function"]["name"] for s in SCHEMA}, finish
            )
            executed = ExecutedTurn(
                adapter.profile_id,
                tuple(ids),
                tuple(generation["output_ids"]),
                raw,
                finish.get("type") if isinstance(finish, dict) else finish,
                outcome,
            )
            generation.update(
                raw_text=executed.raw_text,
                profile_id=executed.profile_id,
                response_outcome=type(outcome).__name__,
                outcome_reason=getattr(outcome, "reason", None),
            )
            if isinstance(outcome, (InvalidOutput, UnsupportedOutput)):
                row["failure_kind"] = type(outcome).__name__
                raise ValueError(outcome.reason)
            if isinstance(outcome, FinalAnswer):
                row["output"] = outcome.text
                row["task_success"] = tools.grade(task, row["output"], row["tools"])
                row["status"] = "COMPLETED"
                break
            if not isinstance(outcome, ToolCalls) or len(outcome.calls) != 1:
                row["failure_kind"] = "UnsupportedOutput"
                raise ValueError("MULTIPLE_TOOL_CALLS")
            call = outcome.calls[0]
            if turn == max_tool_rounds:
                raise ValueError("Tool-round budget exhausted")
            # Both checks precede tools, observer calls and cache-control effects.
            tools.validate_call(call)
            try:
                plan = adapter.prepare_continuation(
                    tokenizer, messages, SCHEMA, ids, generation["output_ids"], call
                )
                # Minimum envelope fit is checkable now; actual output is not.
                plan.append(
                    tokenizer,
                    {},
                    max_input_tokens=context_limit
                    - getattr(model, "max_new_tokens", 0),
                )
            except ValueError:
                row["failure_kind"] = "UnsupportedContinuation"
                raise
            saved = ids + generation["output_ids"]
            prefix = aligned_prefix(saved)
            step = dict(
                call=dict(
                    name=call.name,
                    arguments=call.arguments,
                    call_id=call.call_id,
                    model_call_id=call.model_call_id,
                ),
                tool_execution_id=uuid.uuid4().hex,
                boundary_ns=time.monotonic_ns(),
                prefix_ids=prefix,
                prefix_sha256=hashlib.sha256(json.dumps(prefix).encode()).hexdigest(),
            )
            row["tools"].append(step)
            step["dispatched_ns"] = time.monotonic_ns()
            window = None
            if on_boundary is not None:
                window = ToolWindowSamples(
                    on_boundary, prefix, row["cache_salt"], step, config=sampling_config
                )
                windows.append(window)
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
            ids, messages = plan.append(
                tokenizer,
                result,
                max_input_tokens=context_limit - getattr(model, "max_new_tokens", 0),
            )
            if window is not None:
                window.continuation_boundary()
    except asyncio.CancelledError as exc:
        row["status"] = "CANCELLED"
        row["task_success"] = False
        exc.task_evidence = row  # Filled by finally before the block retains it.
        raise
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        row["completed_ns"] = time.monotonic_ns()
        row["full_task_ms"] = (row["completed_ns"] - row["started_ns"]) / 1e6
        for window in windows:
            await window.finish()
            window.step["cache_window_summary"] = window_summary(window.step)
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
