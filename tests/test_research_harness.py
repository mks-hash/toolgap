"""Transport/ownership/format fixtures; no model or GPU performance claims."""

import asyncio
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.agent_resume.adapters import (
    FamilyAdapter,
    ToolCall,
    UnsupportedTemplate,
    aligned_prefix,
)
from research.agent_resume.prepare import ScriptedModel, call_text
from research.agent_resume.runner import GenerationTransport, run_task, settle_owned
from research.agent_resume.live import validate_server, execute
from research.agent_resume.workloads import RepositoryTools, SCHEMA, TASKS
from toolgap import PrefetchAdmission, PrefetchClient


class FormatFixture:
    """Character IDs and illustrative Qwen structure, not a native tokenizer."""

    def encode(self, text, **kwargs):
        return list(text.encode())

    def decode(self, ids, **kwargs):
        return bytes(ids).decode()

    def apply_chat_template(self, messages, **kwargs):
        text = ""
        for message in messages:
            text += "<|im_start|>" + message["role"] + "\n"
            if "tool_calls" in message:
                c = message["tool_calls"][0]["function"]
                text += "<tool_call>\n" + json.dumps(c) + "\n</tool_call>"
            else:
                text += message["content"]
            text += "<|im_end|>\n"
        return text + (
            "<|im_start|>assistant\n" if kwargs["add_generation_prompt"] else ""
        )


def corpus():
    return dict(
        commit="fixture",
        files={
            TASKS[0]["path"]: dict(
                text='response.get("cleanup_pending")\n', sha256="fixture"
            )
        },
    )


class TestFamilyFormats(unittest.TestCase):
    def test_server_validation_refuses_identity_or_setting_changes(self):
        profile = dict(
            model="model",
            revision="revision",
            runtime_candidate_sha="a" * 40,
            server_settings=dict(tp_size=1, pp_size=1),
        )
        deployment = dict(
            model="model",
            revision="revision",
            model_path="/model",
            runtime_sha="a" * 40,
            resolved_cache_mode="FULL",
        )
        info = dict(tp_size=1, pp_size=1, model_path="/model")
        validate_server(info, deployment, profile)
        for changed in [dict(info, tp_size=2), dict(info, model_path="/other")]:
            with self.assertRaises(ValueError):
                validate_server(changed, deployment, profile)
        with self.assertRaises(ValueError):
            validate_server(info, dict(deployment, revision="other"), profile)
        with self.assertRaises(ValueError):
            validate_server(info, dict(deployment, runtime_sha="b" * 40), profile)

    def test_three_families_require_actual_valid_calls(self):
        for family in ("qwen", "mistral", "llama"):
            call = ToolCall(
                "search_repository",
                dict(query="KV"),
                "abc123XYZ" if family == "mistral" else None,
            )
            adapter = FamilyAdapter(family)
            self.assertEqual(adapter.parse(call_text(family, call), {call.name}), call)
            self.assertIsNone(adapter.parse("A final answer", {call.name}))
            with self.assertRaises(ValueError):
                adapter.parse(call_text(family, call), {"other"})

    def test_mistral_rejects_malformed_model_id(self):
        for body in [
            dict(name="t", arguments={}, id="short"),
            dict(name="t", arguments={}, id="12345678!"),
        ]:
            with self.assertRaises(ValueError):
                FamilyAdapter("mistral").parse(
                    "[TOOL_CALLS] " + json.dumps([body]), {"t"}
                )

    def test_multiple_calls_fail_and_final_llama_json_is_not_a_tool(self):
        with self.assertRaises(ValueError):
            FamilyAdapter("mistral").parse("[TOOL_CALLS] [{},{}]", {"t"})
        self.assertIsNone(FamilyAdapter("llama").parse('{"answer":"PASS"}', {"t"}))
        with self.assertRaises(ValueError):
            FamilyAdapter("llama").parse("<|python_tag|>tool.run()", {"t"})

    def test_mistral_system_normalized_before_initial_generation(self):
        raw = [
            dict(role="system", content="rules"),
            dict(role="user", content="question"),
        ]
        changed = FamilyAdapter("mistral").normalize_messages(raw)
        self.assertEqual(changed, [dict(role="user", content="rules\n\nquestion")])
        self.assertEqual(raw[0]["role"], "system")

    def test_exact_noncanonical_decision_ids_are_not_replaced(self):
        t = FormatFixture()
        a = FamilyAdapter("qwen")
        m = [dict(role="user", content="question")]
        prompt = a.prompt(t, m, SCHEMA)
        c = ToolCall("search_repository", dict(query="KV"))
        decision = t.encode(
            '<tool_call>{"arguments":{"query":"KV"},"name":"search_repository"}</tool_call>'
        )
        for end in ("", "<|im_end|>", "<|im_end|>\n"):
            ids = decision + t.encode(end)
            new, _ = a.continuation(t, m, SCHEMA, prompt, ids, c, dict(matches=[]))
            self.assertEqual(new[: len(prompt) + len(ids)], prompt + ids)
            self.assertEqual(t.decode(new).count("</tool_call><|im_end|>"), 1)
        with self.assertRaises(ValueError):
            a.continuation(
                t,
                m,
                SCHEMA,
                prompt,
                decision,
                ToolCall(c.name, dict(query="other")),
                {},
            )

    def test_changed_native_history_fails_closed(self):
        class Broken(FormatFixture):
            def apply_chat_template(self, messages, **kwargs):
                return (
                    "changed" if len(messages) > 1 else ""
                ) + super().apply_chat_template(messages, **kwargs)

        t = Broken()
        a = FamilyAdapter("qwen")
        m = [dict(role="user", content="question")]
        c = ToolCall("search_repository", dict(query="KV"))
        with self.assertRaises(UnsupportedTemplate):
            a.continuation(
                t,
                m,
                SCHEMA,
                a.prompt(t, m, SCHEMA),
                t.encode(call_text("qwen", c)),
                c,
                {},
            )

    def test_page_alignment_excludes_last_saved_token(self):
        self.assertEqual(aligned_prefix(list(range(81))), list(range(80)))
        self.assertEqual(aligned_prefix([1]), [])


class TestUsefulTools(unittest.IsolatedAsyncioTestCase):
    async def test_search_read_and_grading_require_retrieved_evidence(self):
        tools = RepositoryTools(corpus())
        task = TASKS[0]
        call = ToolCall("search_repository", dict(query="cleanup_pending"))
        result = await tools(call)
        records = [dict(call=dict(name=call.name), result=result)]
        answer = dict(answer=task["answer"], evidence=[dict(path=task["path"], line=1)])
        self.assertTrue(tools.grade(task, json.dumps(answer), records))
        self.assertFalse(tools.grade(task, json.dumps(answer), []))
        answer["evidence"].append(dict(path="made-up.py", line=10))
        self.assertFalse(tools.grade(task, json.dumps(answer), records))
        self.assertEqual(tools.read(task["path"], 1, 1)["lines"][0]["line"], 1)

    async def test_no_arbitrary_commands_paths_or_extra_arguments(self):
        tools = RepositoryTools(corpus())
        for call in [
            ToolCall("run_regression", dict(suite="shell")),
            ToolCall("search_repository", dict(query="x", command="echo")),
            ToolCall("read_source", dict(path="/etc/passwd", start=1, end=2)),
        ]:
            with self.assertRaises(ValueError):
                await tools(call)


class TestRunner(unittest.IsolatedAsyncioTestCase):
    async def test_live_diagnostic_cli_records_rows_and_controls_with_mock_model(self):
        from research.agent_resume.sampling import clock_domain

        tokenizer = FormatFixture()
        profile = dict(
            model="model",
            revision="revision",
            family="qwen",
            profile_id="qwen",
            tokenizer_files={},
            source_commit="fixture",
            runtime_candidate_sha="a" * 40,
            server_settings=dict(context_length=8192),
        )
        deployment = dict(
            model="model",
            revision="revision",
            model_path="/model",
            runtime_sha="a" * 40,
            resolved_cache_mode="FULL",
            clock_domain=clock_domain(),
            admin_auth_required=True,
        )
        original_http = httpx.AsyncClient
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "profile.json").write_text(json.dumps(profile))
            (root / "deployment.json").write_text(json.dumps(deployment))
            for mode in ("request_time", "proactive"):
                texts = iter(self.texts())

                def handler(request):
                    if request.url.path == "/get_server_info":
                        return httpx.Response(
                            200,
                            json=dict(
                                context_length=8192,
                                model_path="/model",
                                admin_api_key="fixture-admin",
                                launch_command="--admin-api-key fixture-admin",
                            ),
                        )
                    body = json.loads(request.content)
                    if request.url.path == "/generate":
                        result = dict(
                            output_ids=tokenizer.encode(next(texts)),
                            meta_info=dict(finish_reason=dict(type="stop")),
                        )
                        return httpx.Response(
                            200,
                            text="data: " + json.dumps(result) + "\n\ndata: [DONE]\n\n",
                        )
                    self.assertEqual(
                        request.headers.get("Authorization"), "Bearer fixture-admin"
                    )
                    return httpx.Response(
                        200,
                        json=dict(
                            success=True,
                            result=dict(
                                operation_id=body["operation_id"],
                                state="SUCCESS",
                                cleanup_pending=False,
                                restored_tokens=0,
                                restored_bytes=0,
                            ),
                        ),
                    )

                def http_factory(*args, **kwargs):
                    kwargs["transport"] = httpx.MockTransport(handler)
                    return original_http(*args, **kwargs)

                args = types.SimpleNamespace(
                    profile=root / "profile.json",
                    deployment=root / "deployment.json",
                    tokenizer=root,
                    output=root / mode,
                    server="http://fixture",
                    mode=mode,
                    reconcile_ms=None,
                    native_evidence=root / "native.json",
                    probe_dir=root,
                )
                fake_transformers = types.SimpleNamespace(
                    AutoTokenizer=types.SimpleNamespace(
                        from_pretrained=lambda *a, **k: tokenizer
                    )
                )
                with (
                    patch.dict("os.environ", TOOLGAP_STUDY_ADMIN_KEY="fixture-admin"),
                    patch.dict(sys.modules, transformers=fake_transformers),
                    patch(
                        "research.agent_resume.live.tokenizer_manifest",
                        return_value=dict(tokenizer_files={}),
                    ),
                    patch("research.agent_resume.live.snapshot", return_value=corpus()),
                    patch("research.agent_resume.live.TASKS", [TASKS[0]]),
                    patch("httpx.AsyncClient", side_effect=http_factory),
                    # Synthetic transport fixtures do not supply live proof.
                    patch(
                        "research.agent_resume.live.require_native",
                        return_value="fixture",
                    ),
                    patch("research.agent_resume.live.verify_storage", return_value={}),
                    patch(
                        "research.agent_resume.live.FileObserver.snapshot",
                        return_value={},
                    ),
                ):
                    self.assertTrue(await execute(args))
                self.assertNotIn(
                    "fixture-admin", (args.output / "manifest.json").read_text()
                )
                row = json.loads((args.output / "tasks.jsonl").read_text())
                self.assertTrue(row["task_success"])
                self.assertEqual(bool(row["control_events"]), mode == "proactive")
                self.assertEqual(row["cache_state"], "UNMEASURED")

    async def test_declared_admin_auth_without_key_fails_before_transport(self):
        from research.agent_resume.live import control_headers, retained_server_info

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                control_headers({"admin_auth_required": True})
            self.assertIsNone(control_headers({}))
        self.assertEqual(
            retained_server_info(
                {
                    "server_args": {"admin_api_key": "secret", "page_size": 16},
                    "launch_command": "secret",
                    "states": [{"api_key": "secret"}],
                }
            ),
            {"server_args": {"page_size": 16}, "states": [{}]},
        )

    async def test_cleanup_timeout_retains_owner_and_cannot_cancel_other_session(self):
        actions = []

        async def handler(request):
            body = json.loads(request.content)
            actions.append(body["action"])
            return httpx.Response(
                200,
                json=dict(
                    success=True,
                    result=dict(
                        operation_id=body["operation_id"],
                        state="RUNNING",
                        cleanup_pending=True,
                        restored_tokens=0,
                        restored_bytes=0,
                    ),
                ),
            )

        async with PrefetchClient(
            "http://fixture", transport=httpx.MockTransport(handler)
        ) as client:
            async with PrefetchAdmission(client) as policy:
                lease = await policy.submit("owner", [1])
                records = await settle_owned(
                    policy, [], session_id="other", abandoned=True, timeout=0.01
                )
                self.assertEqual(actions, ["submit"])
                self.assertEqual(records, [])
                records = await settle_owned(
                    policy, [], session_id="owner", abandoned=True, timeout=0.01
                )
                self.assertIn("cancel", actions)
                self.assertIs(policy.active, lease)
                self.assertFalse(records[-1]["cleanup_confirmed"])

    async def test_abandoning_later_step_does_not_assert_all_restores_unused(self):
        # An earlier continuation may have consumed this published restore;
        # trajectory failure is not operation-specific evidence of zero usage.
        from unittest.mock import AsyncMock, Mock

        lease = types.SimpleNamespace(
            cancel=AsyncMock(
                return_value=dict(state="PUBLISHED", cleanup_pending=False)
            ),
            finish=Mock(),
            decision={},
            timing={},
        )
        task = asyncio.create_task(asyncio.sleep(0, result=lease))
        policy = types.SimpleNamespace(active=None)
        records = await settle_owned(policy, [task], session_id="owner", abandoned=True)
        lease.cancel.assert_awaited_once()
        lease.finish.assert_called_once_with(used_tokens=None)
        self.assertEqual(records[0]["state"]["state"], "PUBLISHED")

    async def test_tool_failure_cancels_only_owned_operation(self):
        accepted = asyncio.Event()
        actions = []

        async def handler(request):
            body = json.loads(request.content)
            actions.append(body["action"])
            terminal = body["action"] == "cancel"
            accepted.set()
            return httpx.Response(
                200,
                json=dict(
                    success=True,
                    result=dict(
                        operation_id=body["operation_id"],
                        state="CANCELLED" if terminal else "RUNNING",
                        cleanup_pending=not terminal,
                        restored_tokens=0,
                        restored_bytes=0,
                    ),
                ),
            )

        class BrokenTools(RepositoryTools):
            async def __call__(self, call):
                await accepted.wait()
                raise RuntimeError("actual tool failed")

        async with PrefetchClient(
            "http://fixture", transport=httpx.MockTransport(handler)
        ) as client:
            async with PrefetchAdmission(client) as policy:
                row = await run_task(
                    FamilyAdapter("qwen"),
                    FormatFixture(),
                    self.model(self.texts()),
                    BrokenTools(corpus()),
                    TASKS[0],
                    policy=policy,
                )
                self.assertEqual(row["status"], "FAILED")
                self.assertEqual(actions, ["submit", "cancel"])
                self.assertIsNone(policy.active)

    def model(self, texts):
        return ScriptedModel(FormatFixture(), texts)

    async def run_fixture(self, model, **kwargs):
        return await run_task(
            FamilyAdapter("qwen"),
            FormatFixture(),
            model,
            RepositoryTools(corpus()),
            TASKS[0],
            **kwargs,
        )

    def texts(self):
        return [
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

    async def test_two_rounds_and_wrong_answers_are_preserved(self):
        row = await self.run_fixture(self.model(self.texts()))
        self.assertTrue(row["task_success"])
        self.assertEqual(row["cache_state"], "UNMEASURED")
        a, b = row["generations"]
        self.assertEqual(
            b["input_ids"][: len(a["input_ids"]) + len(a["output_ids"])],
            a["input_ids"] + a["output_ids"],
        )
        row = await self.run_fixture(self.model(['{"answer":"wrong","evidence":[]}']))
        self.assertEqual(row["status"], "COMPLETED")
        self.assertFalse(row["task_success"])

    async def test_failed_model_call_stays_failed(self):
        row = await self.run_fixture(self.model(["<tool_call>{}</tool_call>"]))
        self.assertEqual(row["status"], "FAILED")
        self.assertFalse(row["task_success"])
        self.assertEqual(row["tools"], [])

    async def test_context_and_round_budgets_do_not_hide_failures(self):
        row = await self.run_fixture(self.model(self.texts()), context_limit=1)
        self.assertEqual(row["status"], "FAILED")
        row = await self.run_fixture(self.model(self.texts()), max_tool_rounds=0)
        self.assertEqual(row["status"], "FAILED")

    async def test_scripted_and_live_reserve_the_same_output_budget(self):
        from research.agent_resume.runner import generation_contract, initial_messages
        from research.agent_resume.workloads import SCHEMA

        model = self.model(self.texts())
        self.assertEqual(model.max_new_tokens, GenerationTransport(None).max_new_tokens)
        self.assertEqual(model.max_new_tokens, generation_contract()["max_new_tokens"])
        adapter = FamilyAdapter("qwen")
        tokenizer = FormatFixture()
        # Enough space for a scripted call + empty result, but no 256-token
        # output reservation. Reject before executing real tools in both modes.
        prompt = adapter.prompt(tokenizer, initial_messages(adapter, TASKS[0]), SCHEMA)
        row = await self.run_fixture(model, context_limit=len(prompt) + 200)
        self.assertEqual(row["status"], "FAILED")
        self.assertEqual(row["tools"], [])

    async def test_malformed_stream_metadata_preserves_partial_evidence(self):
        async def handler(request):
            return httpx.Response(
                200,
                text='data: {"output_ids":[1],"meta_info":null}\n\ndata: [DONE]\n\n',
            )

        async with httpx.AsyncClient(
            base_url="http://fixture", transport=httpx.MockTransport(handler)
        ) as http:
            with self.assertRaisesRegex(ValueError, "metadata") as raised:
                await GenerationTransport(http).generate([2], "salt")
        partial = raised.exception.generation_evidence
        self.assertEqual(partial["output_ids"], [1])
        self.assertIsNone(partial["meta_info"])
        self.assertEqual(partial["sampling_params"]["max_new_tokens"], 256)

    async def test_continuation_does_not_wait_for_slow_submit(self):
        continuation = asyncio.Event()
        requests = []

        async def handler(request):
            body = json.loads(request.content)
            requests.append(body["action"])
            if body["action"] == "submit":
                await asyncio.wait_for(continuation.wait(), 1)
            return httpx.Response(
                200,
                json=dict(
                    success=True,
                    result=dict(
                        operation_id=body["operation_id"],
                        state="SUCCESS",
                        cleanup_pending=False,
                        restored_tokens=0,
                        restored_bytes=0,
                    ),
                ),
            )

        class Model(ScriptedModel):
            async def generate(self, ids, salt):
                if requests:
                    continuation.set()
                return await super().generate(ids, salt)

        async with PrefetchClient(
            "http://fixture", transport=httpx.MockTransport(handler)
        ) as client:
            async with PrefetchAdmission(client) as policy:
                row = await self.run_fixture(
                    Model(FormatFixture(), self.texts()), policy=policy
                )
                self.assertTrue(row["task_success"])
                self.assertTrue(continuation.is_set())
                self.assertIsNone(policy.active)
                self.assertNotIn("cancel", requests)

    async def test_cancelled_task_records_outcome(self):
        started = asyncio.Event()
        records = []

        class Blocking:
            async def generate(self, ids, salt):
                started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(
            self.run_fixture(Blocking(), on_record=records.append)
        )
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(records[0]["status"], "CANCELLED")

    async def test_stream_records_first_token_and_actual_ids(self):
        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["sampling_params"]["temperature"], 0)
            return httpx.Response(
                200,
                text='data: {"output_ids":[8]}\n\ndata: {"output_ids":[8,9],"meta_info":{"cache":2,"finish_reason":{"type":"stop"}}}\n\ndata: [DONE]\n\n',
            )

        async with httpx.AsyncClient(
            base_url="http://fixture", transport=httpx.MockTransport(handler)
        ) as http:
            row = await GenerationTransport(http).generate([1, 2], "salt")
        self.assertEqual(row["output_ids"], [8, 9])
        self.assertLessEqual(row["submitted_ns"], row["first_token_ns"])
        self.assertLessEqual(row["first_token_ns"], row["completed_ns"])


if __name__ == "__main__":
    unittest.main()
