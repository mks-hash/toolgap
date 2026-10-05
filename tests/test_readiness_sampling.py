"""Offline gates and temporal observation semantics; no live model proof."""

import asyncio
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from research.agent_resume import readiness
from research.agent_resume.adapters import FamilyAdapter
from research.agent_resume.prepare import ScriptedModel, call_text
from research.agent_resume.runner import run_task
from research.agent_resume.sampling import (
    ToolWindowSamples,
    clock_domain,
    window_summary,
)
from research.agent_resume.workloads import RepositoryTools, TASKS
from research.agent_resume.adapters import ToolCall
from test_research_harness import FormatFixture, corpus


def native_record(profile):
    return dict(
        validation_type="OFFLINE_NATIVE_REFERENCE_CONFORMANCE",
        passed=True,
        profile_id=FamilyAdapter.from_profile(profile).profile_id,
        tokenizer_files=profile["tokenizer_files"],
        transformers=readiness.metadata.version("transformers"),
        checks=[
            dict(
                render_tokenize_agreement=True,
                native_full_text_agreement=True,
                exact_saved_ids=True,
            )
        ]
        * 2,
        source_sha256={
            name: readiness.file_hash(Path(readiness.__file__).parent / name)
            for name in readiness.NATIVE_SOURCES
        },
    )


def live_rows():
    # Deliberately synthetic records for gate testing, never saved as research evidence.
    return [
        dict(
            task_id=t["id"],
            status="COMPLETED",
            task_success=True,
            tools=[dict(call=dict(name="search_repository"))],
            prefetch=[],
            generations=[
                dict(
                    input_ids=[1],
                    output_ids=[2],
                    rid="fixture-a",
                    meta_info=dict(finish_reason="stop"),
                ),
                dict(
                    input_ids=[1, 2, 3],
                    output_ids=[4],
                    rid="fixture-b",
                    meta_info=dict(finish_reason="stop"),
                ),
            ],
        )
        for t in TASKS
    ]


class TestReadiness(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(
            (readiness.ROOT / "research/agent_resume/profiles/qwen.json").read_text()
        )

    def test_same_boot_with_different_time_namespace_is_not_comparable(self):
        with patch(
            "research.agent_resume.sampling.os.readlink", return_value="time:[one]"
        ):
            one = clock_domain()
        with patch(
            "research.agent_resume.sampling.os.readlink", return_value="time:[two]"
        ):
            two = clock_domain()
        self.assertNotEqual(one, two)

    def test_native_gate_rejects_scripted_stale_template_and_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "native.json"
            record = native_record(self.profile)
            path.write_text(json.dumps(record))
            self.assertEqual(
                readiness.require_native(path, self.profile), readiness.file_hash(path)
            )
            for changed in (
                dict(record, validation_type="SCRIPTED_CPU_FIXTURE"),
                dict(record, source_sha256={}),
                dict(record, profile_id="wrong"),
                dict(record, checks=[]),
                dict(record, tokenizer_files={}),
                dict(record, passed=False),
            ):
                with self.subTest(changed=changed.keys()):
                    path.write_text(json.dumps(changed))
                    with self.assertRaises(ValueError):
                        readiness.require_native(path, self.profile)

    def test_live_dimensions_do_not_promote_fit_or_pressure(self):
        rows = live_rows()
        result = readiness.live_result(rows, [t["id"] for t in TASKS], False)
        self.assertTrue(result["study_success"])
        self.assertEqual(result["dimensions"]["model_fit"], "UNKNOWN")
        self.assertEqual(result["dimensions"]["performance"], "NOT_RUN")
        self.assertIsNone(result["wasted_prefetch_bytes"])
        for kind in (
            "wrong-answer",
            "truncated",
            "scripted",
            "no-tool",
            "changed-ids",
            "cleanup",
            "missing-task",
        ):
            modified = copy.deepcopy(rows)
            if kind == "wrong-answer":
                modified[0]["task_success"] = False
            elif kind == "truncated":
                modified[0]["generations"][-1]["meta_info"] = {}
            elif kind == "scripted":
                modified[0]["generations"][0]["validation_type"] = (
                    "SCRIPTED_CPU_FIXTURE"
                )
            elif kind == "no-tool":
                modified[0]["tools"] = []
            elif kind == "changed-ids":
                modified[0]["generations"][-1]["input_ids"] = [9]
            elif kind == "cleanup":
                modified[0]["prefetch"] = [dict(cleanup_confirmed=False)]
            else:
                modified.pop()
            with self.subTest(kind=kind):
                result = readiness.live_result(
                    modified, [t["id"] for t in TASKS], False
                )
                self.assertTrue(result["procedure_completed"])
                self.assertFalse(result["study_success"])

    def test_exact_prefix_contract_is_independent_of_answer_quality(self):
        rows = live_rows()
        rows[0]["task_success"] = False
        result = readiness.live_result(rows, [t["id"] for t in TASKS], False)
        self.assertEqual(result["dimensions"]["exact_continuation"], "PASS")
        self.assertEqual(result["dimensions"]["correctness"], "FAIL")
        self.assertFalse(result["study_success"])
        for row in rows:
            row["generations"] = row["generations"][:1]
        result = readiness.live_result(rows, [t["id"] for t in TASKS], False)
        self.assertEqual(result["dimensions"]["exact_continuation"], "NOT_RUN")
        self.assertFalse(result["study_success"])

    def test_missing_or_changed_continuation_ids_fail_contract(self):
        for key, value in (("input_ids", None), ("output_ids", []), ("input_ids", [9])):
            rows = live_rows()
            rows[0]["generations"][0][key] = value
            result = readiness.live_result(rows, [t["id"] for t in TASKS], False)
            self.assertEqual(result["dimensions"]["exact_continuation"], "FAIL")
            self.assertFalse(result["study_success"])

    def test_malformed_retained_metadata_is_failure_not_classification_crash(self):
        rows = live_rows()
        rows[0]["generations"][0]["meta_info"] = None
        result = readiness.live_result(rows, [t["id"] for t in TASKS], False)
        self.assertFalse(result["study_success"])
        self.assertEqual(result["dimensions"]["transport"], "FAIL")

    def test_live_gate_binds_code_packages_profile_and_raw_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = live_rows()
            (root / "tasks.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
            (root / "manifest.json").write_text("{}")
            (root / "control-events.json").write_text("[]")
            record = readiness.live_result(rows, [t["id"] for t in TASKS], False)
            record.update(
                provenance=readiness.provenance(self.profile),
                cleanup_unresolved=False,
                artifacts_sha256={
                    name: readiness.file_hash(root / name)
                    for name in ("tasks.jsonl", "manifest.json", "control-events.json")
                },
            )
            (root / "readiness.json").write_text(json.dumps(record))
            self.assertTrue(readiness.require_live(root, self.profile))
            modified = copy.deepcopy(self.profile)
            modified["server_settings"]["hicache_size"] = 1
            with self.assertRaises(ValueError):
                readiness.require_live(root, modified)
            with patch.object(readiness, "provenance", return_value={}):
                with self.assertRaises(ValueError):
                    readiness.require_live(root, self.profile)
            (root / "tasks.jsonl").write_text("[]")
            with self.assertRaises(ValueError):
                readiness.require_live(root, self.profile)

    def test_pressure_gate_rejects_unrelated_or_changed_workload(self):
        from research.agent_resume.load import AUDITS, fixed_trace

        packet = dict(
            profile=self.profile,
            arrivals=fixed_trace(6),
            measurement_contract=readiness.measurement_contract(),
        )
        for item in packet["arrivals"]:
            task = next(t for t in AUDITS if t["id"] == item["audit_id"])
            item["task"] = dict(
                task, initial_input_ids=[1], context_pack="actual pinned context"
            )
        items, contract = readiness.pressure_gate_workload(packet)
        self.assertEqual(len(items), 3)
        self.assertEqual(contract["max_tool_rounds"], 6)
        rows = live_rows()
        for row, item in zip(rows, items):
            row.update(task_id=item["task"]["id"], cache_salt=item["cache_salt"])
            for generation in row["generations"]:
                generation["sampling_params"] = dict(contract["generation"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tasks.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
            (root / "manifest.json").write_text(
                json.dumps(dict(profile=self.profile, task_contract=contract))
            )
            (root / "control-events.json").write_text("[]")
            record = readiness.live_result(rows, contract["expected_ids"], False)
            record.update(
                task_contract=contract,
                provenance=readiness.provenance(self.profile),
                cleanup_unresolved=False,
                artifacts_sha256={
                    name: readiness.file_hash(root / name)
                    for name in ("manifest.json", "tasks.jsonl", "control-events.json")
                },
            )
            (root / "readiness.json").write_text(json.dumps(record))
            self.assertTrue(readiness.require_live(root, self.profile, packet))
            changed_rows = json.loads(json.dumps(rows))
            changed_rows[0]["generations"][0]["sampling_params"]["max_new_tokens"] = 512
            (root / "tasks.jsonl").write_text(
                "\n".join(json.dumps(r) for r in changed_rows)
            )
            record["artifacts_sha256"]["tasks.jsonl"] = readiness.file_hash(
                root / "tasks.jsonl"
            )
            (root / "readiness.json").write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "inputs/limits"):
                readiness.require_live(root, self.profile, packet)
            (root / "tasks.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
            record["artifacts_sha256"]["tasks.jsonl"] = readiness.file_hash(
                root / "tasks.jsonl"
            )
            (root / "readiness.json").write_text(json.dumps(record))
            for kind in ("context", "budget", "unrelated", "changed-ids", "salt"):
                changed = copy.deepcopy(packet)
                if kind == "context":
                    changed["arrivals"][0]["task"]["context_pack"] = "different"
                elif kind == "budget":
                    changed["measurement_contract"]["max_tool_rounds"] = 4
                elif kind == "unrelated":
                    changed["arrivals"][0]["task"] = TASKS[0]
                elif kind == "changed-ids":
                    changed["arrivals"][0]["task"]["initial_input_ids"] = [9]
                else:
                    changed["arrivals"][0]["cache_salt"] = "different"
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    readiness.require_live(root, self.profile, changed)
            record["task_contract"] = dict(kind="LEGACY_DIAGNOSTIC", max_tool_rounds=4)
            (root / "readiness.json").write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                readiness.require_live(root, self.profile, packet)

    def test_namespace_isolated_by_revision_precision_layout_and_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = readiness.initialize_storage(self.profile, directory)
            settings = self.profile["server_settings"]
            state = dict(
                storage_identity=dict(
                    namespace=root.name,
                    root_sha256=readiness.hashlib.sha256(
                        str(root.resolve()).encode()
                    ).hexdigest(),
                    page_size=settings["page_size"],
                    layout=settings["hicache_mem_layout"],
                    kv_dtype=settings["dtype"],
                    bytes_per_token=28672,
                )
            )
            deployment = dict(storage_path=str(root))
            state["runtime_identity"] = dict(
                status="OBSERVED_CHECKOUT",
                head=self.profile["runtime_candidate_sha"],
                tracked_runtime_clean=True,
            )
            self.assertEqual(
                readiness.verify_storage(self.profile, deployment, state)["namespace"],
                root.name,
            )
            for wrong in (
                dict(status="UNKNOWN"),
                dict(
                    status="OBSERVED_CHECKOUT",
                    head="f" * 40,
                    tracked_runtime_clean=True,
                ),
                dict(state["runtime_identity"], tracked_runtime_clean=False),
            ):
                with (
                    self.subTest(runtime=wrong),
                    self.assertRaisesRegex(ValueError, "imported runtime"),
                ):
                    readiness.verify_storage(
                        self.profile, deployment, dict(state, runtime_identity=wrong)
                    )
            with self.assertRaises(FileExistsError):
                readiness.initialize_storage(self.profile, directory)
            for key in ("revision", "dtype"):
                modified = dict(self.profile, **{key: "different"})
                self.assertNotEqual(readiness.storage_namespace(modified), root.name)
                with self.assertRaises(ValueError):
                    readiness.verify_storage(modified, deployment, state)
            for key in (
                "layout",
                "kv_dtype",
                "root_sha256",
                "page_size",
                "bytes_per_token",
            ):
                changed = dict(
                    state,
                    storage_identity=dict(state["storage_identity"], **{key: None}),
                )
                with self.subTest(key=key), self.assertRaises(ValueError):
                    readiness.verify_storage(self.profile, deployment, changed)
            (root / "toolgap-identity.json").write_text("{}")
            with self.assertRaises(ValueError):
                readiness.verify_storage(self.profile, deployment, state)

    def test_comparison_requires_bound_baseline_and_retains_trigger_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(
                json.dumps(
                    dict(
                        mode="request_time",
                        packet_sha256="same",
                        observation="memory-and-stat",
                        measurement_contract=readiness.measurement_contract(),
                        profile=self.profile,
                        provenance=readiness.provenance(self.profile),
                        initial_state=dict(
                            policy=readiness.measurement_contract()["initial_state"],
                            device_capacity_tokens=8192,
                            host_capacity_tokens=35000,
                        ),
                        observed_storage=dict(
                            page_size=16,
                            layout="page_first",
                            kv_dtype="bfloat16",
                            bytes_per_token=28672,
                            prefetch_threshold=256,
                        ),
                    )
                )
            )
            (root / "summary.json").write_text(
                json.dumps(
                    dict(
                        tasks=12,
                        successful=12,
                        cleanup_unresolved=False,
                        procedure_completed=True,
                        study_success=True,
                    )
                )
            )
            (root / "tasks.jsonl").write_text("fixture")
            (root / "server-trace.jsonl").write_text("fixture")
            report = dict(
                physical_read_batches=0,
                boundaries=[],
                source_artifacts_sha256={
                    name: readiness.file_hash(root / name)
                    for name in (
                        "manifest.json",
                        "summary.json",
                        "tasks.jsonl",
                        "server-trace.jsonl",
                    )
                },
            )
            (root / "trace-report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "No matched"):
                readiness.require_baseline(root, "same", "memory-and-stat")
            report.update(
                physical_read_batches=1,
                boundaries=[
                    dict(
                        cache_window_summary=dict(
                            first_eligible_during_tool=dict(
                                eligible_tokens=64, admission_eligible=True
                            )
                        )
                    )
                ],
            )
            (root / "trace-report.json").write_text(json.dumps(report))
            result = readiness.require_baseline(root, "same", "memory-and-stat")
            self.assertEqual(result["dispatch_trigger_reachability"], "UNKNOWN")
            self.assertFalse(result["performance_validated"])
            with self.assertRaises(ValueError):
                readiness.require_baseline(root, "wrong-packet", "memory-and-stat")
            # All successful rows do not authorize a comparison from an interrupted block.
            (root / "summary.json").write_text(
                json.dumps(
                    dict(
                        tasks=12,
                        successful=12,
                        cleanup_unresolved=False,
                        procedure_completed=False,
                        study_success=False,
                    )
                )
            )
            report["source_artifacts_sha256"]["summary.json"] = readiness.file_hash(
                root / "summary.json"
            )
            (root / "trace-report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "No matched"):
                readiness.require_baseline(root, "same", "memory-and-stat")
            (root / "summary.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                readiness.require_baseline(root, "same", "memory-and-stat")

    def test_whole_block_start_rejects_pilot_residency_and_previous_l3(self):
        with tempfile.TemporaryDirectory() as directory:
            root = readiness.initialize_storage(self.profile, directory)
            deployment = dict(storage_path=str(root))
            state = dict(
                host_used_tokens=0,
                inflight_tokens=0,
                ongoing_prefetch_count=0,
                host_available_tokens=35000,
                device_capacity_tokens=8192,
                device_available_tokens=8192,
            )
            self.assertEqual(
                readiness.verify_initial_state(deployment, state)["policy"],
                readiness.measurement_contract()["initial_state"],
            )
            for key in (
                "host_used_tokens",
                "inflight_tokens",
                "ongoing_prefetch_count",
                "device_available_tokens",
            ):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    readiness.verify_initial_state(deployment, dict(state, **{key: 1}))
            (root / "old-prefix.bin").write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "file L3"):
                readiness.verify_initial_state(deployment, state)


class TestSampling(unittest.IsolatedAsyncioTestCase):
    async def test_slow_observer_never_blocks_tool_or_continuation(self):
        continuation, observing, tool_started = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        token = FormatFixture()
        texts = [
            call_text(
                "qwen", ToolCall("search_repository", dict(query="cleanup_pending"))
            ),
            json.dumps(
                dict(
                    answer="cleanup_pending",
                    evidence=[dict(path=TASKS[0]["path"], line=1)],
                )
            ),
        ]

        class Model(ScriptedModel):
            async def generate(self, ids, salt):
                if tool_started.is_set():
                    continuation.set()
                    await asyncio.sleep(0)  # fixture lets the observer complete
                return await super().generate(ids, salt)

        class Tools(RepositoryTools):
            async def __call__(self, call):
                tool_started.set()
                await observing.wait()
                return await super().__call__(call)

        async def observe(ids, salt):
            observing.set()
            await continuation.wait()  # old awaited observer deadlocks here
            return dict(
                clock_domain=clock_domain(),
                cache_read_started_ns=time.monotonic_ns(),
                observation_completed_ns=time.monotonic_ns(),
            )

        row = await asyncio.wait_for(
            run_task(
                FamilyAdapter("qwen"),
                token,
                Model(token, texts),
                Tools(corpus()),
                TASKS[0],
                on_boundary=observe,
            ),
            1,
        )
        self.assertTrue(row["task_success"])
        self.assertTrue(continuation.is_set())
        self.assertTrue(row["tools"][0]["observer_cleanup_confirmed"])
        summary = row["tools"][0]["cache_window_summary"]
        self.assertEqual(summary["dispatch_state"], "UNKNOWN")
        self.assertIsNone(summary["first_eligible"])

    async def test_timeout_budget_and_reaping(self):
        active = 0

        async def blocked(ids, salt):
            nonlocal active
            active += 1
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1

        step = {}
        window = ToolWindowSamples(
            blocked,
            [1] * 16,
            "salt",
            step,
            config=dict(interval_ms=1, max_samples=3, timeout_ms=1),
        )
        await asyncio.sleep(0.015)
        window.continuation_boundary()
        await asyncio.sleep(0.01)
        await window.finish()
        self.assertEqual(active, 0)
        self.assertEqual(len(step["cache_samples"]), 3)
        self.assertTrue(
            all(
                s["status"] == "UNKNOWN" and s.get("reason") == "TimeoutError"
                for s in step["cache_samples"]
            )
        )
        self.assertTrue(step["observer_cleanup_confirmed"])

    async def test_bad_observer_and_sampling_config_have_no_generation_effects(self):
        step = {}

        async def invalid(ids, salt):
            return None

        window = ToolWindowSamples(
            invalid,
            [1],
            "salt",
            step,
            config=dict(interval_ms=1, max_samples=1, timeout_ms=1),
        )
        await window.task
        await window.finish()
        self.assertEqual(step["cache_samples"][0]["reason"], "ValueError")
        model = ScriptedModel(FormatFixture(), [])
        with patch.object(model, "generate") as generated:
            row = await run_task(
                FamilyAdapter("qwen"),
                FormatFixture(),
                model,
                RepositoryTools(corpus()),
                TASKS[0],
                on_boundary=invalid,
                sampling_config=dict(interval_ms=0, max_samples=1, timeout_ms=1),
            )
        generated.assert_not_called()
        self.assertEqual(row["status"], "FAILED")

    def test_interval_censoring_late_unknown_and_tool_window(self):
        def sample(start, end, available, resident, **extra):
            return dict(
                status="OBSERVED",
                state=dict(
                    clock_domain=clock_domain(),
                    cache_read_started_ns=start,
                    observation_completed_ns=end,
                    storage_check="DIRECT_STAT_NO_BACKEND_CACHE",
                    page_size=16,
                    prefetch_threshold=64,
                    storage_available_tokens=available,
                    resident_prefix_tokens=resident,
                    **extra,
                ),
            )

        step = dict(
            dispatched_ns=100,
            completed_ns=500,
            continuation_submitted_ns=800,
            prefix_ids=[1] * 128,
            cache_samples=[
                sample(150, 200, 128, 128),
                sample(300, 350, 128, 0),
                sample(600, 650, 128, 0),
                sample(700, 900, 128, 0),
            ],
        )
        summary = window_summary(step)
        self.assertEqual(summary["opportunity"], "OBSERVED_FILE_AVAILABLE")
        self.assertEqual(summary["transition_interval_ns"], [150, 350])
        self.assertEqual(summary["late_samples"], 1)
        self.assertEqual(
            summary["first_eligible_during_tool"]["eligible_span"], [0, 128]
        )
        self.assertGreater(
            summary["first_eligible_during_tool"]["remaining_tool_ms"], 0
        )
        self.assertEqual(summary["samples"][-1]["remaining_tool_ms"], 0)
        self.assertIsNone(summary["consumed_restore_tokens"])
        for changed in (
            dict(step, cache_samples=[sample(100, 150, None, 0)]),
            dict(step, cache_samples=[]),
            dict(step, cache_samples=[sample(100, 150, 127, 0)]),
        ):
            with self.subTest(changed=changed["cache_samples"]):
                self.assertEqual(window_summary(changed)["opportunity"], "UNKNOWN")
        changed = dict(step, cache_samples=[sample(100, 150, 0, 128)])
        self.assertEqual(
            window_summary(changed)["opportunity"], "NOT_OBSERVED_AT_SAMPLES"
        )
        changed = dict(step, cache_samples=[sample(600, 650, 128, 0)])
        self.assertIsNone(window_summary(changed)["first_eligible_during_tool"])
        bad_clock = sample(100, 150, 128, 0)
        bad_clock["state"]["clock_domain"] = "another-boot"
        self.assertEqual(
            window_summary(dict(step, cache_samples=[bad_clock]))["opportunity"],
            "UNKNOWN",
        )
        below_threshold = sample(100, 150, 128, 0)
        below_threshold["state"]["prefetch_threshold"] = 256
        self.assertEqual(
            window_summary(dict(step, cache_samples=[below_threshold]))["opportunity"],
            "NOT_OBSERVED_AT_SAMPLES",
        )


class TestFailClosedCLI(unittest.IsolatedAsyncioTestCase):
    async def test_pressure_rejects_unverified_profile_before_http_or_tools(self):
        from research.agent_resume.pressure import execute
        import types

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = dict(
                profile=json.loads(
                    (
                        readiness.ROOT / "research/agent_resume/profiles/qwen.json"
                    ).read_text()
                ),
                measurement_contract=readiness.measurement_contract(),
            )
            (root / "packet.json").write_text(
                json.dumps(dict(packet=packet, sha256=readiness.digest(packet)))
            )
            (root / "native.json").write_text(
                json.dumps(dict(validation_type="SCRIPTED_CPU_FIXTURE", passed=True))
            )
            args = types.SimpleNamespace(
                packet=root / "packet.json",
                native_evidence=root / "native.json",
                reconcile_ms=50,
            )
            with patch("research.agent_resume.pressure.httpx.AsyncClient") as http:
                with self.assertRaisesRegex(ValueError, "native reference"):
                    await execute(args)
                http.assert_not_called()
                (root / "native.json").write_text(
                    json.dumps(native_record(packet["profile"]))
                )
                args.live_evidence = root / "live"
                args.live_evidence.mkdir()
                (args.live_evidence / "readiness.json").write_text(
                    json.dumps(
                        dict(validation_type="SCRIPTED_CPU_FIXTURE", passed=True)
                    )
                )
                with self.assertRaisesRegex(ValueError, "useful live"):
                    await execute(args)
                http.assert_not_called()
