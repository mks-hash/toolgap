# Recorded actual model failures

Selected public data from three failed live pilots (2026-10-05). Raw cloud logs
remain private; `raw_sha256` binds each original retained JSONL file.

- `model-outputs.json`: 27 actual response token sequences/texts and current
  parser expectations, from 13 packet-Qwen7, 11 older Qwen7 and 3 Mistral
  generations. Mistral text was decoded from retained actual output IDs with
  its pinned official tokenizer; the original log did not store raw text.
- `qwen7-continuations.json`: the packet-bound pilot's original schema, first
  representative's actual initial messages/IDs, tool results, generated IDs
  and submitted-input hashes. It preserves all ten submitted continuations,
  two unsubmitted overflows (8236/8058 versus 7936 allowed tokens), and invalid
  final citation evidence. Source context is public pinned ToolGap code.

Extracted at historical ToolGap `b6b42e4d529963aa6996452fc41d4627edcec6dd` for the
packet-bound recording. Complete selected outputs/IDs/results are unchanged;
cloud identifiers, salts, request IDs, timings and private process metadata
are excluded. No new model-generated output, test repair or claimed live pass.
Original useful task outcomes remain 0/3 in every pilot. These records do not
attest behavior on later counterfactual bounded tool responses.

Run parser tests with `tests/test_recorded_replay.py`; run native CPU replay with
`python -m research.agent_resume.replay --qwen-tokenizer "$TOKENIZER_DIR"
--output work/study/replay.json`. The native replay verifies the stored tokenizer
file hashes before use. Older Qwen7/Mistral full continuation replay is NOT_RUN.
The pinned source snippets retain their original Apache-2.0 license.
