"""Small semantic records; no tokenizer, serving engine or tool effects."""

from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .adapters import ToolCall


@dataclass(frozen=True)
class ToolCalls:
    calls: tuple["ToolCall", ...]


@dataclass(frozen=True)
class FinalAnswer:
    text: str


@dataclass(frozen=True)
class InvalidOutput:
    reason: str


@dataclass(frozen=True)
class UnsupportedOutput:
    reason: str


ResponseOutcome = ToolCalls | FinalAnswer | InvalidOutput | UnsupportedOutput


@dataclass(frozen=True)
class ExecutedTurn:
    profile_id: str
    input_ids: tuple[int, ...]
    generated_ids: tuple[int, ...]
    raw_text: str
    finish_reason: str | None
    outcome: ResponseOutcome


class ModelAdapter(Protocol):
    family: str
    profile_id: str

    def normalize_messages(self, messages): ...

    def prompt(self, tokenizer, messages, tools): ...

    def classify(self, raw, allowed_tools, finish_reason) -> ResponseOutcome: ...

    def prepare_continuation(
        self, tokenizer, messages, tools, prompt_ids, decision_ids, call
    ): ...
