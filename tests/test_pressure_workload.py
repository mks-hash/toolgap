"""CPU fixtures for competing arrivals, observation and complete-row accounting."""

import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.agent_resume.load import (
    AUDITS,
    fixed_trace,
    run_arrivals,
    summarize,
    compare_complete_blocks,
)
from research.agent_resume.sampling import FileObserver
from research.agent_resume.trace_report import analyze, saved_span
from research.agent_resume.adapters import FamilyAdapter, ToolCall
from research.agent_resume.workloads import RepositoryTools
from research.agent_resume.runner import run_task
from research.agent_resume.prepare import ScriptedModel, call_text
from test_research_harness import FormatFixture


class TestPressure(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_arrivals_overlap_queue_and_keep_failure(self):
        trace = fixed_trace(12)
        for item in trace:
            item["offset_ms"] = 0
        running = peak = 0

        async def work(item):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            try:
                await asyncio.sleep(0.01)  # test scheduler fixture, not a workload tool
                if item["trajectory_id"] == "agent-02":
                    raise ValueError("retained failure")
                return dict(
                    status="COMPLETED",
                    task_success=True,
                    completed_ns=time.monotonic_ns(),
                )
            finally:
                running -= 1

        block = await run_arrivals(trace, work, max_active=3)
        summary = summarize(block)
        self.assertEqual(peak, 3)
        self.assertEqual(summary["successful"], 11)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(len(summary["all_caller_arrival_to_completed_ms"]), 12)
        self.assertGreater(block["rows"][-1]["client_queue_ms"], 10)
        self.assertEqual(len(fixed_trace()), 12)
        self.assertEqual(fixed_trace(), fixed_trace())

    async def test_cancel_reaps_every_started_caller(self):
        started = asyncio.Event()
        active = set()

        async def work(item):
            ident = item["trajectory_id"]
            active.add(ident)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(
                    0.01
                )  # owned async cleanup must not be cancelled twice
                active.remove(ident)

        trace = fixed_trace(4)
        for item in trace:
            item["offset_ms"] = 0
        task = asyncio.create_task(run_arrivals(trace, work, max_active=2))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(active)

    async def test_cancel_retains_running_queued_and_future_callers_once(self):
        started = asyncio.Event()
        saved = []
        trace = fixed_trace(4)
        trace[0]["offset_ms"] = trace[1]["offset_ms"] = 0
        trace[2]["offset_ms"] = trace[3]["offset_ms"] = 60000
        partial = dict(
            status="FAILED",
            task_success=False,
            tools=[],
            generations=[dict(input_ids=[7], output_ids=[9])],
            prefetch=[],
            completed_ns=0,
        )

        async def work(item):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError as exc:
                exc.task_evidence = partial
                raise

        task = asyncio.create_task(
            run_arrivals(trace, work, max_active=1, on_result=saved.append)
        )
        await started.wait()
        await asyncio.sleep(0)  # Allow the other fixed callers to wait at their gates.
        task.cancel()
        with self.assertRaises(asyncio.CancelledError) as raised:
            await task
        self.assertEqual(len(saved), 4)
        self.assertEqual(len({r["trajectory_id"] for r in saved}), 4)
        self.assertEqual(
            {r["arrival_phase"] for r in saved},
            {"RUNNING", "WAITING_CLIENT_GATE", "NOT_YET_ARRIVED"},
        )
        self.assertTrue(
            all(r["status"] == "CANCELLED" and not r["task_success"] for r in saved)
        )
        self.assertTrue(
            all(
                r["arrival_to_completed_ms"] is None
                and r["arrival_to_finalized_ms"] is None
                for r in saved
            )
        )
        self.assertEqual(
            next(r for r in saved if r["trajectory_id"] == trace[0]["trajectory_id"])[
                "generations"
            ],
            partial["generations"],
        )
        summary = summarize(raised.exception.block_evidence)
        self.assertEqual(summary["tasks"], 4)
        self.assertEqual(summary["cancelled"], 4)
        self.assertEqual(summary["successful"], 0)

    async def test_block_throughput_includes_last_cleanup_and_client_queue(self):
        started = 1000000000
        block = dict(
            block_started_ns=started,
            block_finalized_ns=started + 500000000,
            max_active_observed=1,
            rows=[
                dict(
                    status="COMPLETED",
                    task_success=True,
                    completed_ns=started + 100000000,
                    full_task_ms=50,
                    arrival_to_completed_ms=100,
                    arrival_to_finalized_ms=500,
                )
            ],
        )
        summary = summarize(block)
        self.assertEqual(summary["block_elapsed_seconds"], 0.5)
        self.assertEqual(summary["successful_tasks_per_second"], 2.0)
        self.assertEqual(summary["all_caller_arrival_to_finalized_ms"], [500])

        # A real cleanup delay affects both last-slot throughput and next caller queue.
        async def work(item):
            completed = time.monotonic_ns()
            await asyncio.sleep(0.02)  # Cleanup fixture, not workload tool delay.
            return dict(
                status="COMPLETED",
                task_success=True,
                completed_ns=completed,
                finalized_ns=time.monotonic_ns(),
                full_task_ms=0,
            )

        trace = fixed_trace(2)
        for item in trace:
            item["offset_ms"] = 0
        actual = await run_arrivals(trace, work, max_active=1)
        self.assertGreater(actual["rows"][1]["client_queue_ms"], 10)
        self.assertGreater(
            actual["rows"][1]["arrival_to_finalized_ms"],
            actual["rows"][1]["arrival_to_completed_ms"] + 10,
        )
        self.assertGreater(summarize(actual)["block_elapsed_seconds"], 0.03)

    async def test_comparison_includes_queue_and_rejects_incomplete_callers(self):
        def row(latency=100, throughput=10):
            return dict(
                procedure_completed=True,
                study_success=True,
                cleanup_unresolved=False,
                successful=2,
                tasks=2,
                latency_censored_callers=0,
                all_caller_arrival_to_finalized_ms=[latency] * 2,
                all_caller_full_task_ms=[10] * 2,
                successful_tasks_per_second=throughput,
            )

        self.assertTrue(compare_complete_blocks(row(), row(104, 9.8))["acceptable"])
        self.assertFalse(compare_complete_blocks(row(), row(106))["acceptable"])
        self.assertFalse(compare_complete_blocks(row(), row(100, 9.4))["acceptable"])
        for changes in (
            dict(procedure_completed=False),
            dict(study_success=False),
            dict(cleanup_unresolved=True),
            dict(latency_censored_callers=1),
            dict(successful=1),
            dict(all_caller_arrival_to_finalized_ms=[100, None]),
            dict(all_caller_arrival_to_finalized_ms=[100, float("nan")]),
            dict(successful_tasks_per_second=0),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                compare_complete_blocks(row(), dict(row(), **changes))

    async def test_failed_quality_is_not_success_or_dropped(self):
        async def work(item):
            return dict(
                status="COMPLETED", task_success=False, completed_ns=time.monotonic_ns()
            )

        block = await run_arrivals(fixed_trace(2), work)
        self.assertEqual(summarize(block)["completed"], 2)
        self.assertEqual(summarize(block)["successful"], 0)

    async def test_multi_file_evidence_requires_both_actual_tools(self):
        task = AUDITS[0]
        files = {
            r["path"]: dict(text=r["needle"], sha256="fixture")
            for r in task["evidence_requirements"]
        }
        tools = RepositoryTools(dict(commit="fixture", files=files))
        records = [dict(call=dict(name="run_regression"), result=dict(passed=True))]
        citations = []
        for requirement in task["evidence_requirements"]:
            hit = tools.read(requirement["path"], 1, 1)
            records.append(dict(call=dict(name="read_source"), result=hit))
            citations.append(dict(path=requirement["path"], line=1))
        final = dict(answer=task["answer"], evidence=citations)
        self.assertTrue(tools.grade(task, json.dumps(final), records))
        self.assertFalse(
            tools.grade(task, json.dumps(dict(final, evidence=citations[:1])), records)
        )
        self.assertFalse(tools.grade(task, json.dumps(final), records[:-1]))

    async def test_background_samples_are_not_dispatch_state(self):
        task = AUDITS[0]
        files = {
            r["path"]: dict(text=r["needle"], sha256="fixture")
            for r in task["evidence_requirements"]
        }
        tools = RepositoryTools(dict(commit="fixture", files=files))
        calls = [
            ToolCall("read_source", dict(path=r["path"], start=1, end=1))
            for r in task["evidence_requirements"]
        ]
        texts = [call_text("qwen", c) for c in calls] + [
            json.dumps(dict(answer=task["answer"], evidence=[]))
        ]
        observations = []

        async def observe(ids, salt):
            observations.append(time.monotonic_ns())
            return dict(residency="UNKNOWN_STORAGE")

        row = await run_task(
            FamilyAdapter("qwen"),
            FormatFixture(),
            ScriptedModel(FormatFixture(), texts),
            tools,
            task,
            on_boundary=observe,
            cache_salt="fixed",
        )
        self.assertTrue(observations)
        self.assertEqual(row["cache_salt"], "fixed")
        self.assertFalse(row["task_success"])  # missing actual regression remains wrong
        for step in row["tools"]:
            self.assertTrue(step["observer_cleanup_confirmed"])
            self.assertEqual(step["cache_window_summary"]["dispatch_state"], "UNKNOWN")
            self.assertLess(step["completed_ns"], step["continuation_submitted_ns"])

    async def test_mailbox_concurrency_mismatch_timeout_and_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observer = FileObserver(root, domain="boot", timeout=0.1)

            async def server(count, domain="boot"):
                seen = set()
                while len(seen) < count:
                    for request in root.glob("*.request.json"):
                        if request.name in seen:
                            continue
                        seen.add(request.name)
                        data = json.loads(request.read_text())
                        response = root / request.name.replace("request", "response")
                        response.write_text(
                            json.dumps(
                                dict(clock_domain=domain, salt=data["cache_salt"])
                            )
                        )
                    await asyncio.sleep(0.001)

            response_task = asyncio.create_task(server(2))
            rows = await asyncio.gather(
                observer.snapshot([1], "one"), observer.snapshot([2], "two")
            )
            await response_task
            self.assertEqual({r["salt"] for r in rows}, {"one", "two"})
            self.assertFalse(list(root.iterdir()))
            response_task = asyncio.create_task(server(1, "other-boot"))
            with self.assertRaises(ValueError):
                await observer.snapshot([1], "one")
            await response_task
            with self.assertRaises(TimeoutError):
                await observer.snapshot([1], "one")
            task = asyncio.create_task(observer.snapshot([1], "one"))
            await asyncio.sleep(0.001)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(list(root.iterdir()))


class TestTrace(unittest.TestCase):
    def test_exact_rid_mapping_no_consumption_claim_or_inferred_duplicate_bug(self):
        rows = [
            dict(
                trajectory_id="a",
                generations=[],
                tools=[
                    dict(
                        prefix_ids=[1] * 16,
                        prefetch_operation_id="op",
                        continuation_submitted_ns=100,
                    )
                ],
            )
        ]
        events = [
            dict(
                kind="control_accepted_end",
                clock_domain="boot",
                operation_id="op",
                rid="r",
            ),
            dict(
                kind="read",
                clock_domain="boot",
                rid="r",
                keys=["k"],
                bytes=32,
                start_ns=70,
                end_ns=110,
            ),
            dict(
                kind="read",
                clock_domain="boot",
                rid="another",
                keys=["k"],
                bytes=32,
                start_ns=50,
                end_ns=60,
            ),
            dict(
                kind="publish",
                clock_domain="boot",
                rid="r",
                restored_tokens=16,
                at_ns=120,
            ),
        ]
        report = analyze(rows, events, "boot")
        self.assertEqual(report["physical_read_bytes"], 64)
        self.assertEqual(report["repeated_successful_page_reads"], 1)
        self.assertEqual(report["boundaries"][0]["physical_read_bytes"], 32)
        self.assertEqual(report["boundaries"][0]["pre_arrival_published_tokens"], 0)
        self.assertAlmostEqual(
            report["boundaries"][0]["physical_io_before_arrival_ms"], 0.00003
        )
        self.assertIsNone(report["wasted_prefetch_bytes"])
        with self.assertRaises(ValueError):
            analyze(rows, events, "other-boot")

    def test_clip_match_to_saved_prefix_not_tool_result_suffix(self):
        state = dict(
            prefix_tokens=32,
            segments=[
                dict(start=0, end=8, device=True, host=True),
                dict(start=8, end=32, device=False, host=True),
            ],
        )
        self.assertEqual(
            saved_span(state, 16),
            dict(device_hit_tokens=8, host_hit_tokens=8, observed_prefix_tokens=16),
        )


class TestPressureCLI(unittest.IsolatedAsyncioTestCase):
    async def test_two_mode_whole_block_mock_transport_keeps_all_rows(self):
        import types
        import httpx
        from research.agent_resume.pressure import execute, digest
        from research.agent_resume.readiness import measurement_contract
        from research.agent_resume.workloads import TASKS
        from research.agent_resume.sampling import clock_domain

        task = TASKS[0]
        profile = dict(
            family="qwen",
            profile_id="qwen",
            tokenizer_files={},
            source_commit="fixture",
            model="model",
            revision="revision",
            runtime_candidate_sha="a" * 40,
            server_settings=dict(context_length=8192),
        )
        deployment = dict(
            model="model",
            revision="revision",
            runtime_sha="a" * 40,
            model_path="model",
            resolved_cache_mode="FULL",
            clock_domain=clock_domain(),
            pressure_match_observation=False,
        )
        corpus = dict(
            commit="fixture",
            files={task["path"]: dict(text=task["needle"], sha256="fixture")},
        )
        tokenizer = FormatFixture()
        trace = fixed_trace(2)
        for item in trace:
            item.update(offset_ms=0, task=task)
        packet = dict(
            profile=profile,
            arrivals=trace,
            max_active=2,
            measurement_contract=measurement_contract(),
        )
        original_http = httpx.AsyncClient
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "packet.json").write_text(
                json.dumps(dict(packet=packet, sha256=digest(packet)))
            )
            (root / "deployment.json").write_text(json.dumps(deployment))
            for case, mode in (
                ("request_time", "request_time"),
                ("proactive", "proactive"),
                ("cancelled", "request_time"),
            ):
                generation_started = asyncio.Event()
                turns = {}

                def handler(request):
                    if request.url.path == "/get_server_info":
                        return httpx.Response(
                            200, json=dict(context_length=8192, model_path="model")
                        )
                    data = json.loads(request.content)
                    if request.url.path == "/generate":
                        salt = data["cache_salt"]
                        turn = turns.get(salt, 0)
                        turns[salt] = turn + 1
                        text = (
                            call_text(
                                "qwen",
                                ToolCall(
                                    "search_repository", dict(query="cleanup_pending")
                                ),
                            )
                            if turn == 0
                            else json.dumps(
                                dict(
                                    answer=task["answer"],
                                    evidence=[dict(path=task["path"], line=1)],
                                )
                            )
                        )
                        return httpx.Response(
                            200,
                            text="data: "
                            + json.dumps(
                                dict(
                                    output_ids=tokenizer.encode(text),
                                    meta_info=dict(finish_reason=dict(type="stop")),
                                )
                            )
                            + "\n\ndata: [DONE]\n\n",
                        )
                    return httpx.Response(
                        200,
                        json=dict(
                            success=True,
                            result=dict(
                                operation_id=data["operation_id"],
                                state="SUCCESS",
                                cleanup_pending=False,
                                restored_tokens=0,
                                restored_bytes=0,
                            ),
                        ),
                    )

                class BlockedStream(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        yield b'data: {"output_ids":[7],"meta_info":{}}\n\n'
                        generation_started.set()
                        await asyncio.Event().wait()

                    async def aclose(self):
                        pass

                async def asynchronous_handler(request):
                    if case == "cancelled" and request.url.path == "/generate":
                        return httpx.Response(200, stream=BlockedStream())
                    return handler(request)

                def factory(*args, **kwargs):
                    kwargs["transport"] = httpx.MockTransport(asynchronous_handler)
                    return original_http(*args, **kwargs)

                args = types.SimpleNamespace(
                    packet=root / "packet.json",
                    deployment=root / "deployment.json",
                    tokenizer=root,
                    output=root / case,
                    server="http://fixture",
                    mode=mode,
                    observation="off",
                    probe_dir=root,
                    reconcile_ms=50,
                    native_evidence=root / "native.json",
                    live_evidence=root / "live",
                    baseline=root / "baseline",
                )
                fake_transformers = types.SimpleNamespace(
                    AutoTokenizer=types.SimpleNamespace(
                        from_pretrained=lambda *a, **k: tokenizer
                    )
                )
                with (
                    patch.dict(sys.modules, transformers=fake_transformers),
                    patch(
                        "research.agent_resume.pressure.tokenizer_manifest",
                        return_value=dict(tokenizer_files={}),
                    ),
                    patch(
                        "research.agent_resume.pressure.snapshot", return_value=corpus
                    ),
                    patch("httpx.AsyncClient", side_effect=factory),
                    # Synthetic HTTP plumbing; readiness is tested separately.
                    patch(
                        "research.agent_resume.pressure.require_native",
                        return_value="fixture",
                    ),
                    patch(
                        "research.agent_resume.pressure.require_live",
                        return_value="fixture",
                    ),
                    patch(
                        "research.agent_resume.pressure.require_baseline",
                        return_value=None,
                    ),
                    patch(
                        "research.agent_resume.pressure.verify_storage", return_value={}
                    ),
                    patch(
                        "research.agent_resume.pressure.verify_initial_state",
                        return_value={},
                    ),
                    patch(
                        "research.agent_resume.pressure.FileObserver.snapshot",
                        return_value={},
                    ),
                ):
                    if case == "cancelled":
                        execution = asyncio.create_task(execute(args))
                        try:
                            await asyncio.wait_for(generation_started.wait(), 3)
                        except TimeoutError:
                            if execution.done():
                                await (
                                    execution
                                )  # Surface setup errors, not an endless fixture wait.
                            execution.cancel()
                            await asyncio.gather(execution, return_exceptions=True)
                            raise
                        execution.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await execution
                    else:
                        self.assertTrue(await execute(args))
                rows = [
                    json.loads(line)
                    for line in (args.output / "tasks.jsonl").read_text().splitlines()
                ]
                self.assertEqual(len(rows), 2)
                if case == "cancelled":
                    self.assertTrue(all(row["status"] == "CANCELLED" for row in rows))
                    summary = json.loads((args.output / "summary.json").read_text())
                    manifest = json.loads((args.output / "manifest.json").read_text())
                    self.assertFalse(summary["procedure_completed"])
                    self.assertFalse(summary["study_success"])
                    self.assertEqual(summary["cancelled"], 2)
                    self.assertIn("finalized_ns", manifest)
                    self.assertFalse(manifest["procedure_completed"])
                    self.assertTrue(any(row["generations"] for row in rows))
                    continue
                self.assertTrue(all(row["task_success"] for row in rows))
                self.assertTrue(
                    all(
                        g["rid"].startswith("tgp-")
                        for row in rows
                        for g in row["generations"]
                    )
                )


class TestPlugin(unittest.TestCase):
    def test_scheduler_mailbox_and_physical_read_rid_mapping(self):
        import types
        from research.agent_resume.plugin import toolgap_pressure_probe as plugin
        from research.agent_resume.sampling import clock_domain

        events = []
        trace = types.SimpleNamespace(
            event=lambda kind, **data: events.append(dict(kind=kind, **data)),
            install=lambda: None,
            occupancy=lambda cache: {},
        )

        class Scheduler:
            def _process_hicache_events(self):
                return "tick"

        class Cache:
            def match_prefix(self, params):
                return "ordinary-match"

        class Control:
            def submit(self, operation_id, *args, **kwargs):
                self.records = {
                    operation_id: types.SimpleNamespace(
                        handle=types.SimpleNamespace(rid="physical")
                    )
                }
                self.cache = None
                return dict(state="RUNNING")

        class File:
            def batch_get(self, keys):
                trace.event("read", keys=keys, bytes=8)
                return 8

        class Controller:
            def _page_transfer(self, op):
                return File().batch_get(["k"])

        modules = {
            "sglang.srt.managers.scheduler": types.SimpleNamespace(Scheduler=Scheduler),
            "sglang.srt.mem_cache.unified_radix_cache": types.SimpleNamespace(
                UnifiedRadixCache=Cache
            ),
            "sglang.srt.mem_cache.proactive_prefetch": types.SimpleNamespace(
                ProactivePrefetch=Control
            ),
            "sglang.srt.mem_cache.hicache_storage": types.SimpleNamespace(
                HiCacheFile=File
            ),
            "sglang.srt.mem_cache.hybrid_cache.hybrid_cache_controller": types.SimpleNamespace(
                HybridCacheController=Controller
            ),
            "hicache_trace": trace,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / ("a" * 32 + ".request.json")
            request.write_text(
                json.dumps(dict(input_ids=[1], clock_domain=clock_domain()))
            )
            with (
                patch.dict(sys.modules, modules),
                patch.dict("os.environ", TOOLGAP_PRESSURE_PROBE_DIR=directory),
                patch.object(
                    plugin,
                    "probe_prefix",
                    return_value=dict(residency="UNKNOWN_STORAGE"),
                ) as probe,
            ):
                plugin.install()
                plugin.install()  # only one layer of hooks
                scheduler = Scheduler()
                scheduler.tree_cache = Cache()
                self.assertEqual(scheduler._process_hicache_events(), "tick")
                state = json.loads((root / ("a" * 32 + ".response.json")).read_text())
                self.assertEqual(state["clock_domain"], clock_domain())
                self.assertEqual(probe.call_count, 1)
                Control().submit("op")
                Controller()._page_transfer(
                    types.SimpleNamespace(handle=types.SimpleNamespace(rid="physical"))
                )
                File().batch_get(["other"])
            reads = [e for e in events if e["kind"] == "read"]
            self.assertEqual([e["rid"] for e in reads], ["physical", None])
            accepted = [e for e in events if e["kind"] == "control_accepted_end"]
            self.assertEqual(accepted[0]["rid"], "physical")
            self.assertEqual(accepted[0]["operation_id"], "op")


if __name__ == "__main__":
    unittest.main()
