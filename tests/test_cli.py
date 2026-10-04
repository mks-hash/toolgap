"""CLI contract tests: exact IDs, uncertain ownership, read-only diagnostics."""

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from toolgap import cli
from toolgap.diagnostics import manifest


def state(operation_id, outcome="RUNNING", *, pending=False, restored=0):
    return dict(
        operation_id=operation_id,
        state=outcome,
        requested_tokens=64,
        restored_tokens=restored,
        restored_bytes=restored * 8,
        elapsed_ms=1.5,
        cleanup_pending=pending,
        host_available_tokens=1024,
        inflight_tokens=64 if outcome == "RUNNING" or pending else 0,
    )


class CLITest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.prefix = self.directory / "prefix.json"
        self.prefix.write_text(
            json.dumps(
                dict(
                    input_ids=list(range(64)),
                    cache_salt="original",
                    operation_id="owned",
                    ttl_ms=1000,
                )
            )
        )

    def invoke(self, argv, handler, *, env=None, stdin=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = cli.main(
            argv + ["--json"],
            stdout=stdout,
            stderr=stderr,
            stdin=stdin or io.StringIO(),
            environ=env or {},
            transport=httpx.MockTransport(handler),
        )
        self.assertEqual(stderr.getvalue(), "")
        return code, json.loads(stdout.getvalue())

    def test_exact_prefix_and_auth_without_generation(self):
        requests = []

        def handler(request):
            requests.append(request)
            payload = json.loads(request.content)
            return httpx.Response(
                200, json=dict(success=True, result=state(payload["operation_id"]))
            )

        code, result = self.invoke(
            ["submit", "--prefix", str(self.prefix), "--url", "http://engine"],
            handler,
            env={"TOOLGAP_API_KEY": "private-key"},
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, "/hicache/prefetch")
        self.assertEqual(requests[0].headers["Authorization"], "Bearer private-key")
        self.assertEqual(
            json.loads(requests[0].content),
            dict(
                action="submit",
                operation_id="owned",
                input_ids=list(range(64)),
                cache_salt="original",
                ttl_ms=1000,
            ),
        )
        self.assertEqual(result["state"], "RUNNING")
        self.assertNotIn("private-key", json.dumps(result))

    def test_timeout_retains_generated_id_and_does_not_retry(self):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            raise httpx.ReadTimeout("late acceptance is possible")

        code, result = self.invoke(
            ["submit", "--prefix", "-"],
            handler,
            stdin=io.StringIO(json.dumps(dict(input_ids=[1] * 64))),
        )
        self.assertEqual(code, 3)
        self.assertEqual(len(requests), 1)
        self.assertEqual(result["operation_id"], requests[0]["operation_id"])
        self.assertRegex(result["operation_id"], r"^[a-f0-9]{32}$")
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertIsNone(result["fallback_recommended"])
        self.assertNotIn("cleanup_pending", result)

    def test_rejection_preserves_reason_and_redacts_key(self):
        def handler(request):
            return httpx.Response(
                400, json=dict(success=False, message="One restore active; private-key")
            )

        code, result = self.invoke(
            ["submit", "--prefix", str(self.prefix)],
            handler,
            env={"TOOLGAP_API_KEY": "private-key"},
        )
        self.assertEqual(code, 4)
        self.assertTrue(result["fallback_recommended"])
        self.assertIn("One restore active", result["reason"])
        self.assertNotIn("private-key", json.dumps(result))

    def test_cancel_pending_does_not_poll_or_confirm_cleanup(self):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                json=dict(
                    success=True, result=state("owned", "CANCELLED", pending=True)
                ),
            )

        code, result = self.invoke(["cancel", "owned"], handler)
        self.assertEqual(code, 0)
        self.assertEqual(requests, [dict(action="cancel", operation_id="owned")])
        self.assertTrue(result["result"]["cleanup_pending"])
        self.assertIn("not physical cleanup", result["message"])

    def test_json_escaped_and_long_secrets_are_redacted_before_truncation(self):
        for secret in ['quote"back\\slash', "s" * 5000]:
            with self.subTest(length=len(secret)):
                code, result = self.invoke(
                    ["submit", "--prefix", str(self.prefix)],
                    lambda request: httpx.Response(
                        400, json=dict(success=False, message=secret)
                    ),
                    env={"TOOLGAP_API_KEY": secret},
                )
                self.assertEqual(code, 4)
                self.assertEqual(result["reason"], "[redacted]")

    def test_cancel_after_success_does_not_claim_eviction(self):
        def handler(request):
            return httpx.Response(
                200,
                json=dict(success=True, result=state("owned", "SUCCESS", restored=64)),
            )

        code, result = self.invoke(["cancel", "owned"], handler)
        self.assertEqual(code, 0)
        self.assertEqual(result["state"], "SUCCESS")
        self.assertIn("does not evict", result["message"])

    def test_unknown_status_rejection_does_not_confirm_absence(self):
        def handler(request):
            return httpx.Response(
                400, json=dict(success=False, message="Unknown operation")
            )

        code, result = self.invoke(["status", "forgotten"], handler)
        self.assertEqual(code, 4)
        self.assertIn("does not confirm cleanup", result["message"])
        self.assertNotIn("result", result)

    def test_foreign_and_malformed_replies_remain_unknown(self):
        invalid = [
            dict(success=True, result=state("someone-else", "SUCCESS")),
            dict(success=True, result=dict(state="SUCCESS", operation_id="owned")),
            dict(success=True, result=state("owned", "FAKE")),
            ["unexpected envelope"],
            dict(success=True, result=None),
            dict(success=True, result=state("owned", "SUCCESS", restored=65)),
        ]
        for response in invalid:
            with self.subTest(response=response):
                code, result = self.invoke(
                    ["status", "owned"],
                    lambda request: httpx.Response(200, json=response),
                )
                self.assertEqual(code, 3)
                self.assertEqual(result["state"], "UNKNOWN")
                self.assertEqual(result["operation_id"], "owned")

    def test_http_errors_and_bad_json_have_actionable_output(self):
        for status in [401, 403, 404, 500]:
            with self.subTest(status=status):
                code, result = self.invoke(
                    ["status", "owned"],
                    lambda request: httpx.Response(
                        status, text="No operation acknowledgement"
                    ),
                )
                self.assertEqual(code, 3)
                self.assertEqual(result["http_status"], status)
        code, result = self.invoke(
            ["status", "owned"],
            lambda request: httpx.Response(200, text="invalid JSON"),
        )
        self.assertEqual(code, 3)
        self.assertEqual(result["state"], "UNKNOWN")

    def test_bad_local_prefix_never_contacts_server(self):
        examples = [
            dict(input_ids=[]),
            dict(input_ids=[True]),
            dict(input_ids=[-1]),
            dict(input_ids=[1.0]),
            dict(input_ids=[1], ttl_ms=0),
            dict(input_ids=[1], operation_id=""),
            dict(input_ids=[1], cache_salt="x" * 257),
            dict(input_ids=[1], session="invented"),
            [1, 2],
            dict(input_ids=[1], ttl_ms=True),
        ]

        def forbidden(request):
            self.fail("Invalid local inputs must not send HTTP")

        for example in examples:
            with self.subTest(example=example):
                code, result = self.invoke(
                    ["submit", "--prefix", "-"],
                    forbidden,
                    stdin=io.StringIO(json.dumps(example)),
                )
                self.assertEqual(code, 2)
                self.assertEqual(result["state"], "INVALID_INPUT")
        for text in [
            '{"input_ids":[1],"input_ids":[2]}',
            " " * (cli.MAX_PREFIX_BYTES + 1),
        ]:
            code, _ = self.invoke(
                ["submit", "--prefix", "-"], forbidden, stdin=io.StringIO(text)
            )
            self.assertEqual(code, 2)

    def test_file_flag_conflicts_are_rejected(self):
        for options in [
            ["--operation-id", "other"],
            ["--cache-salt", "other"],
            ["--ttl-ms", "2000"],
        ]:
            code, result = self.invoke(
                ["submit", "--prefix", str(self.prefix)] + options,
                lambda request: self.fail("Conflict must not send"),
            )
            self.assertEqual(code, 2)
            self.assertIn("Conflicting", result["message"])

    def test_invalid_doctor_url_and_absent_file_have_no_traceback(self):
        code, result = self.invoke(
            ["doctor", "--url", "http://user:password@engine"],
            lambda request: self.fail("Bad URL must not send"),
        )
        self.assertEqual(code, 2)
        self.assertNotIn("password", result["message"])
        code, _ = self.invoke(
            ["submit", "--prefix", str(self.directory / "absent")],
            lambda request: self.fail("Missing file must not send"),
        )
        self.assertEqual(code, 2)

    def test_interrupt_retains_prepared_operation_id(self):
        with patch("toolgap.cli.execute", new=AsyncMock(side_effect=KeyboardInterrupt)):
            code, result = self.invoke(
                ["submit", "--prefix", str(self.prefix)],
                lambda request: self.fail("Transport mocked"),
            )
        self.assertEqual(code, 130)
        self.assertEqual(result["operation_id"], "owned")

    def test_nonfinite_timeout_is_usage_error(self):
        for value in ["nan", "inf", "-1", "0"]:
            with (
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                cli.main(["doctor", "--timeout", value], environ={})
            self.assertEqual(raised.exception.code, 2)


class DoctorTest(unittest.TestCase):
    def remote(self, *, backend="file", denied_backend=False, missing_route=False):
        info = dict(
            memory=dict(
                enable_hierarchical_cache=True, hicache_host_memory_mode="cache"
            ),
            parallel=dict(tp_size=1, pp_size=1, dp_size=1),
            api_key="never-echo-full-server-config",
        )
        replies = {
            "/health": {},
            "/openapi.json": dict(
                paths={} if missing_route else {"/hicache/prefetch": {"post": {}}}
            ),
            "/server_info": info,
            "/hicache/storage-backend": dict(hicache_storage_backend=backend),
            "/model_info": dict(architectures=["Qwen2ForCausalLM"]),
        }
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.method, "GET")
            if request.url.path == "/hicache/storage-backend" and denied_backend:
                return httpx.Response(403)
            return httpx.Response(200, json=replies[request.url.path])

        return handler, requests, replies

    def invoke(self, argv, handler):
        output = io.StringIO()
        code = cli.main(
            argv + ["--json"],
            stdout=output,
            environ={},
            transport=httpx.MockTransport(handler),
        )
        return code, json.loads(output.getvalue())

    def test_remote_checks_only_get_no_capability_promise(self):
        handler, requests, _ = self.remote()
        code, result = self.invoke(["doctor", "--url", "http://engine"], handler)
        self.assertEqual(code, 0)
        self.assertEqual(len(requests), 4)
        self.assertEqual(
            {r.url.path for r in requests},
            {
                "/openapi.json",
                "/server_info",
                "/hicache/storage-backend",
                "/model_info",
            },
        )
        self.assertFalse(result["restore_exercised"])
        self.assertFalse(result["cache_state_verified"])
        self.assertNotIn("never-echo-full-server-config", json.dumps(result))

    def test_scope_and_route_failures(self):
        for kwargs in [dict(backend="mooncake"), dict(missing_route=True)]:
            handler, _, _ = self.remote(**kwargs)
            code, result = self.invoke(["doctor", "--url", "http://engine"], handler)
            self.assertEqual(code, 1)
            self.assertEqual(result["state"], "FAIL")
        handler, _, replies = self.remote()
        replies["/server_info"]["parallel"]["tp_size"] = 2
        code, _ = self.invoke(["doctor", "--url", "http://engine"], handler)
        self.assertEqual(code, 1)

    def test_unreadable_live_backend_is_unknown(self):
        handler, _, _ = self.remote(denied_backend=True)
        code, result = self.invoke(["doctor", "--url", "http://engine"], handler)
        self.assertEqual(code, 3)
        self.assertEqual(result["state"], "UNKNOWN")

    def test_no_targets_does_not_report_ready(self):
        code, result = self.invoke(
            ["doctor"], lambda request: self.fail("No URL means no HTTP")
        )
        self.assertEqual(code, 3)
        self.assertEqual(result["state"], "UNKNOWN")

    def test_non_object_diagnostics_are_not_silently_passed(self):
        handler, _, replies = self.remote()
        for path in [
            "/server_info",
            "/openapi.json",
            "/hicache/storage-backend",
            "/model_info",
        ]:
            original = replies[path]
            replies[path] = None
            code, result = self.invoke(["doctor", "--url", "http://engine"], handler)
            self.assertEqual(code, 3)
            self.assertEqual(result["state"], "UNKNOWN")
            replies[path] = original
        replies["/openapi.json"] = {"unexpected": "schema"}
        code, result = self.invoke(["doctor", "--url", "http://engine"], handler)
        self.assertEqual(code, 3)
        self.assertEqual(result["state"], "UNKNOWN")

    def test_file_checks_report_missing_and_mismatched_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "good").write_text("source")
            pinned = dict(
                release_source_commit="pinned",
                source_files={
                    "good": hashlib.sha256(b"source").hexdigest(),
                    "missing": "bad",
                },
                model_tokenizer_files={},
            )
            with patch("toolgap.diagnostics.manifest", return_value=pinned):
                code, result = self.invoke(
                    ["doctor", "--sglang", str(root)],
                    lambda request: self.fail("Offline check must not send"),
                )
            self.assertEqual(code, 1)
            self.assertEqual([c["state"] for c in result["checks"]], ["PASS", "FAIL"])
            pinned["source_files"] = {"good": hashlib.sha256(b"different").hexdigest()}
            with patch("toolgap.diagnostics.manifest", return_value=pinned):
                code, _ = self.invoke(
                    ["doctor", "--sglang", str(root)],
                    lambda request: self.fail("Offline"),
                )
            self.assertEqual(code, 1)

    def test_packaged_manifest_matches_existing_demo_guard(self):
        example = (
            Path(__file__).resolve().parents[1]
            / "examples/tool_loop/compatibility-files.json"
        )
        self.assertEqual(manifest(), json.loads(example.read_text()))

    def test_gpu_missing_binary_does_not_import_model_or_run_cuda(self):
        with (
            patch("toolgap.diagnostics.shutil.which", return_value=None),
            patch("toolgap.diagnostics.subprocess.run") as run,
        ):
            code, result = self.invoke(
                ["doctor", "--gpu"],
                lambda request: self.fail("Local GPU check has no HTTP"),
            )
        self.assertEqual(code, 1)
        run.assert_not_called()
        self.assertFalse(result["restore_exercised"])


if __name__ == "__main__":
    unittest.main()
