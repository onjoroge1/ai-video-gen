"""Composable prompts with explicit precedence instead of string-concatenation ambiguity."""
from dataclasses import dataclass
from enum import IntEnum


class PromptPriority(IntEnum):
    SAFETY = 10
    OUTPUT_CONTRACT = 20
    FACTS = 30
    FORMAT = 40
    CREATIVE = 50


@dataclass(frozen=True)
class PromptSection:
    name: str
    content: str
    priority: PromptPriority


class PromptBuilder:
    def __init__(self, purpose: str):
        self.purpose = purpose.strip()
        self._sections: list[PromptSection] = []

    def add(self, name: str, content: str, priority: PromptPriority) -> "PromptBuilder":
        content = content.strip()
        if content:
            self._sections.append(PromptSection(name, content, priority))
        return self

    def render(self) -> str:
        ordered = sorted(enumerate(self._sections), key=lambda item: (item[1].priority, item[0]))
        header = (
            f"PURPOSE: {self.purpose}\n"
            "INSTRUCTION PRECEDENCE: lower-numbered sections override later sections on conflict."
        )
        blocks = [header]
        for _, section in ordered:
            blocks.append(f"[{int(section.priority):02d} {section.name.upper()}]\n{section.content}")
        return "\n\n".join(blocks) + "\n"
