"""Cancellation must reap the actual search subprocess, not leave tool work running."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from run import tool
from search_tool import create_corpus


class TestToolProcess(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_reaps_real_tool_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "documents.jsonl"
            create_corpus(corpus, 10000)
            started = asyncio.Event()
            children = []
            original = asyncio.create_subprocess_exec

            async def launch(*args, **kwargs):
                child = await original(*args, **kwargs)
                children.append(child)
                started.set()
                return child

            with mock.patch("asyncio.create_subprocess_exec", side_effect=launch):
                task = asyncio.create_task(tool(corpus, "KV prefetch tool latency"))
                await started.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertIsNotNone(children[0].returncode)
