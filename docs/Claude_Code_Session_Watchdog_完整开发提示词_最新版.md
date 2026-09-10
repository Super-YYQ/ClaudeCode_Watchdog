# Claude Code Session Watchdog V0.1 — 完整调研、诊断与开发提示词（含 ccSwitch 路由/模型切换专项）

> 适用场景：Windows + PowerShell + Claude Code CLI + ccSwitch + 第三方公益站/中转 API。  
> 目标：让**发生过异常的当前 Claude Code 会话自己取证、分析，并直接实现一个 Windows 原生会话守护工具**，解决 API/流式中断、空响应、Tool use interrupted、以及“没有明显报错却突然 done”的静默异常，并专项分析 ccSwitch 本地路由、provider/model 热切换和协议转换是否参与触发故障。

## 使用方式

请把下方“完整提示词正文”**直接发送到刚刚发生过异常的原 Claude Code 会话**，不要 `/clear`，不要另开 session。这样它可以优先定位当前 session JSONL、最近异常 turn、已有项目状态和真实工具调用历史。

---

# 完整提示词正文

你刚才在本会话中出现过不止一种“任务明显还没完成，但 Claude Code 突然结束当前 turn”的异常。现在暂停原业务开发任务，先对这些异常做一次完整技术取证，然后直接实现一个可用的 Windows 原生守护工具。

这个任务不是咨询，不要只给方案。必须完成：**取证 -> 对照分析 -> 开源项目调研 -> 架构设计 -> V0.1 实现 -> 测试 -> 用真实 session replay 验证 -> 最终报告**。

---

## 1. 已知真实异常样本

### 样本 A：明显承诺下一步动作，但直接 done

本会话出现过类似：

```text
● 明白了。多源轮询方案，通过配置项控制。
  让我看一下前端状态管理和 API 结构，然后开始开发。

✻ Cooked for 3m 5s · done
```

这不是用户要求停止。文本语义明确表示下一步应该继续 Read / Grep / Glob / Bash / Edit 等操作，但实际没有继续。

### 样本 B：连续“空消息”后仍然突然 done

本会话还出现过类似：

```text
● 确认：改动前 engine 测试同样报 13 个 PermissionError，是 Windows 临时目录权限问题，不是我的改动引起的。detectors 全部通过（34/34）。

  现在为镜像功能写测试：

● 上一条是空消息。继续完成方案 C —— 为镜像功能写测试。先看现有测试的结构以便于匹配风格：

● 再来条空消息，我继续推进方案 C 收尾。先看 detectors 测试里 Mirror 相关的已有测试结构来对齐风格：

● 空消息连续收到5条了，不猜测意图，继续按方案C开发。正在为镜像功能写测试。

✻ Baked for 3m 7s · done
```

这里必须重点调查：

- “空消息”在 JSONL 中究竟是什么结构；
- 是否存在 `content: []`；
- 是否存在 assistant message 但 text 长度为 0；
- 是否有 thinking/tool_use block 被截断；
- 是否收到正常 `message_stop`；
- `stop_reason` 是 `end_turn`、`tool_use`、null、缺失还是被代理错误转换；
- 是否出现连续的零内容 turn；
- 是否在 `tool_result` 返回后下一次推理没有产生有效内容；
- 是否是第三方 provider / gateway 返回了 HTTP 200 但 SSE 无有效 Anthropic event；
- 是否是 SSE 打开后立即关闭、只有 ping、`[DONE]`、`null` 或缺少 `message_stop`；
- 为什么最终 TUI 仍显示 `done`，而不是显式 API Error。

这两类异常必须作为 **V0.1 replay 测试的核心真实样本**。

### 待验证假设 C：ccSwitch 路由 + 同一会话内频繁切换 provider/model 可能放大异常

用户观察到：这些异常可能不仅与公益站/中转上游质量有关，也可能与 **ccSwitch 开启本地路由后，在同一个 Claude Code 会话中来回切换不同 provider / model** 有相关性。

这目前只是待验证假设，不得直接当成根因。必须通过当前 session、ccSwitch 路由日志/配置、模型字段、时间戳和 A/B 测试证明或排除。

重点考虑但不要预设成立的可能性包括：

- provider 热切换发生在 agentic loop 中间；
- 前一轮模型和下一轮模型不是同一模型家族；
- Anthropic Messages 原生 provider 与 OpenAI Responses / Chat Completions 转换 provider 之间来回切换；
- tool schema、thinking/reasoning、stop reason、stream event 映射能力不同；
- 模型上下文窗口或 ccSwitch 声明的 context capability 不一致；
- 切换前后的 system/tool definitions、prompt cache、session routing key 或模型角色映射发生变化；
- 切换恰好发生在 `tool_use -> tool_result -> 下一轮 inference` 边界；
- 路由接管启用/关闭后 Claude Code 进程仍持有旧的 live config；
- 某次请求仍在旧 provider 的 SSE stream 中，而 active provider 已切到新 provider；
- 第三方模型经过 ccSwitch 协议转换时，比直接调用同一 provider 更容易出现 empty response / silent stop。

最终报告必须单独回答：**异常与“公益站本身”“ccSwitch 路由”“协议转换”“同 session 切模型”“切换时机”各自的相关性有多强。**

---

## 2. 先调查当前会话本身，不要凭记忆猜原因

不要只根据当前聊天文本猜测。尽可能读取当前 Claude Code 会话实际保存的数据，包括但不限于：

- 当前 session 的 JSONL / conversation history；
- `~/.claude/projects` 下与当前项目对应的 session 文件；
- 当前 session id；
- assistant / user / system message；
- `tool_use`；
- `tool_result`；
- `stop_reason`；
- `message_start`；
- `content_block_start`；
- `content_block_delta`；
- `content_block_stop`；
- `message_delta`；
- `message_stop`；
- `Stop`；
- `StopFailure`；
- `stop_hook_summary`；
- API Error；
- `[Tool use interrupted]`；
- empty assistant content；
- zero-length text / thinking；
- interrupted / cancelled / aborted；
- timeout / EOF / ECONNRESET / socket close；
- stream / SSE / retry；
- compact / context；
- provider / model 信息；
- Claude Code debug 日志（如果存在）；
- Claude Code hooks 配置；
- `settings.json` / `settings.local.json`；
- 与 Claude Code / Anthropic / ccSwitch / API Base URL 有关的环境变量；
- 当前 ccSwitch 版本；
- ccSwitch 本地 Routing 是否启用；
- Claude Code 是否处于 Routing Takeover / 接管状态；
- 本地 route listen address / port；
- 当前 active provider；
- provider 的 API Format / Upstream Format；
- provider/model mapping；
- Sonnet / Opus / Haiku role alias 实际映射到哪个模型；
- ccSwitch usage/routing 日志中每个请求实际命中的 provider/model；
- 最近 provider/model 切换时间；
- 最近 Routing 开启/关闭时间；
- 若 ccSwitch 使用 SQLite / JSON / config 文件保存 provider 和 route 状态，找到实际存储位置并只读检查；
- 如果存在 route request id、trace id、request counter、provider generation/version 等信息，也一并关联。

### 敏感信息保护

检查过程中允许识别 provider、base URL 主机名、模型名等诊断信息，但输出时必须脱敏：

- API Key；
- Token；
- Cookie；
- Authorization Header；
- 密码；
- Secret；
- URL query 中可能存在的凭据。

禁止把完整 secret 写入终端、日志、报告或测试 fixture。

---

## 3. 精确定位两个异常 turn

分别定位样本 A 和样本 B 对应的真实 session 事件。

每个异常至少回答：

1. 最后一条非空 assistant message 是什么？
2. 是否明确表示还有下一步工作？
3. 紧接着有没有 `tool_use`？
4. 是否出现空 assistant message？出现几次？
5. 空消息的 JSON 结构是什么？
6. 是否收到正常 `message_stop`？
7. `stop_reason` 是什么？
8. 是否出现 `Stop`？
9. 是否出现 `StopFailure`？
10. 是否出现 `stop_hook_summary`？
11. 是否存在网络/SSE/API 异常痕迹？
12. 是否存在“响应被截断但 Claude Code 当正常结束”的迹象？
13. 是否可能是公益站/中转网关返回了不完整 Anthropic Streaming Events？
14. 是否可能是 ccSwitch、API 转换层或第三方 provider 对 `tool_use` / `stop_reason` / SSE 的映射不兼容？
15. 为什么 Claude Code 最终显示 `done` 而不是 API Error？
16. 与正常 turn 相比，异常事件序列缺少什么、多了什么或顺序发生了什么变化？
17. 异常发生前 30 秒 / 60 秒 / 120 秒内是否发生过 ccSwitch provider/model 切换？
18. 异常请求和前一个正常请求是否命中了不同 provider 或不同实际模型？
19. 是否发生了 API Format 切换，例如 Anthropic Messages native -> OpenAI Responses/Chat conversion，或反向切换？
20. Claude Code UI 中显示的模型、session JSONL 中记录的模型、ccSwitch 路由日志中的实际 upstream model 是否一致？
21. 异常是否集中发生在 A -> B、B -> A、A -> B -> A 这种同 session 热切换之后？
22. 如果同一 provider/model 绕过 ccSwitch 路由直接调用，是否还能复现？
23. 如果新开 Claude Code session 再使用同一 provider/model，是否还能复现？

输出必须分为：

- **已确认事实**；
- **高度疑似**；
- **暂时无法证明**。

禁止把猜测写成事实。

---

## 4. 做正常与异常事件序列对照

从当前 session 或同项目历史 session 中至少选取：

- 1 个正常执行 `tool_use` 并继续 agent loop 的 turn；
- 1 个正常完成任务后 `end_turn` 的 turn；
- 样本 A；
- 样本 B。

比较真实事件序列。

理论参考仅用于辅助，不得替代真实日志。例如正常工具调用通常类似：

```text
assistant text
-> content_block_start(tool_use)
-> tool input deltas
-> content_block_stop
-> message_delta(stop_reason=tool_use)
-> message_stop
-> tool_result
-> 下一轮 model inference
```

正常最终完成可能类似：

```text
assistant text
-> message_delta(stop_reason=end_turn)
-> message_stop
-> idle
```

而异常必须根据真实 JSONL 写出来，例如：

```text
assistant text / empty assistant
-> ???
-> tool_result ?
-> message_stop missing ?
-> stop_hook_summary ?
-> idle / done
```

我要看到真实差异，而不是只画理论流程图。

---

## 5. 重点研究“空消息”故障

新增一个独立故障分类：

`EMPTY_ASSISTANT_TURN` / `REPEATED_EMPTY_RESPONSE`

重点检测：

- assistant message `content=[]`；
- text 总长度为 0；
- thinking 总长度为 0；
- 无 tool_use；
- message 有 UUID 但没有有效 content；
- 连续 N 个 assistant zero-content turn；
- tool_result 已成功返回，但下一次模型 inference 产生空消息；
- 上一轮 `stop_reason=tool_use`，tool_result 正常，随后 agentic loop 直接停止；
- 有 `stop_hook_summary` 但没有有效 assistant response；
- SSE 结束前没有任何 complete data；
- HTTP 200 但 response body 为空或格式不是 Anthropic Messages；
- SSE 打开立即关闭；
- 只有 keep-alive / ping；
- OpenAI 风格 `[DONE]` 被错误混入 Anthropic stream；
- `data: null`；
- 缺失 `usage` / `message_stop` 等 Claude Code 校验所需字段。

连续空消息应作为 interruption score 的强信号，而不能简单当作用户“发送了空输入”。

同时要区分：

- 用户真的提交空消息；
- Claude Code 内部产生空 assistant turn；
- proxy 返回空 body；
- SSE 没有有效事件；
- tool-use event 转换失败导致最终 content 为空；
- thinking-only block 被过滤后 content 为空。

---

## 6. 判断是否能可靠识别 Silent Premature Stop

我们真正需要解决的不只是普通 API Error，而是：

```text
任务明显未完成
+
assistant 明显表示要继续
+
没有后续 tool_use
+
Claude Code 回到 idle
+
甚至没有明显错误
```

不要用单一正则。设计多信号 `interruption score` / `confidence score`，范围 0-100。

### 信号 A：语义未完成

最后有效 assistant 文本存在明显 future action，例如：

中文：

- 接下来；
- 下一步；
- 然后；
- 现在开始；
- 我会继续；
- 让我查看；
- 我先检查；
- 我准备；
- 开始开发；
- 然后修改；
- 然后运行测试；
- 正在为……写测试。

英文：

- next；
- then；
- I'll；
- let me；
- I will now；
- proceeding to；
- start implementing；
- first I'll；
- now I'll。

但禁止只靠关键词。必须结合工具调用和任务状态。

### 信号 B：协议事件异常

例如：

- 没有正常 `message_stop`；
- `stop_reason` 缺失/null；
- `stop_reason=end_turn` 但文本明显是未完成过渡句；
- `stop_reason=tool_use` 但 tool loop 没继续；
- content block 未闭合；
- tool_use 准备开始但不存在完整 tool_use；
- SSE premature EOF；
- assistant message 被截断；
- StopFailure；
- socket close；
- connection reset；
- upstream timeout；
- HTTP 200 + empty/malformed body。

### 信号 C：空响应

例如：

- `content=[]`；
- textLen=0；
- thinkingLen=0；
- 连续 2/3/5 条 empty assistant message；
- tool_result 后下一轮 zero-content；
- empty streaming attempt 后直接 idle。

### 信号 D：Agent 当前状态

确认：

- Claude Code 已回到等待用户输入状态；
- 最近 N 秒没有输出；
- 没有正在运行的 tool；
- 没有 Bash command 仍在运行；
- 没有 permission prompt；
- 没有 AskUserQuestion；
- 没有 plan approval；
- 没有 MCP elicitation；
- 没有真正需要用户介入的 blocker。

### 信号 E：任务状态

例如：

- Todo / Task 仍有 `in_progress` / `pending`；
- assistant 刚声明下一步动作；
- 当前验收条件明显尚未完成；
- 尚未执行承诺的 compile/test/edit；
- 上一条业务进度明确写着“现在为 X 写测试”，但之后没有 Write/Edit/Test。

### 信号 F：ccSwitch 路由/模型切换邻近性

这不是单独定罪信号，但应进入 interruption score 和根因关联分析：

- 异常前短时间内发生 provider switch；
- 异常前短时间内发生 model switch；
- Routing Master Switch / Claude Code takeover 被开启或关闭；
- 从 direct provider 切到 routed provider，或反向；
- 从 Anthropic-native 切到 Responses/Chat conversion，或反向；
- 实际 upstream model 与 Claude Code 显示模型不一致；
- role alias 在切换后指向不同真实模型；
- context/window 声明发生变化；
- thinking/reasoning 能力映射发生变化；
- 切换发生在未完成 tool call、tool_result 刚返回、compaction、retry 等敏感边界附近。

如果仅存在“最近切过模型”但事件序列完全正常，分值不能过高；如果同时出现协议断裂、empty response、provider 变化和时间高度重合，才提升为强证据。

### 建议分类

至少支持：

```text
NORMAL
NORMAL_END
TOOL_RUNNING
WAITING_USER
API_INTERRUPTED
EMPTY_RESPONSE
REPEATED_EMPTY_RESPONSE
SUSPECTED_SILENT_INTERRUPTION
CONFIRMED_PROTOCOL_BREAK
ROUTE_SWITCH_SUSPECTED
ROUTE_SWITCH_RACE
PROVIDER_SWITCH_NEAR_FAILURE
MODEL_SWITCH_CONTEXT_DRIFT
PROTOCOL_CONVERSION_FAILURE
STALE_ROUTING_CONFIG
SIDE_EFFECT_UNKNOWN
UNKNOWN
```

---

## 7. ccSwitch 本地路由、Provider/Model 热切换专项调查

这一章是本项目的**核心新增调查项**。用户怀疑故障与以下组合有关：

```text
Claude Code CLI
  -> ccSwitch 本地 Routing
  -> 第三方公益站 / 中转站
  -> 不同模型 / 不同协议上游
  -> 同一个 Claude Code session 内来回热切换
```

不要把“ccSwitch 有 bug”或“切模型一定丢上下文”当作前提。要通过真实日志、源码和可重复实验判断：

- 是公益站本身不稳定；
- 是 ccSwitch route/proxy 层引入；
- 是协议转换层引入；
- 是 provider/model 热切换引入；
- 是 Claude Code 对 mid-session model/provider switch 的行为引入；
- 还是以上因素叠加。

### 7.1 先确认 ccSwitch 的真实版本与工作模式

必须读取当前机器真实状态，不使用记忆中的版本号。

至少记录：

- ccSwitch version；
- Claude Code version；
- Windows / PowerShell version；
- Routing Master Switch 是否开启；
- Claude Code Routing Enabled / Takeover 是否开启；
- 当前 `ANTHROPIC_BASE_URL` 实际值；
- Claude Code 进程启动时读取到的 base URL；
- ccSwitch 本地监听地址和端口；
- 当前 provider；
- provider 类型；
- API Format / Upstream Format；
- auth field 类型（只记录类型，禁止记录 key）；
- model mapping；
- Sonnet / Opus / Haiku role alias 到真实 upstream model 的映射；
- context / 1M 等 capability 声明；
- thinking/reasoning 配置与转换；
- provider 是否 direct；
- provider 是否 requires routing；
- 是否启用了“模拟 Claude Code client”等兼容选项。

### 7.2 理解并验证 ccSwitch 的热切换语义

根据当前 ccSwitch 官方文档和源码重新确认，不得凭旧版本经验。

目前值得重点验证的行为包括：

1. Claude Code 被 Routing Takeover 后，live config 会指向 ccSwitch 本地 route；
2. **首次启用 takeover 或关闭 takeover 恢复 direct 模式后，运行中的 Claude Code 可能需要新开终端/session 才能读取新的 live config；**
3. 在 Routing 一直开启的前提下，ccSwitch 支持 provider hot switch；
4. `/model` 菜单或 UI 展示名未必能即时反映 route 后真实 upstream model，因此不能只看 TUI 文案判断模型；
5. 应以 ccSwitch routing/usage 日志中“该请求实际命中的 provider + upstream model”为主要证据。

请直接审查当前版本源码，确认“hot switch”具体实现：

- active provider 是按请求开始时 snapshot，还是整个 stream 生命周期动态查询？
- 一次请求开始后切换 provider，会不会影响正在进行中的 SSE stream？
- tool_result 后发出的下一轮 inference 是否会立即使用新 provider？
- provider 切换是否有 generation/version/request binding？
- 路由层是否保证一个 request 从开始到结束固定绑定同一个 upstream？
- 是否可能旧 stream 尚未完全关闭，新 provider 已成为 active provider？
- 切换 provider 时连接池、HTTP client、SSE parser 是否复用？
- route state 是否线程安全/原子更新？
- Windows 下 route service 重载配置是否存在竞态？

### 7.3 专门研究“同一个 session A -> B -> A”

这是重点复现场景。

建立真实时间线：

```text
T0 session start
T1 provider/model A request
T2 tool_use
T3 tool_result
T4 ccSwitch switch A -> B
T5 provider/model B request
T6 empty response / normal response
T7 ccSwitch switch B -> A
T8 next request
T9 silent done / empty response / tool interruption
```

对当前真实异常，尽可能恢复类似时间线。

每个请求至少关联：

```text
timestamp
session_id
request_id / trace_id（若有）
turn/message id
Claude Code model field
ccSwitch active provider
actual upstream model
api format
route mode
stream start
first token
last valid event
message_stop
stop_reason
tool_use id
tool_result id
route/provider switch event
```

如果无法拿到 request id，也要通过时间戳和相邻事件尽可能关联。

### 7.4 重点检查跨模型的上下文与能力不一致

同一个 Claude Code transcript 可以继续存在，但**这不等于不同模型/provider 对上下文、工具和推理状态的解释完全兼容**。

重点检查：

- A 与 B 的 context window 是否不同；
- ccSwitch 是否向 Claude Code 声明统一的保守 context window；
- 切换后是否突然触发 auto-compact；
- 前一个模型留下的 tool_use / tool_result 对新模型是否仍满足其协议约束；
- thinking block / reasoning item 是否能被另一协议/模型继续消费；
- encrypted/opaque reasoning state 是否跨模型可用；
- system prompt、tool definitions、MCP tools 在切换前后是否完全一致；
- tool choice / parallel tool calls / tool id 格式是否兼容；
- image/PDF/web search 等 capability 是否在新模型不存在；
- max_tokens / max_output_tokens 是否因为新 provider 的缺省值而降低；
- provider model mapping 是否把 Claude Code 的 `sonnet`/`opus` alias 映射成了不同真实模型；
- 模型 switch 后 Claude Code UI 仍显示旧 alias，导致用户以为没切，实际 route 已切；
- 新模型是否把前一模型的“准备调用工具”的自然语言当成已经完成的上下文，从而直接 end_turn；
- provider 是否对长 transcript、cache_control、thinking block 或 tool_result 有兼容性限制。

特别注意：不要简单宣称“切换模型一定丢失上下文”。要区分：

1. transcript 是否仍然被 Claude Code 发送；
2. route 是否仍然保留 session key/cache key；
3. upstream 是否支持这些历史消息结构；
4. 新模型是否能语义上正确承接；
5. protocol adapter 是否丢字段。

### 7.5 重点检查协议转换边界

如果 ccSwitch 把 Claude Code 的 Anthropic Messages 请求转换为：

```text
OpenAI Responses
或
OpenAI Chat Completions
```

再把上游 JSON/SSE 转回 Anthropic Messages，那么本项目必须把**协议转换**作为独立故障源。

检查：

- `message_start` 如何生成；
- text/thinking/tool_use block 如何转换；
- tool call id 如何保持；
- `stop_reason` 如何从 upstream finish reason / status 映射；
- OpenAI `[DONE]` 如何转成 Anthropic `message_stop`；
- upstream incomplete / max_tokens / cancelled 如何映射；
- 空 delta 如何处理；
- only-reasoning/no-text 响应如何处理；
- tool call arguments streaming 如何拼接；
- malformed partial JSON 如何处理；
- upstream stream EOF 没有结束事件时 route 是抛错还是“正常 close”；
- route 是否可能生成 HTTP 200 + 空 Anthropic message；
- 不同 provider 的兼容分支是否使用不同 parser/adapter；
- A -> B 切换时 parser/adapter 是否可能选错。

对于“连续空消息”样本，尤其验证：

```text
上游是否有内容
-> ccSwitch adapter 是否把它过滤掉
-> Claude Code 最终收到 content=[]
```

以及：

```text
上游本身就是空响应
-> ccSwitch 是否仍包装成正常 Anthropic success
-> Claude Code 因此显示 done
```

### 7.6 检查切换时机是否位于危险窗口

记录用户切换 provider/model 时，Claude Code 正处于：

- idle；
- thinking；
- streaming text；
- streaming tool_use arguments；
- 等待 tool result；
- Bash/Read/Edit 正在执行；
- tool_result 刚写入 transcript；
- retry/backoff；
- compact；
- Stop/StopFailure hook；
- subagent 正在运行。

特别测试：

- **仅在 idle 时切换**；
- tool call 完全结束后切换；
- tool_result 后、下一轮 inference 前切换；
- stream 尚未结束时切换（只用于受控 dry-run/测试环境，不要对有副作用任务乱做）；
- A -> B -> A 快速切换；
- 切换后立即发请求；
- 切换后等待 3/5/10 秒再发请求。

如果只有敏感窗口会复现，应分类为 `ROUTE_SWITCH_RACE` 或同类问题，而不是笼统写“公益站不稳定”。

### 7.7 对 ccSwitch 做 A/B/C/D 隔离实验

至少设计以下矩阵，能安全执行的就实际执行；涉及真实付费/危险操作时使用最小只读 prompt：

| Case | Claude session | ccSwitch Routing | Provider/Model | 是否切换 | 目的 |
|---|---|---|---|---|---|
| A | 新 session | OFF/direct | 同一第三方模型 | 否 | 测 provider 本身 |
| B | 新 session | ON | 同一第三方模型 | 否 | 测 route/adapter 增量风险 |
| C | 同一 session | ON | A -> B | 是 | 测一次热切换 |
| D | 同一 session | ON | A -> B -> A | 是 | 测来回切换 |
| E | 新 session | ON | B | 否 | 判断是否只是旧 session 状态污染 |
| F | 同一 session | ON | A 固定 | 否 | 长 agent loop 基线 |
| G | 同一 session | ON | A -> B | 仅 idle 切 | 测安全窗口 |
| H | 同一 session | ON | A -> B | tool 边界切 | 测竞态窗口 |

每个 Case 记录：

- 有效 response 数；
- empty response 数；
- silent done 数；
- explicit API error 数；
- tool interruption 数；
- 平均 first-token latency；
- stream abnormal close 数；
- stop_reason 分布；
- message_stop 缺失次数；
- 是否 auto-resume；
- resume 是否成功。

不要为了测试而高频打公益站。用足以区分问题的最小样本。

### 7.8 Watchdog 必须记录 Route/Model Switch History

V0.1 如果能获取，应新增结构化事件：

```text
ROUTING_ENABLED
ROUTING_DISABLED
ROUTING_TAKEOVER_CHANGED
PROVIDER_SWITCH
MODEL_SWITCH
MODEL_MAPPING_CHANGED
API_FORMAT_CHANGED
ROUTE_TARGET_CHANGED
SESSION_STARTED_AFTER_SWITCH
REQUEST_PROVIDER_BOUND
```

事件字段至少：

```text
timestamp
session_id
old_provider
new_provider
old_model
new_model
old_api_format
new_api_format
route_enabled
source
```

敏感字段必须脱敏。

发生 interruption 时，报告中自动附加：

```text
last_route_switch_age_ms
last_provider_switch_age_ms
last_model_switch_age_ms
provider_before_failure
model_before_failure
previous_provider
previous_model
api_format_before_failure
```

这样后续才能统计：

> “90% 的 silent interruption 都发生在模型切换后 60 秒内”

或反过来证明：

> “异常与模型切换没有显著相关性，固定 provider 也同样发生。”

### 7.9 Auto Resume 不能偷偷换 provider

如果异常发生时当前 provider/model 与上一轮不同，Watchdog 不得盲目执行：

```text
continue
```

然后让任务在未知 provider 上继续。

恢复策略至少应知道：

- interrupted request 原本绑定哪个 provider/model；
- 当前 active provider/model 是什么；
- 两者是否一致；
- 用户是否刚主动切换模型；
- 是否应该保持用户当前选择；
- 是否只做状态检查而不自动 resume。

默认规则建议：

- 如果只是 provider 自己中断，且 current provider 未变，可进入正常 safe-resume 流程；
- 如果 interruption 与最近一次 model/provider switch 高度重合，优先 `manual_review` 或 dry-run 提示；
- 不要未经用户允许自动切回旧模型；
- 不要为了“提高成功率”自动轮询多个公益站；
- 不要让同一个有副作用步骤在不同模型/provider 上重复执行。

### 7.10 需要重点调研的 ccSwitch 资料和 Issue

必须重新核对当前最新状态、源码和修复版本，不要只引用标题：

1. CC Switch 官方 Claude Code <-> Codex 路由文档：
   https://github.com/farion1231/cc-switch/blob/main/docs/guides/claude-codex-routing-guide-en.md

   重点确认：Routing Takeover、provider hot switch、live config 何时读取、protocol conversion、model mapping、context/compaction、tool/reasoning conversion。

2. CC Switch Issue #1234：第三方模型长交互输出中断/停在 `●`
   https://github.com/farion1231/cc-switch/issues/1234

   这个案例与当前故障非常接近。重点调查涉及版本、第三方 provider/model、旧版正常而新版异常的原因、Issue 关闭原因、对应 PR/commit/release fix、当前安装版本是否包含修复以及是否有 regression。

3. CC Switch Issue #6127：开启 Routing 后切回非路由 provider 出现 timeout/connection refused
   https://github.com/farion1231/cc-switch/issues/6127

   重点调查 takeover restore、`ANTHROPIC_BASE_URL` 是否残留本地 route、route service 关闭后旧 Claude Code 进程是否仍请求 localhost、是否必须新开 terminal/session、Windows 是否存在状态残留。

4. Claude Code 关于同 session model/provider switch/context 的相关 Issue：
   https://github.com/anthropics/claude-code/issues/46423

   这只能作为调查线索。必须判断它描述的“直接修改 `ANTHROPIC_MODEL` / `ANTHROPIC_BASE_URL`”与 ccSwitch 在固定 local route 后内部 hot-switch upstream 的机制是否真的等价，不能直接套用结论。

此外继续搜索：

```text
cc-switch provider switch interrupted
cc-switch hot switch stream
cc-switch empty response
cc-switch tool use interrupted
cc-switch third party model output stops
cc-switch SSE
cc-switch route race
cc-switch model mapping tool call
Claude Code switch provider mid session
Claude Code switch model tool_result
```

### 7.11 给最终根因报告增加 ccSwitch 专项结论

最终报告必须额外给出：

```text
ccSwitch involvement: CONFIRMED / LIKELY / POSSIBLE / UNLIKELY / RULED_OUT
routing involvement: ...
provider hot-switch involvement: ...
model-switch involvement: ...
protocol-conversion involvement: ...
stale live-config involvement: ...
upstream provider involvement: ...
```

每一项都附证据。

如果能定位到 ccSwitch 某个版本 regression，写清：

```text
last known good version
first known bad version
suspected commit/PR
fixed version（如果存在）
workaround
```

如果暂时不能证明，也要给最小复现步骤和下一步应采集的日志，而不是直接归因。

---

## 8. 调研现有开源项目，不要从零重复造轮子

确定技术方案前必须审查以下项目。不要只读 README，尽量看源码、Issue、提交历史、License 和实际恢复逻辑。

### 7.1 cheapestinference/claude-auto-retry

GitHub：

https://github.com/cheapestinference/claude-auto-retry

这是目前最接近本需求的项目之一。

重点研究：

- interrupted-stream resume；
- dropped connection；
- `response stopped arriving`；
- server error mid-response；
- laptop suspend；
- idle prompt 判断；
- tmux pane tail 检测；
- safe send-keys；
- maxRetries；
- backoff / jitter；
- overload 429/5xx/529；
- customPatterns；
- retry message；
- 如何防止匹配 scrollback 中历史错误；
- 如何区分 Claude Code 自己正在 retry 与最终失败。

特别拆分：

**检测逻辑 / 状态机 / retry 逻辑** 与 **tmux terminal backend**。

不要因为它依赖 tmux 就放弃研究。我们的 Windows 工具可能复用前者、替换后者。

### 7.2 reglisseblip/claude-auto-retry-windows

GitHub：

https://github.com/reglisseblip/claude-auto-retry-windows

重点研究：

- psmux；
- Windows 10/11；
- PowerShell / cmd / Git Bash；
- `claude` / `claudem` 包装方式；
- capture pane；
- send-keys；
- session attach / orphan 检测；
- monitor 生命周期；
- `doctor`；
- `sessions`；
- `reap`；
- `status`；
- `logs`；
- PID / session 管理；
- hard-close 后清理。

判断能否将：

```text
cheapestinference 的 stream interruption/retry 思路
+
Windows fork 的 psmux/session backend
```

组合起来。

但不要默认必须 psmux。如果直接 JSONL + 进程状态即可可靠识别，优先选择更轻量方案。

### 7.3 zhangfeiyang/claude-auto-retry

GitHub：

https://github.com/zhangfeiyang/claude-auto-retry

重点研究：

- `SessionStart` 启动后台 daemon；
- daemon 如何监控 session JSONL；
- 如何识别错误 pattern；
- 如何找到当前 session；
- 如何提取最后 prompt；
- `CLAUDE_RETRY_MAX`；
- `CLAUDE_RETRY_INTERVAL`；
- `CLAUDE_RETRY_PATTERN`；
- Linux/macOS `/dev/pts`；
- Windows `WScript.Shell SendKeys`。

重点评估 Windows SendKeys 风险：

- 焦点窗口错误；
- 多 Claude Code session；
- 多 PowerShell 窗口；
- 用户切换前台窗口；
- 窗口最小化；
- 管理员权限边界；
- 中文与特殊字符；
- 将输入误发到其他程序。

如果不够可靠，寻找更安全的 session-targeted 输入方式。

### 7.4 Anthropic 官方 Claude Code Hooks

官方文档：

https://code.claude.com/docs/en/hooks

必须以**当前安装版本 + 最新官方文档**为准确认：

- Stop；
- StopFailure；
- SessionStart；
- SessionEnd；
- PostToolUse；
- PostToolUseFailure；
- PostToolBatch；
- `session_id`；
- `transcript_path`；
- `last_assistant_message`；
- `stop_hook_active`。

特别注意：

- `Stop` 可以 `decision:block` 阻止正常停止；
- API error 走 `StopFailure`；
- `StopFailure` 的 output 和 exit code 被忽略，不能靠它阻止停止；
- StopFailure 仍可用于日志、告警或触发外部恢复逻辑。

因此不要把整个方案建立在“StopFailure Hook 返回 block”这种无效假设上。

### 7.5 Claude Code streaming / empty response / silent termination Issue

搜索并审查与以下关键词相关的官方仓库 Issue：

- stream silently terminates；
- response stops mid-stream；
- SSE premature EOF；
- connection lost without retry；
- agent stops unexpectedly；
- empty assistant content；
- zero content after tool_result；
- tool_use interrupted；
- proxy streaming；
- message_stop missing；
- stop_reason missing；
- API proxy compatibility。

特别留意一种已经公开出现过的故障模式：

```text
assistant: stop_reason=tool_use + tool_use block
user: tool_result 成功
随后没有有效 assistant content
agentic loop 却结束
无明显 API error
```

这与当前“连续空消息 + 最终 done”高度相关。

不要只罗列 Issue URL。必须写出：

- 相同点；
- 不同点；
- 是否能解释当前样本；
- 对 detector/state machine 有什么启发。

### 7.6 第三方 Anthropic compatibility proxy / gateway

额外搜索实现 Anthropic Messages/SSE 转换的代理项目，重点关注它们如何处理：

- empty body；
- malformed HTTP 200；
- stream opens then immediately closes；
- ping-only stream；
- `data: null`；
- OpenAI `[DONE]`；
- missing `message_stop`；
- missing usage；
- tool-use stop reason mapping；
- upstream thinking/max_tokens 不兼容；
- 空响应 retry。

目标是理解公益站/聚合网关最容易在哪一层制造“Claude Code 看起来正常 done，实际响应不完整”。

---

## 9. 对现有项目做架构对比

调研完成后输出表格：

| 项目 | 主要目标 | Windows | JSONL监听 | Terminal监控 | Stream中断检测 | Empty Response | Silent Stop | 自动Resume | 风险 |
|---|---|---|---|---|---|---|---|---|---|

然后明确回答：

1. 哪些能力已有成熟实现？
2. 哪些能力可以直接借鉴？
3. 哪些能力不适合本项目？
4. 哪些能力目前仍缺成熟实现？
5. 我们真正需要新增的核心能力是什么？

重点新增能力应至少考虑：

```text
Silent Premature Stop Detector
Repeated Empty Response Detector
Protocol Sequence Validator
Side Effect Safety Guard
Replay Engine
Provider Reliability Statistics
```

---

## 10. 不要直接安装第三方项目

调研阶段允许：

- git clone 到临时研究目录；
- 阅读源码；
- git log；
- git show；
- git diff；
- 查看 Issues / Releases；
- 运行确认无持久化副作用的只读测试。

禁止未经审查：

- 修改 `~/.claude`；
- 安装全局 Hook；
- 覆盖 `settings.json`；
- 安装 daemon；
- 注册 Windows 自启动；
- 修改 PowerShell Profile；
- 执行未知 install.sh / install.ps1；
- 修改 ccSwitch 配置；
- 导出或打印 API Key。

如果确实需要运行第三方代码，先审查，再运行最小安全部分。

---

## 11. License 和代码复用

如果决定复用第三方源码，必须先检查 License。

区分：

- 借鉴架构思想；
- 根据原理重新实现；
- 直接复制代码。

直接复制时记录：

```text
Source
License
Original file
Modification
```

来源不明或 License 不兼容的代码禁止直接加入项目。

---

## 12. 设计 Windows 原生 Claude Code Session Watchdog

主要环境：

- Windows 11 / Windows；
- PowerShell 7；
- Claude Code CLI；
- ccSwitch；
- 第三方公益站 / 中转 API；
- 有时切回官方 provider；
- 不希望依赖 WSL；
- 尽量不要依赖 tmux；
- 尽量避免 Bash-only；
- 不修改 Claude Code 本体。

工具暂定名：

`Claude Code Session Watchdog`

核心职责：监控一个或多个 Claude Code session，识别异常结束，并在安全条件满足时恢复。

候选架构：

```text
Claude Code
   |
   +--> ~/.claude/projects/.../*.jsonl
   |          |
   |          v
   |   Incremental JSONL Reader
   |          |
   |          v
   |   Event Normalizer
   |          |
   |          v
   |   Session State Machine
   |          |
   |    +-----+------------------+
   |    |                        |
   |    v                        v
   | Protocol Detector      Semantic/Task Detector
   |    |                        |
   |    +-----------+------------+
   |                v
   |        Interruption Scorer
   |                |
   |       +--------+---------+
   |       |                  |
   |       v                  v
   |    NORMAL          SUSPECTED/ERROR
   |                          |
   |                          v
   |                Side Effect Safety Guard
   |                          |
   |                +---------+---------+
   |                |                   |
   |                v                   v
   |          AUTO_RESUME          MANUAL_REVIEW
   |                |
   |                v
   +-------- Resume Controller
```

不要为了符合这个草图强行实现；根据实际数据调整。

---

## 13. 技术路线选择

检查当前机器已有环境，在以下方案中选择最合理的一种：

A. PowerShell

B. Node.js + TypeScript

C. Python

D. PowerShell launcher + Node.js daemon

优先考虑：

- Windows 原生；
- FileSystemWatcher / 增量 JSONL 读取稳定；
- event/state machine 好实现；
- CLI 好做；
- 测试方便；
- 打包方便；
- 多 session 扩展容易；
- 不依赖前台窗口焦点更佳；
- 能做 replay；
- 日志清晰。

不要因为“PowerShell 写起来最快”就默认 PowerShell。给出选型证据。

---

## 14. 当前阶段优先考虑 JSONL-first，而不是 terminal-first

优先研究是否能只依赖：

```text
Claude session JSONL
+
Hook 提供的 transcript_path/session_id（可选）
+
进程/终端状态
+
debug log（可选）
```

实现绝大多数检测。

理由：terminal 文本容易受：

- TUI 样式；
- 版本变化；
- 中文/英文；
- spinner/footer；
- scrollback；
- 窗口宽度；
- ANSI；
- tmux/psmux；
- 焦点窗口。

影响。

但如果 JSONL 缺少“Claude 当前是否已真正 idle”的信息，可以采用 hybrid：

```text
JSONL = 主证据
terminal/process = 状态确认
```

---

## 15. 自动发现当前/最近 session

V0.1 至少实现：

- 根据当前 cwd 匹配 `~/.claude/projects`；
- 最近修改时间；
- session id；
- JSONL 正在增长；
- 可选 PID/terminal 对应关系；
- 用户可显式 `--session <id/path>` 覆盖自动发现。

多个活跃 session 时禁止猜错，进入 `AMBIGUOUS_SESSION` 或要求显式指定。

---

## 16. 增量 JSONL 监听

要求：

- 不每次读取整个巨大 JSONL；
- 保存 byte offset；
- 支持 partial line；
- 支持文件 rotate/rename 的合理处理；
- UTF-8；
- JSON parse error 不崩 daemon；
- 记录未知 event schema；
- Claude Code 升级新增字段时尽可能向后兼容。

建立内部 normalized event，例如：

```text
ASSISTANT_TEXT
ASSISTANT_EMPTY
TOOL_USE_STARTED
TOOL_USE_COMPLETED
TOOL_RESULT
API_ERROR
STOP
STOP_FAILURE
MESSAGE_STOP
TASK_STATE
USER_INTERACTION_REQUIRED
UNKNOWN_EVENT
```

---

## 17. Protocol Sequence Validator

实现一个轻量状态机验证常见事件顺序。

重点发现：

- `tool_use` 后缺 `tool_result`；
- tool_result 后缺下一轮有效 assistant；
- `stop_reason=tool_use` 后 agent loop 直接停止；
- content block 开始但未结束；
- `message_start` 有但 `message_stop` 缺失；
- zero-content message；
- 多个连续 zero-content；
- `end_turn` 与 task state/语义明显矛盾。

不要要求所有 provider 必须产生完全一致的低层 SSE event，因为 JSONL 可能只保存聚合结果。根据实际 Claude Code transcript schema 设计。

---

## 18. Interruption Score

设计 0-100 分。

示例仅供参考，必须通过真实数据校准：

```text
+35 连续 >=2 个 assistant empty content
+30 assistant 明确承诺下一步但无 tool_use
+30 stop_reason=tool_use + tool_result 后无下一轮有效 assistant
+25 message_stop 缺失/异常
+25 StopFailure / connection / stream error
+20 Todo/Task 仍有 in_progress
+15 最近动作表明测试/实现尚未完成
+10 provider 为第三方 proxy（只能作为弱信号，不能单独判错）

-50 当前存在 AskUserQuestion / permission / approval
-50 当前 tool 正在运行
-40 正常 end_turn + 明确最终总结
-30 用户主动中断
```

阈值示例：

```text
0-29   NORMAL / UNKNOWN
30-59  SUSPICIOUS，记录但不恢复
60-79  SUSPECTED_INTERRUPTION，dry-run 提示
80-100 HIGH_CONFIDENCE_INTERRUPTION
```

V0.1 默认 dry-run，所以即使高分也只记录，除非显式 `--auto-resume`。

---

## 19. Resume Controller

不要默认只发：

```text
continue
```

使用更安全的 resume prompt，例如：

```text
检测到上一轮响应可能因上游流式连接/空响应异常而提前结束。
请先检查当前会话已有进度和最近成功的 tool_result，从最后一个已确认完成的步骤之后继续。
不要重复已经成功执行的 Edit、Write、Bash 或其他有副作用操作；如果上一操作执行状态不确定，先验证当前状态，再决定是否继续。
```

对明显“连续空响应”可以加入：

```text
上一轮出现连续空 assistant response，请不要把空响应解释为用户新指令；继续原任务。
```

---

## 20. Side Effect Safety Guard

这是自动恢复的安全核心。

自动恢复前检查最近工具。

### 相对安全，可重新检查状态后继续

例如：

- Read；
- Grep；
- Glob；
- git status；
- git diff；
- git log；
- compile/test（通常可重跑，但仍要结合项目）；
- 纯查询命令。

### 执行结果未知时禁止盲目自动重试

包括：

- Edit / Write 是否已经落盘不确定；
- git commit；
- git push；
- rm / delete；
- mv / destructive replace；
- DB INSERT/UPDATE/DELETE/DDL；
- deploy；
- publish；
- HTTP POST/PUT/PATCH/DELETE；
- 发邮件/消息；
- 支付/购买；
- 任何外部系统写操作。

进入：

`SIDE_EFFECT_UNKNOWN` / `MANUAL_REVIEW`

不要自动重试原命令。

可以允许自动 resume prompt 只要求 Claude **先验证状态**，但如果无法确保不会重复副作用，则等待用户。

---

## 21. 用户交互等待识别

以下状态绝不能被 watchdog 当“中断”：

- permission prompt；
- AskUserQuestion；
- plan approval；
- login；
- captcha；
- 2FA；
- sudo/password；
- MCP elicitation；
- 用户明确要求暂停；
- user interrupt / Ctrl+C；
- 需要人工选择文件/设备。

分类为：

`WAITING_USER`

---

## 22. 防止无限循环

必须实现：

- 最大连续恢复次数；
- 同一 fingerprint 去重；
- cooldown；
- exponential backoff；
- session retry counter；
- reset 条件；
- circuit breaker。

示例：

```text
第 1 次：3 秒
第 2 次：10 秒
第 3 次：30 秒
之后：熔断
```

触发熔断后：

```text
该 session 已连续发生 N 次疑似上游中断，自动恢复已停止，请人工检查 provider / gateway / session 状态。
```

连续空响应尤其需要快速熔断，避免公益站故障时无限发送请求。

---

## 23. Provider 识别与可靠性统计

如果能识别：

- `ANTHROPIC_BASE_URL`；
- model；
- ccSwitch 当前 provider；
- 官方/第三方；

则记录**脱敏 provider id**。

不要记录 Key。

除 provider 本身外，还要按以下维度切分统计：

- routed vs direct；
- ccSwitch version；
- API Format / Upstream Format；
- actual upstream model；
- 是否发生过本 session model/provider switch；
- failure 距离最近一次 switch 的时间桶（0-10s / 10-60s / 1-5min / >5min）；
- A->B、B->A、A->B->A 等切换路径；
- 新 session vs 切换后的旧 session。

统计：

```text
request/turn count
normal end
api interrupted
empty response
repeated empty response
silent interruption
auto resume attempts
resume success
manual review
```

用于后续比较：

```text
官方 provider vs 公益站 A vs 中转站 B
```

但 V0.1 不要根据 provider 名称直接判定异常，只作为统计维度和弱信号。

---

## 24. 日志

至少输出：

- `watchdog.log`：给人看；
- `events.jsonl`：结构化事件。

字段至少包括：

```text
timestamp
watchdog_version
session_id
provider (masked)
model
event_type
classification
last_assistant_text_summary
empty_assistant_count
stop_reason
last_tool
tool_state
task_state
interruption_score
evidence[]
resume_attempt
resume_result
circuit_breaker_state
routing_enabled
ccswitch_version
active_provider
actual_upstream_model
api_format
last_provider_switch_age_ms
last_model_switch_age_ms
```

禁止记录：

- API Key；
- Authorization；
- Cookie；
- 密码；
- 完整敏感 HTTP body。

日志应支持自动 secret redaction。

---

## 25. CLI 运行模式

至少实现：

### watch

```text
watchdog watch
watchdog watch --session <id/path>
watchdog watch --dry-run
watchdog watch --auto-resume
```

### status

显示：

- watchdog 是否运行；
- PID；
- 当前 session；
- provider；
- model；
- 当前 classification；
- 最近异常；
- retry 次数；
- circuit breaker；
- 最近 JSONL offset。

### logs

查看最近事件。

### doctor

检查：

- Claude Code 是否存在；
- Claude Code version；
- `~/.claude`；
- projects/session 路径；
- PowerShell；
- Node/Python（按实现技术）；
- 文件读取权限；
- hook 配置状态；
- provider 是否可识别；
- terminal backend 是否可用；
- 是否存在多 session 歧义。

### replay

```text
watchdog replay <session.jsonl>
watchdog replay <session.jsonl> --verbose
```

### stop

停止 daemon/watchdog。

---

## 26. Replay Engine 是 V0.1 核心，不是附加功能

必须能对历史 Claude session JSONL 进行离线重放。

输出至少：

```text
Timestamp
Turn/Message ID
Classification
Score
Evidence
Previous tool
stop_reason
Empty count
Recommended action
```

分类：

```text
NORMAL
INTERRUPTED
EMPTY_RESPONSE
REPEATED_EMPTY_RESPONSE
SUSPECTED_SILENT_INTERRUPTION
ROUTE_SWITCH_SUSPECTED
ROUTE_SWITCH_RACE
PROTOCOL_CONVERSION_FAILURE
STALE_ROUTING_CONFIG
WAITING_USER
TOOL_RUNNING
SIDE_EFFECT_UNKNOWN
UNKNOWN
```

必须拿**当前真实 session**验证样本 A 和 B。

理想结果类似：

```text
Sample A
Classification: SUSPECTED_SILENT_INTERRUPTION
Score: 87/100
Evidence:
- assistant explicitly announced next action
- no subsequent tool_use
- task remained incomplete
- session returned to idle

Sample B
Classification: REPEATED_EMPTY_RESPONSE / SUSPECTED_SILENT_INTERRUPTION
Score: 95/100
Evidence:
- multiple zero-content assistant turns
- previous task remained in progress
- no meaningful tool activity after continuation statements
- agentic loop ended at idle/done
```

实际分数和 evidence 必须由真实日志决定，不允许为了满足例子伪造。

此外 replay/fixture 必须加入 ccSwitch 场景：

- routed provider 固定、不切模型的正常长任务；
- 同 session A -> B 后正常继续；
- 同 session A -> B 后 empty response；
- 同 session A -> B -> A 后 silent done；
- 切换发生在 tool_result 后；
- Routing takeover 关闭但旧 Claude Code 进程仍指向 localhost 的 stale config；
- API format 从 native Anthropic 切到 Responses/Chat conversion 后出现 protocol break。

---

## 27. Dry-run 默认开启

V0.1 默认：

```text
auto-resume = false
```

默认只检测、打分、记录、提示。

只有用户显式：

```text
--auto-resume
```

才允许尝试自动输入。

并且 Side Effect Safety Guard / WAITING_USER 永远优先于 auto-resume。

---

## 28. Hook 策略

我已有其他：

- skills；
- plugins；
- hooks；
- superpowers；
- grill-me；
- 其他 Claude Code 配置。

所以不要覆盖 `settings.json`。

如果需要 Hook：

- 先读取现有配置；
- merge；
- 使用本工具唯一标识；
- install/uninstall 对称；
- uninstall 只删除本工具内容；
- 保留其他 hooks；
- 支持 dry-run install preview。

优先考虑 Hook 只做：

```text
SessionStart -> 提供 session_id/transcript_path 或启动 watcher
StopFailure -> 记录结构化失败/唤醒外部恢复器
```

不要指望 StopFailure 自己 `block` Claude，因为官方机制不允许。

如果完全不需要 Hook 也能实现，则优先降低侵入性。

---

## 29. Terminal/Input 注入策略

如果必须自动把 resume prompt 发回当前 Claude Code，需要比较：

- psmux targeted pane；
- Windows Console/ConPTY 可行方案；
- WScript.Shell SendKeys；
- 启动时 wrapper 持有 stdin；
- `claude --continue` 重新进入 session；
- 其他更稳定方式。

评价维度：

- 是否能精确定位 session；
- 是否依赖前台焦点；
- 多窗口安全性；
- 中文支持；
- 特殊字符；
- 管理员/普通权限；
- Claude TUI 升级兼容性；
- 是否容易误输入。

V0.1 如果没有找到可靠的自动注入方式，可以先：

```text
检测 + replay + notification
```

而将 auto-resume 标记 experimental。

不要为了“功能完整”采用明显不安全的 SendKeys。

---

## 30. 测试要求

至少写：

### Unit tests

覆盖：

- JSONL incremental reader；
- partial line；
- malformed line；
- event normalization；
- normal end；
- normal tool loop；
- API error；
- StopFailure；
- empty assistant；
- repeated empty assistant；
- tool_result 后 silent stop；
- semantic unfinished phrase；
- WAITING_USER；
- side-effect unknown；
- score threshold；
- retry counter；
- cooldown；
- circuit breaker；
- secret masking；
- provider/model switch event parsing；
- routed/direct 状态识别；
- switch-age correlation；
- A -> B -> A replay；
- stale routing config detection；
- protocol conversion failure classification。

### Fixture tests

构造最小 fixture：

```text
normal-end.jsonl
normal-tool-loop.jsonl
api-interrupted.jsonl
empty-response.jsonl
repeated-empty-response.jsonl
silent-after-tool-result.jsonl
unfinished-text-then-done.jsonl
waiting-user.jsonl
side-effect-unknown.jsonl
route-fixed-normal.jsonl
route-switch-a-b-normal.jsonl
route-switch-a-b-empty.jsonl
route-switch-a-b-a-silent.jsonl
stale-routing-config.jsonl
protocol-conversion-break.jsonl
```

### Real replay tests

对当前真实 session 做 replay，但测试输出中脱敏。

必须证明样本 A、样本 B 至少能被 detector 标记出来。

---

## 31. 当前 engine 测试环境异常要正确归因

当前开发上下文中已确认曾有：

```text
engine 测试报 13 个 PermissionError
```

并且改动前同样存在，属于 Windows 临时目录权限问题，而不是当前改动引起；detectors 测试曾达到 34/34 通过。

后续开发中：

- 不要把已存在环境失败伪装成新代码 regression；
- 也不要因为“baseline 已失败”就忽略新失败；
- 分别记录 baseline failure 与新改动 failure；
- 如果能安全修复测试临时目录使用方式，可以另列修复；
- 不要为了绿测试修改与 watchdog 无关的大量业务代码。

---

## 32. 项目目录建议

根据技术选型调整，但至少保持职责分离。例如 TypeScript 方向可考虑：

```text
src/
  cli/
  discovery/
  transcript/
  events/
  state/
  detectors/
    api-error.ts
    empty-response.ts
    repeated-empty.ts
    silent-stop.ts
    waiting-user.ts
    side-effect.ts
  scoring/
  replay/
  resume/
  provider/
  logging/
  doctor/
  config/

tests/
  fixtures/
  unit/
  replay/
```

不要把所有逻辑塞到一个脚本里。

---

## 33. 配置建议

例如：

```json
{
  "dryRun": true,
  "autoResume": false,
  "threshold": 80,
  "maxAutoResumes": 3,
  "cooldownSeconds": 10,
  "emptyResponse": {
    "enabled": true,
    "consecutiveThreshold": 2
  },
  "silentStop": {
    "enabled": true
  },
  "logging": {
    "redactSecrets": true
  }
}
```

实际字段由实现决定。

---

## 34. 不要污染现有工作流

要求：

- 不修改业务仓库无关文件；
- 不修改全局 CLAUDE.md，除非确有必要且用户明确同意；
- 不自动启用第三方插件；
- 不破坏 ccSwitch；
- 不影响官方 provider 正常使用；
- watchdog 可完全关闭/卸载；
- 默认不自启动。

---

## 35. Git 规则

允许自由执行只读 Git 操作：

```text
git status
git diff
git log
git show
```

不要执行 `git push`。

不要创建远程仓库。

不要自动 commit，除非我明确要求。

如果需要研究第三方仓库，优先 git clone 后只读分析。

---

## 36. 开发执行顺序

严格按照以下顺序推进，但不要每一步都停下来等用户：

1. 定位当前 session；
2. 定位样本 A；
3. 定位样本 B；
4. 输出初步证据；
5. 找正常 turn 对照；
6. 审查 Claude Code 当前版本/官方 hooks 行为；
7. 调研三个重点开源项目及相关 Issue；
8. 确定技术方案；
9. 创建/完善项目结构；
10. 实现 JSONL incremental reader；
11. 实现 event normalizer/state machine；
12. 实现 empty/repeated-empty detector；
13. 实现 silent-stop detector；
14. 实现 interruption score；
15. 实现 safety guard；
16. 实现 logging；
17. 实现 doctor/status；
18. 实现 replay；
19. 写 unit/fixture tests；
20. replay 当前真实 session；
21. 调整阈值降低误报；
22. 如安全可行，再实现 experimental auto-resume；
23. 跑完整测试；
24. `git diff` 检查；
25. 输出最终报告。

不要在以下阶段停止：

- “接下来我会开始开发”；
- “现在开始写测试”；
- “方案已经明确”；
- “让我先看一下测试结构”；
- “我继续推进收尾”。

如果仍有下一步且无真实 blocker，就继续执行。

---

## 37. V0.1 最低验收标准

必须实现：

- Windows 原生运行；
- 自动发现最近/当前 Claude session；
- JSONL 增量监听；
- normal end 识别；
- tool_use/tool_result 状态识别；
- obvious API error 识别；
- empty assistant response 识别；
- repeated empty response 识别；
- suspected silent interruption 识别；
- interruption score；
- WAITING_USER 识别；
- side effect safety classification；
- 防重复触发；
- retry 次数限制；
- cooldown；
- circuit breaker；
- secret-safe 日志；
- status；
- doctor；
- dry-run；
- replay；
- unit tests；
- 用当前真实 session replay 验证样本 A/B；
- ccSwitch routed/direct 状态识别（在当前环境可获取时）；
- provider/model switch history 记录（在当前环境可获取时）；
- interruption 与最近 switch 的时间关联；
- 至少完成一组固定 provider 与切换 provider 的对照 replay/fixture。

`auto-resume` 如果无法在 Windows 上安全定位当前 session，可作为 experimental，不得牺牲安全强行实现。

---

## 38. 最终报告必须包含

### A. 当前异常会话根因分析

分别分析样本 A / B，给出证据。

### B. 正常与异常事件序列对比

至少四类：normal tool loop / normal end / sample A / sample B。

### C. 开源项目调研结论

说明借鉴了什么、拒绝了什么以及原因。

### D. 工具架构

包含状态机和恢复策略。

### E. 项目目录结构

### F. 已完成代码与核心模块说明

### G. 测试结果

区分 baseline failures 和本次 regression。

### H. 当前真实 session replay 结果

类似：

```text
Sample A
Classification: ...
Score: ...
Evidence: ...

Sample B
Classification: ...
Score: ...
Evidence: ...
```

必须来自真实数据。

### I. 已知限制

### J. ccSwitch / Routing / Model Switch 专项结论

必须明确：

- ccSwitch 是否参与触发；
- Routing 是否参与触发；
- provider hot-switch 是否有时间相关性；
- model-switch 是否有时间相关性；
- routed vs direct 的异常率是否有差异；
- A -> B -> A 是否更容易复现；
- 是否存在版本 regression；
- 是否存在 stale live config；
- 是否存在 protocol conversion 问题；
- 最可能故障层在哪一层。

### K. V0.2 计划

例如：

- 更可靠的 Windows targeted input injection；
- psmux backend；
- provider reliability dashboard；
- 自动生成匿名失败 fixture；
- ccSwitch provider metadata integration；
- 更精确的 protocol anomaly detection。

---

## 39. 根因判断原则

当前我们的主要怀疑方向是：

```text
Claude Code
-> ccSwitch
-> 第三方公益站/中转
-> gateway/proxy
-> upstream provider/model
```

链路中的某层可能造成：

- SSE 提前关闭；
- empty body；
- malformed HTTP 200；
- tool_use stop reason 错误映射；
- Anthropic/OpenAI stream 格式混用；
- thinking/tool-use 内容转换丢失；
- message_stop 缺失；
- zero-content assistant；
- Claude Code agent loop 提前结束。

但**不要预设一定是公益站的锅**。

如果真实日志证明是 Claude Code 自身 agentic loop bug、Windows 行为、hook、插件或本地环境，也必须如实结论。

优先用 A/B 事实验证：同项目、同机器、同 Claude Code 版本下，官方 provider 与第三方 provider 的异常率是否明显不同。

再做 ccSwitch 隔离：

```text
同一第三方 provider direct
vs
同一第三方 provider 经 ccSwitch route
vs
route 固定 provider
vs
同 session A -> B -> A 热切换
vs
切换后新开 session
```

只有这些对照能把“上游质量问题”和“路由/切换问题”分开。

---

## 40. 参考资料（调研时重新核对最新状态）

1. CC Switch 官方仓库与 release/changelog  
   https://github.com/farion1231/cc-switch

2. CC Switch Claude Code 路由文档  
   https://github.com/farion1231/cc-switch/blob/main/docs/guides/claude-codex-routing-guide-en.md

3. CC Switch Issue #1234：第三方模型长交互输出中断/停在 `●`  
   https://github.com/farion1231/cc-switch/issues/1234

4. CC Switch Issue #6127：Routing 切回非路由 provider 后连接异常  
   https://github.com/farion1231/cc-switch/issues/6127

5. Claude Code Issue #46423：同 session model/provider switch/context 线索  
   https://github.com/anthropics/claude-code/issues/46423

6. Claude Code Hooks 官方文档  
   https://code.claude.com/docs/en/hooks

7. cheapestinference/claude-auto-retry  
   https://github.com/cheapestinference/claude-auto-retry

8. reglisseblip/claude-auto-retry-windows  
   https://github.com/reglisseblip/claude-auto-retry-windows

9. zhangfeiyang/claude-auto-retry  
   https://github.com/zhangfeiyang/claude-auto-retry

10. Claude Code GitHub Issues  
    https://github.com/anthropics/claude-code/issues

调研时以当前日期和实际仓库最新代码为准，不要依赖旧 README 或旧 Issue 结论。

---

## 41. 现在开始执行

第一步：**先定位当前 session，并找到样本 A 与样本 B 对应的真实 JSONL 证据；同时恢复异常前后的 ccSwitch provider/model/routing 时间线。**

先展示关键证据、事件序列、最近一次 provider/model switch 距离异常发生的时间，并确认异常请求实际命中了哪个 upstream。然后继续后面的调研和 V0.1 实现。

不要只做分析，不要停在方案阶段，不要因为再次出现空响应就把它当成用户意图；如果系统允许继续且没有真实 blocker，继续推进直到达到 V0.1 验收标准。
