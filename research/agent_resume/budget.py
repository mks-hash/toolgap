"""Bound actual evidence rows at the tool boundary; never rewrite saved KV IDs."""

import copy
import hashlib
import json

MAX_TOOL_SUFFIX_TOKENS = 512


class InsufficientEvidence(ValueError):
    """The remaining context cannot carry useful evidence safely."""


class ToolResultBudget:
    def __init__(self, plan, tokenizer, max_input_tokens):
        self.plan, self.tokenizer = plan, tokenizer
        self.max_input_tokens = max_input_tokens

    def measure(self, result):
        ids, _ = self.plan.append(self.tokenizer, result)
        return len(ids), len(ids) - len(self.plan.saved_ids)

    def fits(self, result):
        total, suffix = self.measure(result)
        return total <= self.max_input_tokens and suffix <= MAX_TOOL_SUFFIX_TOKENS

    def preflight(self):
        # A fitting empty dict cannot establish that a classified response fits.
        if not self.fits(dict(result_status="INSUFFICIENT_EVIDENCE", next_cursor=None)):
            raise InsufficientEvidence("No room for a classified tool response")

    def deliver(self, tools, call, result):
        raw_hash = hashlib.sha256(
            json.dumps(result, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        keys = [
            k for k in ("matches", "files", "lines") if isinstance(result.get(k), list)
        ]
        if len(keys) > 1:
            raise ValueError("Ambiguous tool evidence rows")
        key = keys[0] if keys else None
        rows = result[key] if key else []
        for count in range(len(rows), -1, -1):
            candidate = copy.deepcopy(result)
            if key:
                candidate[key] = rows[:count]
            cursor = tools.resume_arguments(call, result, count) if key else None
            status = "PARTIAL" if cursor or count < len(rows) else "COMPLETE"
            if rows and count == 0:
                status = "INSUFFICIENT_EVIDENCE"
                # Keep the response small and explicit; no successful result claim.
                candidate = {key: []}
            if "next_offset" in candidate:
                candidate["next_offset"] = (
                    cursor["arguments"].get("offset") if cursor else None
                )
            if "truncated" in candidate:
                candidate["truncated"] = status != "COMPLETE"
            candidate.update(result_status=status, next_cursor=cursor)
            if not self.fits(candidate):
                continue
            total, suffix = self.measure(candidate)
            return candidate, dict(
                raw_result_sha256=raw_hash,
                delivered_result_sha256=hashlib.sha256(
                    json.dumps(candidate, sort_keys=True, allow_nan=False).encode()
                ).hexdigest(),
                raw_rows=len(rows),
                delivered_rows=count,
                result_status=status,
                continuation_tokens=total,
                suffix_tokens=suffix,
                max_input_tokens=self.max_input_tokens,
                max_suffix_tokens=MAX_TOOL_SUFFIX_TOKENS,
            )
        raise InsufficientEvidence(
            "Tool metadata cannot fit the remaining evidence budget"
        )
