"""Schemas for the chat welcome-prompts endpoint (Tutor refactor 2026-04-26)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PromptKind = Literal["tutor", "code", "quiz", "career", "auto"]
ChatMode = Literal["auto", "tutor", "code", "career", "quiz"]


class WelcomePromptItem(BaseModel):
    text: str
    icon: str
    kind: PromptKind
    rationale: str = ""


class WelcomePromptsResponse(BaseModel):
    mode: ChatMode
    prompts: list[WelcomePromptItem] = Field(default_factory=list)
