# 使用指南

ClaudeCode Watchdog V0.1 的完整使用步骤。命令、输出、阈值均来自本机真实运行结果（示例里的用户名、provider 名、端口和无关项目名已换成占位符）。

TL;DR：只想快速上手，看 [安装](#安装) + [最短路径](#最短路径) 两节就够了。

## 目录

- [安装](#安装)
- [最短路径](#最短路径)
- [1. 体检：doctor](#1-体检doctor)
- [2. 一句话看有没有出事：last](#2-一句话看有没有出事last)
- [3. 定位会话：status](#3-定位会话status)
- [4. 离线复盘一个会话](#4-离线复盘一个会话)
- [5. 实时守着会话](#5-实时守着会话)
- [6. 读日志产物](#6-读日志产物)
- [7. auto-resume 能做什么](#7-auto-resume-能做什么)
- [评分与分类含义](#评分与分类含义)
- [配置文件](#配置文件)
- [踩坑提示](#踩坑提示)
- [故障排查](#故障排查)

## 安装

需要 Windows + Python 3.11+。

```powershell
cd E:\github仓库\ClaudeCode_Watchdog
python -m pip install -e ".[dev]"
ccw doctor
```

安装包后会同时得到两个命令：`ccw`（短，推荐）和 `ccs-watchdog`（长，历史名字），二者指向同一个入口，完全等价。

不想装包，全部命令都能免安装跑（PowerShell）：

```powershell
cd E:\github仓库\ClaudeCode_Watchdog
$env:PYTHONPATH = "src"
python -m ccs_watchdog.cli.main doctor
```

下文统一用 `ccw` 书写；免安装方式把 `ccw` 换成 `python -m ccs_watchdog.cli.main` 即可。

## 最短路径

日常只需要三条：

```powershell
ccw doctor   # 装完先跑一次，确认能找到 ~/.claude/projects
ccw last     # 怀疑某个会话出事了？直接看结论（只打印 score>=60）
ccw          # 干活时开着守护（另开一个终端，Ctrl+C 停止）
```

`ccw` 不带子命令时等价于 `ccw watch`；`ccw --once` 就是 `ccw watch --once`。`--config` 放在子命令前后都可以。


## 1. 体检：doctor

确认能否找到 Claude Code 的 session 目录、ccSwitch 路由是否在跑。第一步永远先跑它。

```powershell
ccw doctor
```

输出示例（在 `E:\github仓库\ClaudeCode_Watchdog` 下执行，用户名 / provider / 端口已脱敏）：

```json
{
  "claude_path": "C:\\Users\\<user>\\AppData\\Roaming\\npm\\claude.CMD",
  "claude_home": "C:\\Users\\<user>\\.claude",
  "projects_dir_exists": true,
  "session_count": 1,
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
| `session_count` | **当前目录所属项目**可发现的会话数 | `0` 说明这个目录没跑过 Claude Code（换个目录跑，或 `ccw last --any-project`） |
| `routing_enabled` / `listen` / `provider` | ccSwitch 本地路由状态 | 没装 ccSwitch 时为 `false` / `null`，属正常 |
| `dry_run` | 当前是否只记录不动作 | 默认 `true`，V0.1 应该一直是 `true` |

## 2. 一句话看有没有出事：last

最常用的入口。它替你做完"找会话 → 全量复盘 → 过滤噪音"三步，只留可疑事件。

```powershell
ccw last
```

输出示例（截断、已脱敏）：

```text
session 4f52fcf7-7a1b-4502-90ff-9d31c343ec7d  project=E--github---ClaudeCode-Watchdog  C:\Users\<user>\.claude\projects\...\4f52fcf7-....jsonl
2026-09-11T01:54:57.855Z  SUSPECTED_SILENT_INTERRUPTION    score= 60 stop=None empty=0 model=<model>
  evidence: assistant promised next action but emitted no tool_use; stop_reason absent (proxy/conversion likely)
  text: I'll start by finding all references to the old name in the repo.
  action: dry_run_prompt

117 interesting events, 8 score>=60
等价长命令：ccw replay "C:\Users\...\4f52fcf7-....jsonl"
实时守护这一个会话：ccw watch --session 4f52fcf7-7a1b-4502-90ff-9d31c343ec7d
```

和 `replay` 的区别：

| | `ccw last` | `ccw replay <path>` |
|---|---|---|
| 要不要自己找 jsonl 路径 | 不用 | 要 |
| 打印范围 | `score >= suspicious_threshold`（默认 60） | 所有有意义的事件（含 30 分以上） |
| 结尾 | 附赠可复制的长命令 | 只给统计 |

改门槛：配置里写 `"suspicious_threshold": 80`，`ccw last` 就只报高危事件；此时它会打印 `(no event >= 80)` 而不是空白。

跨项目 / 指定项目：

```powershell
ccw last --project watchdog     # 项目目录名片段（大小写不敏感）
ccw last --any-project          # 当前目录没有会话时，全局找最近的一个
```

## 3. 定位会话：status

```powershell
ccw status
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

把 `session_path` 记下来，第 4、5 步要用。`ccw last` 已经替你做了这一步。

```powershell
ccw status --project watchdog    # 别的目录的项目也能查
ccw status --any-project
```

**注意**：不带范围参数时，会话是按**当前工作目录**推断的 —— 在 `E:\github仓库\ClaudeCode_Watchdog` 下执行，只会列出这个项目的会话。

## 4. 离线复盘一个会话

对一整份 transcript 从头打一遍分。**不碰正在运行的会话，最安全，也最实用** —— 出问题时先用它搞清楚"到底算不算中断"。

```powershell
# 用仓库自带的脱敏样本（推荐第一次跑这个）
ccw replay tests/fixtures/unfinished-text-then-done.jsonl

# 复盘你自己的历史会话（路径直接抄 status 的 session_path，或看 ccw last 结尾打印的长命令）
ccw replay "C:\Users\<user>\.claude\projects\<project>\<session-id>.jsonl"
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

## 5. 实时守着会话

V0.1 没有 daemon/service，**需要另开一个终端**，Claude Code 那个终端照常干活。

```powershell
# 先 cd 到被守护的项目目录，才会自动挑对会话
cd <你的项目目录>

# 只关注启动之后新增的内容（默认行为，推荐日常用）—— 裸命令即可
ccw

# 等价写法
ccw watch

# 显式指定会话：session id 前缀 / 文件名 / 完整路径都接受
ccw watch --session 4f52fcf7
ccw watch --session "C:\Users\<user>\.claude\projects\<project>\<id>.jsonl"

# 别的项目的会话
ccw watch --project watchdog
ccw watch --any-project

# 连已有历史一起扫，并且只扫一次就退出（验证配置很好用）
ccw watch --from-start --once

# 只关心更高分的事件，减少刷屏
ccw watch --min-score 60
```

命中时的输出示例（已脱敏）：

```text
watching C:\Users\<user>\.claude\projects\E--github---ClaudeCode-Watchdog\4f52fcf7-....jsonl dry_run=True
SUSPECTED_SILENT_INTERRUPTION score=60 assistant promised next action but emitted no tool_use; stop_reason absent (proxy/conversion likely)
```

轮询间隔固定 0.5 秒；同一 `(分类, uuid, 分数)` 指纹只打印一次，不会刷屏。打印与写日志的门槛默认 30 分，用 `--min-score` 改。

30 秒内有多个会话被写过时不会瞎猜，直接给你可复制的命令：

```text
AMBIGUOUS_SESSION; 30 秒内有多个会话被写过，选一个：
  ccw watch --session 4f52fcf7-7a1b-4502-90ff-9d31c343ec7d   # E--github---ClaudeCode-Watchdog
  ccw watch --session 3c7d9e21-5b4a-4f6c-9d8e-1a2b3c4d5e6f   # D--demo-Other-Tools
```

**停止**：`Ctrl+C`。`ccw stop` 是占位命令，只打印 `no daemon pid file; stop the watch process`，没有 pid 文件管理。

## 6. 读日志产物

默认落在**当前工作目录**的 `.ccs-watchdog/`（已在 `.gitignore` 里）：

| 文件 | 用途 |
|---|---|
| `events.jsonl` | 机器读。字段：`timestamp` / `watchdog_version` / `classification` / `interruption_score` / `evidence` / `stop_reason` / `empty_assistant_count` / `model` / `last_assistant_text_summary` / `resume_attempt` / `recommended_action` / `session_id` |
| `watchdog.log` | 人读，一行一条 |

```powershell
Get-Content .\.ccs-watchdog\watchdog.log -Tail 20
```

换位置：`ccw watch --log-dir D:\logs\ccwd`，或配置里写 `"log_dir": "D:/logs/ccwd"`（命令行参数优先）。

日志里的文本摘要会先过 `redact()`，API Key / Token 之类不落盘。

## 7. auto-resume 能做什么

```powershell
ccw watch --auto-resume
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

| 分数 | 含义 | 可调的地方 |
|---|---|---|
| `>= 80` | 高置信中断，`--auto-resume` 的门槛 | 配置 `threshold` |
| `60–79` | 可疑，`ccw last` 默认只展示这一档及以上 | 配置 `suspicious_threshold` |
| `>= 30` | `watch` / `replay` 会打印并记日志的门槛 | `watch --min-score <n>` |
| `< 30` | 忽略 | |

分类（11 种）：`NORMAL` / `NORMAL_END` / `TOOL_RUNNING` / `WAITING_USER` / `API_INTERRUPTED` / `EMPTY_RESPONSE` / `REPEATED_EMPTY_RESPONSE` / `SUSPECTED_SILENT_INTERRUPTION` / `SIDE_EFFECT_UNKNOWN` / `ROUTE_SWITCH_SUSPECTED` / `UNKNOWN`。

`replay` 只展示其中"有意思"的（`INTERESTING` 集合）或 `score >= 30` 的，所以 `NORMAL` 之类的不会刷屏。

`ROUTE_SWITCH_SUSPECTED` 是**弱信号**：只表示异常与 ccSwitch 路由/模型切换在时间上邻近，不等于因果。

## 配置文件

```powershell
ccw --config my.json doctor
ccw doctor --config my.json     # 也认，全局参数放前放后都行
```

JSON 格式，可写字段见 `config/defaults.py`（拼错键名或写只读 property 会打 `UserWarning` 并跳过，不再崩）。**仍有若干声明了但未接线的字段**，下表如实标注：

| 字段 | 默认 | 作用 |
|---|---|---|
| `dry_run` | `true` | 只记录不动作 |
| `auto_resume` | `false` | 允许打印恢复提示词 |
| `threshold` | `80` | auto-resume 触发的分数门槛 |
| `suspicious_threshold` | `60` | `ccw last` 的展示门槛 |
| `max_auto_resumes` | `3` | 熔断器上限 |
| `log_dir` | `null` | 日志目录；`--log-dir` 优先 |
| `claude_home` | `~/.claude` | 会话发现根目录（路径类，JSON 里写字符串即可，加载时转 `Path`） |
| `ccswitch_home` | `~/.cc-switch` | ccSwitch 状态目录（路径类） |
| `cooldown_seconds` | `10` | ⚠️ 未接线 |
| `idle_grace_seconds` | `2.0` | ⚠️ 未接线 |
| `empty_consecutive_threshold` | `2` | ⚠️ 未接线，`scoring/score.py` 里写死 `>= 2` |
| `redact_secrets` | `true` | ⚠️ 未接线，日志摘要无条件过 redact |

## 踩坑提示

| 现象 | 原因 / 正确做法 |
|---|---|
| `UserWarning: 忽略未知配置项 ...` | 键名拼错，或写了只读 property（如 `projects_dir`）。警告里会列出全部可用键 |
| `AMBIGUOUS_SESSION; 30 秒内有多个会话被写过` | 直接复制它打印出来的 `ccw watch --session <id>` 那条 |
| 守着守着发现不是目标会话 | 会话按 cwd 推断。跨项目用 `--session <id>` / `--project <片段>` / `--any-project` |
| `no session found（当前目录没有会话…）` | 这个目录没跑过 Claude Code。换目录，或加 `--any-project` |
| `ccw` 卡住没输出 | 正常 —— 守护模式在轮询，只打印 `score >= 30` 的事件。`Ctrl+C` 退出，或先 `ccw --from-start --once` 验证 |
| 改了 `threshold` 但 `watch` 输出没变 | `threshold` 只管 auto-resume；打印/写日志门槛是 `--min-score`（默认 30） |
| `No module named ccs_watchdog` | 没 `pip install -e`，也没设 `PYTHONPATH=src` |
| 只有 `ccs-watchdog` 没有 `ccw` | 装的是旧版本，重装一次：`python -m pip install -e ".[dev]"` |

## 故障排查

- **一个会话都找不到** → `ccw doctor` 看 `projects_dir_exists`。Claude Code 的 transcript 在 `~/.claude/projects/<cwd 编码>/<session-id>.jsonl`；目录名是把 cwd 里**所有**非 `[A-Za-z0-9-]` 字符换成 `-`（中文、空格、下划线都算），见 `discovery/sessions.py:encode_cwd`。
- **`routing_enabled: false` 但装了 ccSwitch** → 检查 `~/.cc-switch` 是否存在、版本是否被 `provider/ccswitch.py` 支持。
- **误判为中断** → 先 `ccw last` / `ccw replay` 看 `evidence`。`WAITING_USER`（模型在等你回答）和 `TOOL_RUNNING` 不该算中断；如果算错了，属于 `scoring/score.py` 的判定问题，欢迎带 fixture 报 issue。
- **测试** → `python -m pytest -q`（当前 46 passed）。


## 安全边界

V0.1 明确不做的事：

- 不注入键盘输入、不 SendKeys、不自动续跑
- 不记录 API Key / Token / Cookie（日志摘要过 redact）
- 不写 `~/.claude/settings.json`，不装全局 Hook
- 不改 ccSwitch 配置
- 不自启动、不做 daemon
