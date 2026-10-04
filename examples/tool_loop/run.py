"""Real Qwen tool call → document retrieval → exact-token continuation.

Four scenarios, no artificial tool sleep. No cloud APIs or resource provisioning.
"""

import argparse
import asyncio
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
sys.path.insert(0, str(ROOT / "src"))
from integration import run_with_prefetch  # noqa: E402
from search_tool import create_corpus  # noqa: E402
from server import Engine  # noqa: E402
from tokens import aligned_saved_prefix, continuation_ids, parse_tool_call  # noqa: E402

from toolgap import PrefetchClient  # noqa: E402

SCHEMA = [
    dict(
        type="function",
        function=dict(
            name="search_documents",
            description="Search the document archive for supporting evidence.",
            parameters=dict(
                type="object",
                properties=dict(query=dict(type="string")),
                required=["query"],
            ),
        ),
    )
]
SYSTEM = (
    "You investigate document archives. First call search_documents with the "
    "user's exact query. After receiving the tool result, return only a JSON "
    'object with its document_id: {"document_id":"DOC-xxxxx"}. '
    "Never fabricate a document id.\n"
)
CONTEXT = (
    "Notebook context: saved model prefixes can be backed by file storage. "
    "Exact token identity and cache salt preserve reuse across continuation "
    "requests. Tool runtime must be measured independently.\n"
)


async def tool(corpus, query):
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("search_tool.py")),
        str(corpus),
        query,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode())
        return json.loads(stdout)
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 2)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()


def records(path, label):
    if not path.exists():
        return []
    return [
        r
        for line in path.read_text().splitlines()
        if (r := json.loads(line))["label"] == label
    ]


def summarize_trace(events, t0, t4):
    # Exclude first-turn generation/probes: only the tool/continuation interval.
    after = [r for r in events if r["at_ns"] >= t0]
    reads = [r for r in after if r["kind"] == "read"]
    keys = collections.Counter(k for r in reads for k in r["keys"])
    io = [r for r in after if r["kind"] == "restore_io"]
    published = [
        r for r in after if r["kind"] == "publish" and r["restored_tokens"] > 0
    ]
    accepted = [r for r in after if r["kind"] == "control_accepted_start"]
    return dict(
        scheduler_control_start_ns=accepted[0]["at_ns"] if accepted else None,
        restore_operation_start_ns=min(
            (r["operation_start_ns"] for r in io), default=None
        ),
        l2_published_ns=max((r["at_ns"] for r in published), default=None),
        restored_tokens=sum(r["restored_tokens"] for r in published),
        restored_bytes=sum(r["bytes"] for r in reads),
        backend_read_pages=sum(keys.values()),
        duplicate_backend_read_pages=sum(max(0, n - 1) for n in keys.values()),
        io_hidden_ms=sum(
            max(0, min(r["end_ns"], t4) - r["start_ns"]) / 1e6 for r in io
        ),
        io_duration_ms=sum((r["end_ns"] - r["start_ns"]) / 1e6 for r in io),
        proactive_h2d=any(r["kind"] == "h2d_submit" and r["at_ns"] < t4 for r in after),
        relevant_host_evictions=sum(
            r["evicted_tokens"] for r in after if r["kind"] == "evict_host"
        ),
    )


async def main(args):
    from transformers import AutoTokenizer

    args.work_dir.mkdir(parents=True, exist_ok=False)
    args.results_dir.mkdir(parents=True, exist_ok=False)
    corpus = args.corpus
    if corpus is None:
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
    assert (
        len(prompt) + 128 + 512 + 64 < 8192
    ), "Tool prompt exceeds validated context budget"
    compatibility = json.loads((ROOT / "compatibility.json").read_text())
    (args.results_dir / "demo-config.json").write_text(
        json.dumps(
            dict(
                compatibility=compatibility,
                model_path=args.model_path,
                corpus_sha256=hashlib.sha256(corpus.read_bytes()).hexdigest(),
                repetitions=args.repetitions,
                documents=args.documents,
                os_page_cache="Potentially warm: source payload verification happens before timing",
                temperature=0,
                sampling_seed=42,
                max_tool_call_tokens=128,
                max_continuation_tokens=64,
            ),
            indent=2,
        )
    )
    engine = Engine(args.model_path, args.work_dir, args.results_dir, args.port)
    salt = "toolgap-v02-exact-prefix"
    expected_decision, expected_output, expected_tool = None, None, None
    rows = []
    source = args.work_dir / "source-l3"
    source.mkdir()
    await engine.start("source-producer", source)
    try:
        source_decision, _ = await engine.generate(prompt, salt)
        parse_tool_call(
            tokenizer.decode(source_decision["output_ids"], skip_special_tokens=False)
        )
        expected_decision = source_decision["output_ids"]
        source_prefix = aligned_saved_prefix(prompt, expected_decision)
        source_probe = await engine.ensure_storage(source_prefix, salt)
    finally:
        await engine.stop()
    # Read/copy source pages outside measurements. OS page cache can be warm.
    source_manifest = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob("*.bin")
    }
    (args.results_dir / "source-l3-sha256.json").write_text(
        json.dumps(source_manifest, indent=2)
    )
    (args.results_dir / "source-prefix.json").write_text(
        json.dumps(
            dict(
                prompt_ids=prompt,
                decision_ids=expected_decision,
                prefix_ids=source_prefix,
                cache_salt=salt,
                probe=source_probe,
            ),
            indent=2,
        )
    )
    plans = [
        (rep, scenario, mode)
        for rep in range(args.repetitions)
        for scenario in ["l3_only", "resident"]
        for mode in ["baseline", "proactive"]
    ]
    random.Random(42).shuffle(plans)
    try:
        for rep, scenario, mode in plans:
            label = f"{scenario}-{mode}-{rep}"
            storage = args.work_dir / (label + "-l3")
            shutil.copytree(source, storage)
            await engine.start(label, storage)
            try:
                empty = await engine.probe(source_prefix, salt)
                decision, _ = await engine.generate(prompt, salt)
                call = parse_tool_call(
                    tokenizer.decode(decision["output_ids"], skip_special_tokens=False)
                )
                if expected_decision is None:
                    expected_decision = decision["output_ids"]
                assert (
                    decision["output_ids"] == expected_decision
                ), "Model tool call changed between paired conditions"
                prefix = aligned_saved_prefix(prompt, decision["output_ids"])
                await engine.ensure_storage(prefix, salt)
                if scenario == "l3_only":
                    # Controlled eviction, not a claim that a tool call causes eviction.
                    await engine.flush()
                for name, digest in source_manifest.items():
                    assert (
                        hashlib.sha256((storage / name).read_bytes()).hexdigest()
                        == digest
                    ), "L3 source payload changed"
                before = await engine.probe(prefix, salt)
                assert before["storage_available_tokens"] == len(prefix), before
                resident = before["device_hit_tokens"] + before["host_hit_tokens"]
                assert resident == (0 if scenario == "l3_only" else len(prefix)), before
                # Prefix storage identity must agree across all four conditions.
                if rows:
                    assert (
                        before["storage_key_hashes"]
                        == rows[0]["cache_state_before_tool"]["storage_key_hashes"]
                    )
                    assert (
                        before["storage_model_namespace"]
                        == rows[0]["cache_state_before_tool"]["storage_model_namespace"]
                    )
                events = []
                async with PrefetchClient(engine.url, on_event=events.append) as client:
                    run = await run_with_prefetch(
                        lambda: tool(corpus, call["arguments"]["query"]),
                        client,
                        label,
                        prefix,
                        cache_salt=salt,
                        enabled=mode == "proactive",
                        on_cleanup=lambda state: (
                            args.results_dir / (label + "-failure-cleanup.json")
                        ).write_text(json.dumps(state, indent=2)),
                    )
                    if expected_tool is None:
                        expected_tool = run.result
                    assert (
                        run.result == expected_tool
                    ), "Tool result differs between conditions"
                    if args.corpus is None:
                        assert run.result["document_id"] == "DOC-00173", run.result
                    inputs = continuation_ids(
                        tokenizer, prompt, decision["output_ids"], run.result
                    )
                    assert inputs[: len(prefix)] == prefix
                    response, timing = await engine.generate(inputs, salt, limit=64)
                    answer = json.loads(response["text"].strip())
                    assert answer == dict(
                        document_id=run.result["document_id"]
                    ), response
                    if expected_output is None:
                        expected_output = response["output_ids"]
                    assert (
                        response["output_ids"] == expected_output
                    ), "Continuation output IDs differ"
                    admission = await run.submission if run.submission else None
                    status = (
                        await client.status(label)
                        if admission and admission["accepted"]
                        else None
                    )
                    if status:
                        assert (
                            status["inflight_tokens"] == 0
                            and not status["cleanup_pending"]
                        ), status
                    t0, t3 = run.tool_dispatched_ns, run.tool_completed_ns
                    t4, t5 = timing["submitted_ns"], timing["first_token_ns"]
                    trace = summarize_trace(records(engine.trace, label), t0, t4)
                    assert not trace["proactive_h2d"]
                    assert trace["duplicate_backend_read_pages"] == 0
                    details = response["meta_info"].get("cached_tokens_details") or {}
                    if scenario == "resident":
                        assert (
                            trace["backend_read_pages"] == 0
                        ), "Resident control issued new L3 reads"
                        assert details.get("device", 0) + details.get("host", 0) >= len(
                            prefix
                        ), details
                    elif mode == "baseline":
                        assert details.get("storage", 0) >= len(prefix), details
                    elif admission and admission["accepted"]:
                        assert status["state"] == "SUCCESS", status
                        assert trace["restored_tokens"] >= len(prefix), trace
                        assert details.get("host", 0) + details.get(
                            "storage", 0
                        ) >= len(prefix), details
                    t1 = next(
                        (
                            e["at_ns"]
                            for e in events
                            if e["action"] == "submit" and e["phase"] == "send"
                        ),
                        None,
                    )
                    recv = next(
                        (
                            e["at_ns"]
                            for e in events
                            if e["action"] == "submit"
                            and e["phase"] == "receive_or_error"
                        ),
                        None,
                    )
                    t2 = trace["l2_published_ns"]
                    row = dict(
                        scenario=scenario,
                        mode=mode,
                        repetition=rep,
                        tool_call=call,
                        tool_result=run.result,
                        prompt_tokens=len(prompt),
                        saved_prefix_tokens=len(prefix),
                        cache_state_before_tool=before,
                        source_manifest_sha256=hashlib.sha256(
                            json.dumps(source_manifest, sort_keys=True).encode()
                        ).hexdigest(),
                        timestamps=dict(
                            t0_tool_dispatched=t0,
                            t1_prefetch_submitted=t1,
                            t2_l2_published=t2,
                            t3_tool_completed=t3,
                            t4_continuation_submitted=t4,
                            t5_first_token=t5,
                        ),
                        tool_duration_ms=(t3 - t0) / 1e6,
                        prefetch_rpc_ms=(recv - t1) / 1e6 if t1 and recv else None,
                        hidden_restore_path_ms=(
                            max(0, min(t2, t4) - t1) / 1e6 if t1 and t2 else 0
                        ),
                        continuation_ttft_ms=(t5 - t4) / 1e6,
                        agent_step_ms=(t5 - t0) / 1e6,
                        admission=admission,
                        status=status,
                        client_events=events,
                        cached_tokens_details=response["meta_info"].get(
                            "cached_tokens_details"
                        ),
                        output_ids=response["output_ids"],
                        output_correct=True,
                        **trace,
                    )
                    rows.append(row)
                    (args.results_dir / "tool-loop-trials.json").write_text(
                        json.dumps(rows, indent=2)
                    )
                    print(
                        "TOOL_LOOP",
                        json.dumps(
                            {
                                k: row[k]
                                for k in [
                                    "scenario",
                                    "mode",
                                    "tool_duration_ms",
                                    "continuation_ttft_ms",
                                    "agent_step_ms",
                                    "output_correct",
                                ]
                            }
                        ),
                        flush=True,
                    )
                # Both treatments reclaim through the same ordinary flush, after measuring.
                await engine.flush()
                after = await engine.probe(prefix, salt)
                assert (
                    after["device_hit_tokens"] == after["host_hit_tokens"] == 0
                ), after
                assert (
                    after["host_available_tokens"] == empty["host_available_tokens"]
                ), "Host slots did not return to baseline"
                assert (
                    after["inflight_tokens"] == after["ongoing_prefetch_count"] == 0
                ), after
                row["cleanup_after_flush"] = after
                row["empty_cache_baseline"] = empty
                (args.results_dir / "tool-loop-trials.json").write_text(
                    json.dumps(rows, indent=2)
                )
            finally:
                await engine.stop()
    finally:
        await engine.stop()
        await engine.http.aclose()
    with (args.results_dir / "tool-loop-trials.csv").open("w", newline="") as output:
        columns = [
            "scenario",
            "mode",
            "repetition",
            "prompt_tokens",
            "saved_prefix_tokens",
            "tool_duration_ms",
            "prefetch_rpc_ms",
            "hidden_restore_path_ms",
            "io_hidden_ms",
            "io_duration_ms",
            "continuation_ttft_ms",
            "agent_step_ms",
            "restored_tokens",
            "restored_bytes",
            "duplicate_backend_read_pages",
            "relevant_host_evictions",
            "output_correct",
        ]
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    summary = []
    for scenario in ["l3_only", "resident"]:
        for mode in ["baseline", "proactive"]:
            group = [r for r in rows if r["scenario"] == scenario and r["mode"] == mode]
            summary.append(
                dict(
                    scenario=scenario,
                    mode=mode,
                    repetitions=len(group),
                    continuation_ttft_median_ms=statistics.median(
                        r["continuation_ttft_ms"] for r in group
                    ),
                    agent_step_median_ms=statistics.median(
                        r["agent_step_ms"] for r in group
                    ),
                )
            )
    (args.results_dir / "tool-loop-summary.json").write_text(
        json.dumps(summary, indent=2)
    )
    print("TOOL_LOOP_COMPLETE", json.dumps(summary), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model-path", required=True)
    p.add_argument("--work-dir", type=Path, required=True)
    p.add_argument("--results-dir", type=Path, required=True)
    p.add_argument("--corpus", type=Path)
    p.add_argument("--documents", type=int, default=10000)
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--port", type=int, default=30000)
    args = p.parse_args()
    if args.documents < 174 or args.repetitions < 1:
        p.error("Fixture needs at least174 documents and repetitions>=1")
    asyncio.run(main(args))
