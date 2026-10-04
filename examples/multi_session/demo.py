"""Two salted, real model/tool/continuation trajectories on one pinned worker.

Local preparation only until executed on an explicitly authorized GPU host.
"""

import argparse
import collections
import csv
import hashlib
import json
import random
import shutil
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "examples/tool_loop")]
from run import CONTEXT, SCHEMA, SYSTEM, records, tool  # noqa: E402
from search_tool import create_corpus  # noqa: E402
from server import Engine  # noqa: E402
from tokens import aligned_saved_prefix, continuation_ids, parse_tool_call  # noqa: E402
from workflow import pair, trajectory  # noqa: E402

from toolgap import PrefetchAdmission, PrefetchClient  # noqa: E402


def trace_for_session(events, row, before, client_events):
    """Storage keys isolate salts; internal rid links the proactive operation.

    Occupancy/evictions remain worker-level: never assign them to one caller.
    Read counts include only pages in this known saved prefix, not its suffix.
    """
    t0 = row["t0_tool_dispatched"]
    after = [e for e in events if e["at_ns"] >= t0]
    keys = set(before["storage_key_hashes"])
    reads = collections.Counter(
        key for e in after if e["kind"] == "read" for key in e["keys"] if key in keys
    )
    state = row["lease"]
    op = state["operation_id"] if state else None
    mapping = [
        e
        for e in after
        if e["kind"] == "control_accepted_end" and e["operation_id"] == op
    ]
    rid = mapping[0]["rid"] if mapping else None
    published = [
        e
        for e in after
        if e["kind"] == "publish"
        and rid is not None
        and e["rid"] == rid
        and e["restored_tokens"] > 0
    ]
    io = [
        e
        for e in after
        if e["kind"] == "restore_io" and e["rid"] in {rid, row["continuation_rid"]}
    ]
    sends = [
        e["at_ns"]
        for e in client_events
        if e["operation_id"] == op and e["action"] == "submit" and e["phase"] == "send"
    ]
    t1 = min(sends) if sends else None
    t2 = max((e["at_ns"] for e in published), default=None)
    t4 = row["timing"]["submitted_ns"] if row["timing"] else None
    t5 = row["timing"]["first_token_ns"] if row["timing"] else None
    return dict(
        proactive_internal_rid=rid,
        t1_prefetch_submitted=t1,
        t2_l2_published=t2,
        t4_continuation_submitted=t4,
        t5_first_token=t5,
        prefix_backend_read_pages=sum(reads.values()),
        duplicate_prefix_read_pages=sum(max(0, n - 1) for n in reads.values()),
        restore_io_ms=sum((e["end_ns"] - e["start_ns"]) / 1e6 for e in io),
        published_before_continuation=bool(t2 and t4 and t2 < t4),
        hidden_restore_path_ms=max(0, min(t2, t4) - t1) / 1e6
        if t1 and t2 and t4
        else None,
        continuation_ttft_ms=(t5 - t4) / 1e6 if t4 and t5 else None,
        tool_dispatch_to_first_token_ms=(t5 - t0) / 1e6 if t5 else None,
        tool_duration_ms=(row["t3_tool_completed"] - t0) / 1e6,
    )


async def main(args):
    import asyncio
    from transformers import AutoTokenizer

    args.work_dir.mkdir(parents=True, exist_ok=False)
    args.results_dir.mkdir(parents=True, exist_ok=False)
    corpus = args.work_dir / "documents.jsonl"
    create_corpus(corpus, args.documents)
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, local_files_only=True)
    prompt = tokenizer.apply_chat_template(
        [
            dict(role="system", content=SYSTEM + CONTEXT * 100),
            dict(
                role="user",
                content="Find evidence for: KV prefetch tool latency. Call search_documents now.",
            ),
        ],
        tools=SCHEMA,
        tokenize=True,
        return_dict=False,
        add_generation_prompt=True,
    )
    assert len(prompt) + 128 + 512 + 64 < 8192
    engine = Engine(
        args.model_path,
        args.work_dir,
        args.results_dir,
        args.port,
        max_running_requests=2,
    )
    sessions = [
        dict(id=f"agent-{i}", salt=f"toolgap-v03-agent-{i}", prompt=prompt)
        for i in range(2)
    ]
    source = args.work_dir / "source-l3"
    source.mkdir()
    all_rows, rounds, outputs = [], [], {}
    config = dict(
        compatibility=json.loads((ROOT / "compatibility.json").read_text()),
        repetitions=args.repetitions,
        callers=2,
        max_running_requests=2,
        proactive_slots=1,
        documents=args.documents,
        corpus_sha256=hashlib.sha256(corpus.read_bytes()).hexdigest(),
        scenarios=["baseline", "admission", "abandon_first"],
        cache_state="L3-only, distinct salts, identical prompt",
        os_page_cache="Potentially warm; source hashing/copy outside timing",
        usage_accounting="unknown for continuation, zero only for abandonment",
        harness_sha256={
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                Path(__file__),
                Path(__file__).with_name("workflow.py"),
                ROOT / "examples/tool_loop/server.py",
                ROOT / "examples/tool_loop/plugin/toolgap_demo_trace.py",
            ]
        },
    )
    (args.results_dir / "config.json").write_text(json.dumps(config, indent=2))
    try:
        await engine.start("producer", source)
        for session in sessions:
            decision, _ = await engine.generate(prompt, session["salt"])
            session["decision"] = decision["output_ids"]
            session["call"] = parse_tool_call(
                tokenizer.decode(session["decision"], skip_special_tokens=False)
            )
            session["prefix"] = aligned_saved_prefix(prompt, session["decision"])
            await engine.ensure_storage(session["prefix"], session["salt"])
        await engine.stop()
        manifest = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source.glob("*.bin")
        }
        (args.results_dir / "source.json").write_text(
            json.dumps(dict(sessions=sessions, manifest=manifest), indent=2)
        )
        plans = [
            (rep, mode)
            for rep in range(args.repetitions)
            for mode in config["scenarios"]
        ]
        random.Random(42).shuffle(plans)
        for rep, mode in plans:
            label = f"{mode}-{rep}"
            storage = args.work_dir / (label + "-l3")
            shutil.copytree(source, storage)
            await engine.start(label, storage)
            try:
                empty = await engine.probe(sessions[0]["prefix"], sessions[0]["salt"])
                # Generate actual first turns on this worker; verify exact saved IDs.
                for session in sessions:
                    decision, _ = await engine.generate(prompt, session["salt"])
                    assert decision["output_ids"] == session["decision"], (
                        "Tool-call IDs changed"
                    )
                    await engine.ensure_storage(session["prefix"], session["salt"])
                await engine.flush()
                before = {}
                for session in sessions:  # Probe mailbox is intentionally serialized.
                    state = await engine.probe(session["prefix"], session["salt"])
                    assert (
                        state["device_hit_tokens"] == state["host_hit_tokens"] == 0
                    ), state
                    assert state["storage_available_tokens"] == len(
                        session["prefix"]
                    ), state
                    before[session["id"]] = state
                assert not set(before["agent-0"]["storage_key_hashes"]) & set(
                    before["agent-1"]["storage_key_hashes"]
                )
                for name, digest in manifest.items():
                    assert (
                        hashlib.sha256((storage / name).read_bytes()).hexdigest()
                        == digest
                    )
                client_events = []
                async with PrefetchClient(
                    engine.url, on_event=client_events.append
                ) as client:
                    admission = (
                        PrefetchAdmission(client) if mode != "baseline" else None
                    )
                    gate = asyncio.Event()
                    order = sessions if rep % 2 == 0 else sessions[::-1]
                    coroutines = []
                    rids = {}
                    for position, session in enumerate(order):
                        rid = f"v03-{label}-{session['id']}"
                        rids[session["id"]] = rid

                        async def continuation(result, s=session, request_id=rid):
                            ids = continuation_ids(
                                tokenizer, s["prompt"], s["decision"], result
                            )
                            assert ids[: len(s["prefix"])] == s["prefix"]
                            return await engine.generate(
                                ids, s["salt"], limit=64, rid=request_id
                            )

                        coroutines.append(
                            trajectory(
                                session,
                                gate,
                                lambda s=session: tool(
                                    corpus, s["call"]["arguments"]["query"]
                                ),
                                continuation,
                                admission,
                                abandon=mode == "abandon_first" and position == 0,
                            )
                        )
                    rows = await pair(coroutines, gate)
                    events = records(engine.trace, label)
                    for row in rows:
                        session_id = row["session_id"]
                        row.update(
                            mode=mode,
                            repetition=rep,
                            continuation_rid=rids[session_id],
                            cache_state_before_tool=before[session_id],
                        )
                        assert row["tool_result"]["document_id"] == "DOC-00173"
                        if row["response"]:
                            answer = json.loads(row["response"]["text"].strip())
                            assert answer == dict(
                                document_id=row["tool_result"]["document_id"]
                            )
                            ids = row["response"]["output_ids"]
                            if session_id in outputs:
                                assert outputs[session_id] == ids, (
                                    "Output IDs differ across conditions"
                                )
                            outputs[session_id] = ids
                            details = (
                                row["response"]["meta_info"].get(
                                    "cached_tokens_details"
                                )
                                or {}
                            )
                            prefix_length = before[session_id]["prefix_tokens"]
                            assert (
                                sum(
                                    details.get(tier, 0) for tier in ("host", "storage")
                                )
                                >= prefix_length
                            ), details
                            if mode == "baseline":
                                assert details.get("storage", 0) >= prefix_length, (
                                    details
                                )
                        row["output_correct"] = True if row["response"] else None
                        row.update(
                            trace_for_session(
                                events, row, before[session_id], client_events
                            )
                        )
                        all_rows.append(row)
                        (args.results_dir / "trials.json").write_text(
                            json.dumps(all_rows, indent=2)
                        )
                    start = min(r["t0_tool_dispatched"] for r in rows)
                    interval = [e for e in events if e["at_ns"] >= start]
                    worker = dict(
                        label=label,
                        mode=mode,
                        repetition=rep,
                        admission_metrics=admission.metrics if admission else None,
                        client_events=client_events,
                        host_evicted_tokens=sum(
                            e["evicted_tokens"]
                            for e in interval
                            if e["kind"] == "evict_host"
                        ),
                        peak_observed_host_tokens=max(
                            (
                                e["host_used_tokens"]
                                for e in interval
                                if "host_used_tokens" in e
                            ),
                            default=None,
                        ),
                        duplicate_prefix_read_pages=sum(
                            r["duplicate_prefix_read_pages"] for r in rows
                        ),
                        observed_tool_interval_overlap_ms=max(
                            0,
                            min(r["t3_tool_completed"] for r in rows)
                            - max(r["t0_tool_dispatched"] for r in rows),
                        )
                        / 1e6,
                        observed_generation_interval_overlap_ms=(
                            max(
                                0,
                                min(
                                    r["timing"]["generation_completed_ns"] for r in rows
                                )
                                - max(r["timing"]["submitted_ns"] for r in rows),
                            )
                            / 1e6
                            if all(r["timing"] for r in rows)
                            else None
                        ),
                    )
                    if admission:
                        assert admission.metrics["active_slots"] == 0
                await engine.flush()
                cleanup = await engine.probe(sessions[0]["prefix"], sessions[0]["salt"])
                assert (
                    cleanup["host_available_tokens"] == empty["host_available_tokens"]
                ), cleanup
                assert (
                    cleanup["inflight_tokens"] == cleanup["ongoing_prefetch_count"] == 0
                ), cleanup
                worker["cleanup"] = cleanup
                rounds.append(worker)
                (args.results_dir / "trials.json").write_text(
                    json.dumps(all_rows, indent=2)
                )
                (args.results_dir / "rounds.json").write_text(
                    json.dumps(rounds, indent=2)
                )
                print("MULTI_SESSION", json.dumps(worker), flush=True)
            finally:
                await engine.stop()
        columns = [
            "mode",
            "repetition",
            "session_id",
            "abandoned",
            "output_correct",
            "continuation_ttft_ms",
            "tool_dispatch_to_first_token_ms",
            "tool_duration_ms",
            "restore_io_ms",
            "hidden_restore_path_ms",
            "published_before_continuation",
            "prefix_backend_read_pages",
            "duplicate_prefix_read_pages",
        ]
        with (args.results_dir / "trials.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_rows)
        summary = []
        for mode in config["scenarios"]:
            for session in sessions:
                selected = [
                    r
                    for r in all_rows
                    if r["mode"] == mode
                    and r["session_id"] == session["id"]
                    and not r["abandoned"]
                ]
                if selected:
                    summary.append(
                        dict(
                            mode=mode,
                            session_id=session["id"],
                            n=len(selected),
                            median_ttft_ms=statistics.median(
                                r["continuation_ttft_ms"] for r in selected
                            ),
                            median_tool_dispatch_to_first_token_ms=statistics.median(
                                r["tool_dispatch_to_first_token_ms"] for r in selected
                            ),
                        )
                    )
        (args.results_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    except BaseException as exc:
        (args.results_dir / "failure.json").write_text(
            json.dumps(dict(error=type(exc).__name__, message=str(exc)), indent=2)
        )
        raise
    finally:
        await engine.stop()
        await engine.http.aclose()


if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--documents", type=int, default=10000)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--port", type=int, default=30000)
    args = parser.parse_args()
    if args.repetitions < 1 or args.documents < 174:
        parser.error("Need positive repetitions and at least174 documents")
    asyncio.run(main(args))
