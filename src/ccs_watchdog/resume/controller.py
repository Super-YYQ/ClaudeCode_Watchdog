from __future__ import annotations

from dataclasses import dataclass


RESUME_PROMPT = (
    "检测到上一轮响应可能因上游流式连接/空响应异常而提前结束。"
    "请先检查当前会话已有进度和最近成功的 tool_result，从最后一个已确认完成的步骤之后继续。"
    "不要重复已经成功执行的 Edit、Write、Bash 或其他有副作用操作；如果上一操作执行状态不确定，先验证当前状态，再决定是否继续。"
)

EMPTY_RESUME_PROMPT = RESUME_PROMPT + "上一轮出现连续空 assistant response，请不要把空响应解释为用户新指令；继续原任务。"


@dataclass
class CircuitBreaker:
    failures: int = 0
    max_failures: int = 3

    def allow(self) -> bool:
        return self.failures < self.max_failures

    def record(self, success: bool) -> None:
        self.failures = 0 if success else self.failures + 1


def resume_prompt(empty: bool = False) -> str:
    return EMPTY_RESUME_PROMPT if empty else RESUME_PROMPT
