"""Private same-host scheduler mailbox; never a remotely exposed API."""

import asyncio
import json
import time
import uuid
from pathlib import Path


def clock_domain():
    # Linux monotonic time is comparable across processes on the same boot only.
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


class FileObserver:
    def __init__(self, directory, *, include_storage=False, timeout=3, domain=None):
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise ValueError("Create a private shared observation directory first")
        self.include_storage = include_storage
        self.timeout = timeout
        self.domain = domain or clock_domain()

    async def snapshot(self, ids, salt):
        nonce = uuid.uuid4().hex
        request = self.directory / (nonce + ".request.json")
        response = self.directory / (nonce + ".response.json")
        temporary = self.directory / (nonce + ".request.tmp")
        started = time.monotonic_ns()
        try:
            temporary.write_text(
                json.dumps(
                    dict(
                        input_ids=ids,
                        cache_salt=salt,
                        include_storage=self.include_storage,
                        clock_domain=self.domain,
                    )
                )
            )
            temporary.replace(request)

            async def wait():
                while not response.exists():
                    await asyncio.sleep(
                        0.005
                    )  # measurement/control polling, not tool work
                result = json.loads(response.read_text())
                if result.get("clock_domain") != self.domain:
                    raise ValueError(
                        "Observer and client do not share a Linux boot clock"
                    )
                if "error" in result:
                    raise ValueError("Scheduler observation failed: " + result["error"])
                return result

            result = await asyncio.wait_for(wait(), self.timeout)
            result.update(
                client_observation_started_ns=started,
                client_observation_completed_ns=time.monotonic_ns(),
            )
            return result
        finally:
            for path in (temporary, request, response):
                path.unlink(missing_ok=True)
            # A cancelled request already being read may produce a late response.
            # Its unique nonce cannot be reused; clean orphan responses after the block.
