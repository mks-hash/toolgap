#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
export PYTHONPATH="$root/src:$root/examples/tool_loop:${PYTHONPATH:-}"
python -m unittest discover -s "$root/tests" -p 'test_client_policy.py' -v
python -m unittest discover -s "$root/tests" -p 'test_tokens_tool.py' -v
python -m unittest discover -s "$root/tests" -p 'test_tool_process.py' -v
python -m unittest discover -s "$root/tests" -p 'test_admission.py' -v
python -m unittest discover -s "$root/tests" -p 'test_admission_hints.py' -v
python -m unittest discover -s "$root/tests" -p 'test_reconciliation.py' -v
python -m unittest discover -s "$root/tests" -p 'test_multi_session_workflow.py' -v
python -m unittest discover -s "$root/tests" -p 'test_cli.py' -v
