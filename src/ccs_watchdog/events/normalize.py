from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


FUTURE_HINTS = (
    "接下来", "下一步", "然后开始", "然后修改", "然后运行", "现在开始", "现在为",
    "我会继续", "让我查看", "让我看", "我先检查", "我准备", "开始开发", "正在为",
    "先看", "先读", "写测试", "继续完成", "继续按",
    "let me", "i'll", "i will now", "proceeding to", "start implementing",
    "first i'll", "now i'll", "then ", "next ",
)

WAITING_HINTS = (
    "askuserquestion", "permission", "approval", "plan mode",
    "needs your permission", "waiting for", "elicitation",
)

SIDE_EFFECT_TOOLS = {
    "Edit", "Write", "NotebookEdit", "Bash", "SendMessage",
    "mcp__github__create_issue", "mcp__github__create_pull_request",
    "mcp__github__merge_pull_request", "mcp__github__push_files",
}

SAFE_TOOLS = {"Read", "Grep", "Glob", "LS", "WebSearch", "WebFetch", "Skill", "ToolSearch"}


@dataclass
class NormalizedEvent:
    kind: str
    raw_type: str
    timestamp: str | None = None
    uuid: str | None = None
    role: str | None = None
    model: str | None = None
    stop_reason: str | None = None
    text: str = ""
    text_len: int = 0
    tools: list[str] = field(default_factory=list)
    tool_ids: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    subtype: str | None = None
    empty_assistant: bool = False
    thinking_only: bool = False
    future_action: bool = False
    message_id: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def _blocks(content) -> tuple[list[str], str, list[str], list[str]]:
    types: list[str] = []
    texts: list[str] = []
    tools: list[str] = []
    ids: list[str] = []
    if isinstance(content, str):
        return ["text"], content, [], []
    if not isinstance(content, list):
        return [], "", [], []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type") or "unknown"
        types.append(btype)
        if btype == "text":
            texts.append(block.get("text") or "")
        elif btype == "tool_use":
            tools.append(block.get("name") or "unknown")
            if block.get("id"):
                ids.append(str(block["id"]))
        elif btype == "tool_result":
            tools.append("RESULT")
    return types, "".join(texts), tools, ids


def looks_like_future_action(text: str) -> bool:
    lowered = (text or "").casefold()
    return any(hint in lowered for hint in FUTURE_HINTS)


def normalize_record(record: dict[str, Any]) -> NormalizedEvent:
    raw_type = record.get("type") or "unknown"
    msg = record.get("message") if isinstance(record.get("message"), dict) else {}
    role = msg.get("role")
    content = msg.get("content")
    blocks, text, tools, ids = _blocks(content)
    stop = msg.get("stop_reason")
    model = msg.get("model")
    empty = False
    thinking_only = False
    kind = "UNKNOWN_EVENT"

    if raw_type == "assistant" or role == "assistant":
        if content in ([], None) and not tools:
            empty = True
            kind = "ASSISTANT_EMPTY"
        elif not tools and not (text or "").strip() and blocks == ["thinking"]:
            thinking_only = True
            kind = "ASSISTANT_EMPTY"
            empty = True
        elif not tools and not (text or "").strip() and "text" in blocks:
            empty = True
            kind = "ASSISTANT_EMPTY"
        elif tools:
            kind = "TOOL_USE_STARTED" if stop in (None, "tool_use") else "ASSISTANT_TEXT"
            if text.strip():
                # text + tool_use is still a tool turn
                kind = "TOOL_USE_STARTED"
        else:
            kind = "ASSISTANT_TEXT"
    elif raw_type == "user" or role == "user":
        if "RESULT" in tools or (isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)):
            kind = "TOOL_RESULT"
        else:
            origin = record.get("origin") or {}
            if origin.get("kind") == "human" or record.get("promptSource") in {"typed", "paste"}:
                kind = "USER_PROMPT"
            else:
                kind = "USER_EVENT"
    elif raw_type == "system":
        subtype = record.get("subtype")
        if subtype == "turn_duration":
            kind = "TURN_IDLE"
        elif "error" in str(subtype or "").lower() or "stopfailure" in str(subtype or "").lower():
            kind = "STOP_FAILURE"
        else:
            kind = "SYSTEM"
    elif raw_type in {"last-prompt", "mode", "permission-mode", "atis-latch", "ai-title", "file-history-snapshot", "file-history-delta", "attachment"}:
        kind = "META"
    elif record.get("_parse_error"):
        kind = "UNKNOWN_EVENT"

    if isinstance(text, str) and any(h in text.casefold() for h in ("api error", "please run /login")):
        if kind in {"ASSISTANT_TEXT", "ASSISTANT_EMPTY"}:
            kind = "API_ERROR"

    return NormalizedEvent(
        kind=kind,
        raw_type=raw_type,
        timestamp=record.get("timestamp"),
        uuid=record.get("uuid"),
        role=role,
        model=model,
        stop_reason=stop,
        text=text,
        text_len=len(text or ""),
        tools=tools,
        tool_ids=ids,
        blocks=blocks,
        usage=msg.get("usage") or {},
        subtype=record.get("subtype"),
        empty_assistant=empty,
        thinking_only=thinking_only,
        future_action=looks_like_future_action(text),
        message_id=msg.get("id"),
        extras={"cwd": record.get("cwd"), "version": record.get("version")},
    )
