# 使用指南

ClaudeCode Watchdog V0.1 的完整使用步骤。命令、输出、阈值均来自本机真实运行结果（示例里的用户名、provider 名、端口和无关项目名已换成占位符）。

TL;DR：只想快速上手，看 [安装](#安装) + [第 3 步 replay](#3-离线复盘一个会话) 两节就够了。

## 目录

- [安装](#安装)
- [1. 体检：doctor](#1-体检doctor)
- [2. 定位会话：status](#2-定位会话status)
- [3. 离线复盘一个会话](#3-离线复盘一个会话)
- [4. 实时守着会话](#4-实时守着会话)
- [5. 读日志产物](#5-读日志产物)
- [6. auto-resume 能做什么](#6-auto-resume-能做什么)
- [评分与分类含义](#评分与分类含义)
- [配置文件](#配置文件)
- [踩坑提示](#踩坑提示)
- [故障排查](#故障排查)

## 安装

需要 Windows + Python 3.11+。

```powershell
cd E:\github仓库\ClaudeCode_Watchdog
python -m pip install -e ".[dev]"
ccs-watchdog doctor
```

不想装包，全部命令都能免安装跑（PowerShell）：

```powershell
cd E:\github仓库\ClaudeCode_Watchdog
$env:PYTHONPATH = "src"
python -m ccs_watchdog.cli.main doctor
```

下文统一用 `ccs-watchdog` 书写；免安装方式把 `ccs-watchdog` 换成 `python -m ccs_watchdog.cli.main` 即可。

## 1. 体检：doctor

确认能否找到 Claude Code 的 session 目录、ccSwitch 路由是否在跑。第一步永远先跑它。

```powershell
ccs-watchdog doctor
```

真实输出：

```json
{
  "claude_path": "C:\\Users\\<user>\\AppData\\Roaming\\npm\\claude.CMD",
  "claude_home": "C:\\Users\\<user>\\.claude",
  "projects_dir_exists": true,
  "session_count": 88,
  "newest_session": "4f52fcf7-7a1b-4502-90ff-9d31c343ec7d",
  "python_ok": true,
  "routing_enabled": true,
  "listen": "127.0.0.1:<port>",
  "provider": "<provider>",
  "ccswitch_version": "3.14.0",
  "base_url_host": "127.0.0.1",
  "dry_run": true
}
```

怎么读：

| 字段 | 含义 | 异常时 |
|---|---|---|
| `claude_path` | 找到的 `claude` 可执行文件 | `null` 说明 PATH 里没有 Claude Code |
| `projects_dir_exists` | `~/.claude/projects` 是否存在 | `false` 则后面所有命令都拿不到会话 |
| `session_count` | 可发现的会话总数 | `0` 说明还没跑过 Claude Code，或目录不对 |
| `routing_enabled` / `listen` / `provider` | ccSwitch 本地路由状态 | 没装 ccSwitch 时为 `false` / `null`，属正常 |
| `dry_run` | 当前是否只记录不动作 | 默认 `true`，V0.1 应该一直是 `true` |

## 2. 定位会话：status

```powershell
ccs-watchdog status
```

```json
{
  "watchdog_version": "0.1.0",
  "dry_run": true,
  "newest_session": "4f52fcf7-7a1b-4502-90ff-9d31c343ec7d",
  "session_path": "C:\\Users\\<user>\\.claude\\projects\\E--github---ClaudeCode-Watchdog\\4f52fcf7-7a1b-4502-90ff-9d31c343ec7d.jsonl",
  "routing_enabled": true,
  "listen": "127.0.0.1:<port>",
  "provider": "<provider>",
  "ccswitch_version": "3.14.0"
}
```

把 `session_path` 记下来，第 3、4 步要用。

**注意**：会话是按**当前工作目录**推断的 —— 在 `E:\github仓库\ClaudeCode_Watchdog` 下执行，只会列出这个项目的会话。守别的目录里的会话，需要显式传 `--session`（见第 4 步）。

## 3. 离线复盘一个会话

对一整份 transcript 从头打一遍分。**不碰正在运行的会话，最安全，也最实用** —— 出问题时先用它搞清楚"到底算不算中断"。

```powershell
# 用仓库自带的脱敏样本（推荐第一次跑这个）
ccs-watchdog replay tests/fixtures/unfinished-text-then-done.jsonl

# 复盘你自己的历史会话
ccs-watchdog replay "C:\Users\<user>\.claude\projects\<project>\<session-id>.jsonl"
```

真实输出：

```text
2026-09-09T12:26:52.294Z  SUSPECTED_SILENT_INTERRUPTION    score= 60 stop=tool_use empty=0 model=k3
  evidence: assistant promised next action but emitted no tool_use; stop_reason absent (proxy/conversion likely)
  text: 明白了。多源轮询方案，通过配置项控制。让我看一下前端状态管理和 API 结构，然后开始开发。
  action: dry_run_prompt

2026-09-09T12:26:53.695Z  SUSPECTED_SILENT_INTERRUPTION    score= 40 stop=tool_use empty=0 model=k3
  evidence: idle after future-action text without following tool_use in this idle; recent tool_result then unfinished idle
  text: 明白了。多源轮询方案，通过配置项控制。让我看一下前端状态管理和 API 结构，然后开始开发。
  action: record_only

2 interesting events, 1 score>=60
```

每行字段：

- `score` — 中断嫌疑分，见[评分含义](#评分与分类含义)
- `stop=` — transcript 里的 `stop_reason`；`absent`（代理/转换层丢字段）本身就是弱信号
- `empty=` — 连续空 assistant 响应计数
- `evidence:` — 判定依据，人读这个就够
- `action:` — 建议动作，`record_only`（只记账）/ `dry_run_prompt`（可给提示词）/ `manual_review`（必须人看）

`--verbose` 参数存在但目前不改变输出（未接线）。

## 4. 实时守着会话

V0.1 没有 daemon/service，**需要另开一个终端**，Claude Code 那个终端照常干活。

```powershell
# 先 cd 到被守护的项目目录，才会自动挑对会话
cd <你的项目目录>

# 只关注启动之后新增的内容（默认行为，推荐日常用）
ccs-watchdog watch

# 显式指定会话：session id 前缀 / 文件名 / 完整路径都接受 —— 跨项目时这是唯一办法
ccs-watchdog watch --session 4f52fcf7
ccs-watchdog watch --session "C:\Users\<user>\.claude\projects\<project>\<id>.jsonl"

# 连已有历史一起扫，并且只扫一次就退出（验证配置很好用）
ccs-watchdog watch --from-start --once
```

命中时的输出示例（已脱敏）：

```text
watching C:\Users\<user>\.claude\projects\E--github---ClaudeCode-Watchdog\4f52fcf7-....jsonl dry_run=True
SUSPECTED_SILENT_INTERRUPTION score=60 assistant promised next action but emitted no tool_use; stop_reason absent (proxy/conversion likely)
```

轮询间隔固定 0.5 秒；同一 `(分类, uuid, 分数)` 指纹只打印一次，不会刷屏。

**停止**：`Ctrl+C`。`ccs-watchdog stop` 是占位命令，只打印 `no daemon pid file; stop the watch process`，没有 pid 文件管理。

## 5. 读日志产物

默认落在**当前工作目录**的 `.ccs-watchdog/`（已在 `.gitignore` 里）：

| 文件 | 用途 |
|---|---|
| `events.jsonl` | 机器读。字段：`timestamp` / `watchdog_version` / `classification` / `interruption_score` / `evidence` / `stop_reason` / `empty_assistant_count` / `model` / `last_assistant_text_summary` / `resume_attempt` / `recommended_action` / `session_id` |
| `watchdog.log` | 人读，一行一条 |

```powershell
Get-Content .\.ccs-watchdog\watchdog.log -Tail 20
```

换位置：`ccs-watchdog watch --log-dir D:\logs\ccwd`。

日志里的文本摘要会先过 `redact()`，API Key / Token 之类不落盘。

## 6. auto-resume 能做什么

```powershell
ccs-watchdog watch --auto-resume
```

**它不会自动往终端打字。** V0.1 里 `--auto-resume` 只把"该发给 Claude 的恢复提示词"打印出来，仍需你复制粘贴或手动续。它同时把 `dry_run` 置为 `false`。

触发条件（`cli/main.py`）：`score >= threshold`（默认 80）**且**熔断器未耗尽（`max_auto_resumes`，默认 3）；副作用未知时直接跳过：

```text
manual_review: not auto-resuming
```

否则打印建议提示词（`resume/controller.py`）：

> 检测到上一轮响应可能因上游流式连接/空响应异常而提前结束。请先检查当前会话已有进度和最近成功的 tool_result，从最后一个已确认完成的步骤之后继续。不要重复已经成功执行的 Edit、Write、Bash 或其他有副作用操作；如果上一操作执行状态不确定，先验证当前状态，再决定是否继续。

连续空响应场景会额外追加一句"不要把空响应解释为用户新指令"。

**注意**：`breaker.record(False)` 在打印提示词后无条件调用，所以熔断器是"每次建议都算一次失败"，攒够 3 次就不再提示 —— 不是"恢复失败 3 次才熔断"。这是 V0.1 的实现现状。

日常建议：**保持默认 dry-run**，用 `replay` 做事后分析，`watch` 做实时提醒，人工决定要不要续。

## 评分与分类含义

分数（`scoring/score.py`）：

| 分数 | 含义 |
|---|---|
| `>= 80` | 高置信中断，`--auto-resume` 的门槛（可用 `threshold` 配置） |
| `60–79` | 可疑，`replay` 结尾统计里的 "score>=60"（写死在 `cli/main.py`） |
| `>= 30` | `watch` 会打印并记日志的门槛（写死在 `cli/main.py`） |
| `< 30` | 忽略 |

分类（11 种）：`NORMAL` / `NORMAL_END` / `TOOL_RUNNING` / `WAITING_USER` / `API_INTERRUPTED` / `EMPTY_RESPONSE` / `REPEATED_EMPTY_RESPONSE` / `SUSPECTED_SILENT_INTERRUPTION` / `SIDE_EFFECT_UNKNOWN` / `ROUTE_SWITCH_SUSPECTED` / `UNKNOWN`。

`replay` 只展示其中"有意思"的（`INTERESTING` 集合）或 `score >= 30` 的，所以 `NORMAL` 之类的不会刷屏。

`ROUTE_SWITCH_SUSPECTED` 是**弱信号**：只表示异常与 ccSwitch 路由/模型切换在时间上邻近，不等于因果。

## 配置文件

```powershell
ccs-watchdog --config my.json doctor
```

`--config` 是**全局参数，必须放在子命令之前**（`ccs-watchdog doctor --config my.json` 会报 `unrecognized arguments`）。

JSON 格式，可写字段（`config/defaults.py`）。**V0.1 有若干声明了但未接线的字段**，下表如实标注：

| 字段 | 默认 | 作用 |
|---|---|---|
| `dry_run` | `true` | 只记录不动作 |
| `auto_resume` | `false` | 允许打印恢复提示词 |
| `threshold` | `80` | auto-resume 触发的分数门槛 —— **唯一真正生效的阈值** |
| `max_auto_resumes` | `3` | 熔断器上限 |
| `claude_home` | `~/.claude` | 会话发现根目录（路径类，见踩坑提示） |
| `ccswitch_home` | `~/.cc-switch` | ccSwitch 状态目录（路径类） |
| `suspicious_threshold` | `60` | ⚠️ 未接线，代码里没有引用 |
| `cooldown_seconds` | `10` | ⚠️ 未接线 |
| `idle_grace_seconds` | `2.0` | ⚠️ 未接线 |
| `empty_consecutive_threshold` | `2` | ⚠️ 未接线，`scoring/score.py` 里写死 `>= 2` |
| `redact_secrets` | `true` | ⚠️ 未接线，日志摘要无条件过 redact |
| `log_dir` | `null` | ⚠️ 未接线，只有 `--log-dir` 命令行参数生效 |


## 踩坑提示

| 现象 | 原因 / 正确做法 |
|---|---|
| `unrecognized arguments: --config ...` | `--config` 必须放在子命令**前面** |
| 配置里写 `claude_home` 后路径行为异常 | JSON 值以 `str` 覆盖 dataclass 的 `Path` 字段，后续 `/` 拼接会 `TypeError`。数字字段安全，**路径类字段别写在配置文件里** |
| 配置里有 `projects_dir` 或拼错的键 → `AttributeError` 崩 | `projects_dir` 是 property 无 setter；未知键 `setattr` 抛错。只写上面表格里的普通字段 |
| `AMBIGUOUS_SESSION; pass --session with one of:` | 30 秒内有多个会话被写过，按打印出的候选列表选一个加 `--session` |
| 守着守着发现不是目标会话 | 会话按 cwd 推断。跨项目必须 `--session <完整路径>` |
| 改了 `threshold` 但 replay 输出没变 | `threshold` 只管 auto-resume；日志/打印门槛是写死的 `score >= 30` |
| `No module named ccs_watchdog` | 没 `pip install -e`，也没设 `PYTHONPATH=src` |

## 故障排查

- **一个会话都找不到** → `doctor` 看 `projects_dir_exists`。Claude Code 的 transcript 在 `~/.claude/projects/<cwd 编码>/<session-id>.jsonl`，目录名是把 cwd 里的 `:` `\` `/` 换成 `-`（`discovery/sessions.py:encode_cwd`）。
- **`routing_enabled: false` 但装了 ccSwitch** → 检查 `~/.cc-switch` 是否存在、版本是否被 `provider/ccswitch.py` 支持。
- **误判为中断** → 先 `replay` 该会话看 `evidence`。`WAITING_USER`（模型在等你回答）和 `TOOL_RUNNING` 不该算中断；如果算错了，属于 `scoring/score.py` 的判定问题，欢迎带 fixture 报 issue。
- **测试** → `python -m pytest -q`（当前 14 passed）。

## 安全边界

V0.1 明确不做的事：

- 不注入键盘输入、不 SendKeys、不自动续跑
- 不记录 API Key / Token / Cookie（日志摘要过 redact）
- 不写 `~/.claude/settings.json`，不装全局 Hook
- 不改 ccSwitch 配置
- 不自启动、不做 daemon
