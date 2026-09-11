# ClaudeCode Watchdog

Windows 原生 Claude Code 会话守护工具（V0.1）。

检测并记录：

- 静默提前结束（承诺下一步但 `done`）
- 空 assistant / 连续空响应
- 明显 API Error
- 与 ccSwitch 路由/模型切换的时间邻近性（弱信号）

默认 **dry-run**：只检测、打分、写日志，不自动往终端灌输入。

## 环境

- Windows 11 + PowerShell 7
- Python 3.11+
- Claude Code CLI
- 可选：ccSwitch 本地路由（`~/.cc-switch`）

## 安装

```powershell
cd ClaudeCode_Watchdog
python -m pip install -e ".[dev]"
```

## 快速开始

```powershell
ccw doctor    # 体检：能否找到会话目录与 ccSwitch 路由
ccw last      # 复盘最近一个会话，只列可疑事件（最常用）
ccw           # 实时守护当前项目最近的会话（另开终端，Ctrl+C 停止）
```

包同时安装 `ccw` 和 `ccs-watchdog` 两个命令，二者完全等价，下文用更短的 `ccw` 书写。

完整步骤、字段含义、评分解释、配置项与踩坑清单见 **[docs/USAGE.md](docs/USAGE.md)**。

## 命令

| 命令 | 作用 |
|---|---|
| `ccw` | 等价于 `ccw watch`，守护当前目录推断出的最近会话 |
| `ccw doctor` | 体检环境与 ccSwitch 路由 |
| `ccw status` | 查看当前目录最近的 session |
| `ccw last` | 自动定位最近会话 → 全量复盘 → 只打印 `score >= 60` 的事件 |
| `ccw replay <session.jsonl>` | 离线复盘一份 transcript（打印全部有意义的事件） |
| `ccw watch [--session <id>] [--once] [--from-start] [--min-score <n>] [--log-dir <dir>]` | 实时守护 |
| `ccw install-hook` / `ccw uninstall-hook` | 把本工具注册为 Claude Code 的 Stop hook（可选，见下）/ 一键撤销 |
| `ccw hook <event>` | 内部命令，由 Claude Code 在回合结束时调用，不用手敲 |

共享的范围参数：`--project <片段>` 按项目目录名过滤，`--any-project` 跨所有项目查找；命中多个近期会话时会打印可直接复制的 `ccw watch --session <id>`。

`--auto-resume` 目前只打印建议 resume prompt，**不会**用 SendKeys 往前台窗口打字。

默认日志落在当前目录 `.ccs-watchdog/`（`events.jsonl` + `watchdog.log`）。

## Hook 驱动（可选）

`ccw watch` 要另开一个终端，且只盯启动时挑中的那个会话。Hook 模式把本工具注册成 Claude Code 的 Stop hook，**每个窗口、每次回合结束**都自动经过它，不用常驻进程：

```powershell
ccw install-hook      # 注册（写前备份、只追加自己的条目、可用 uninstall 撤销）
ccw uninstall-hook    # 一键撤销，只删本工具写入的条目
```

**默认只记录 + 提示，不干预回合。** 命中 `suspicious_threshold`（默认 60）时提示一行；日志落在 `~/.claude/watchdog/`。想让 hook 把 Claude 拦回去继续跑，需显式在配置里设 `resume_on_stop: true` 并 `ccw --config <路径> install-hook`；即便开启也受 `threshold`（默认 80）、`max_blocks_per_session`（默认 2）、`stop_hook_active` 三重限制。完整说明见 **[docs/USAGE.md](docs/USAGE.md) 第 8 节**。


## 测试

```powershell
python -m pytest -q
```

真实样本 A/B 来自脱敏后的本地 session 片段（`tests/fixtures/`）。

## 安全

- 不记录 API Key / Token / Cookie
- **默认不碰 `~/.claude/settings.json`**：只有显式跑 `ccw install-hook` 才写，且只追加自己那一条、写前备份、解析失败就拒绝写入、`ccw uninstall-hook` 可完全撤销
- 不修改 ccSwitch 配置
- 默认不自启动、不做 daemon
- **Hook 默认不拦停回合**：`resume_on_stop` 默认 `false`，默认只记录 + 提示；开启后仍受 `threshold`、`max_blocks_per_session`、`stop_hook_active` 三重限制
- `--auto-resume` 与 hook 拦停都不模拟键盘输入：前者只打印提示词，后者走 Claude Code 官方 hook 协议
