# yonyoubot 接口文档

本文档描述当前项目中真实注册的 HTTP API。服务由 FastAPI 提供，所有业务路由统一挂载在 `/api` 前缀下。

## 基本信息

- 默认基础地址：`http://127.0.0.1:8900`
- 默认 API 前缀：`/api`
- 默认认证方式：`Authorization: Bearer <access_token>` 或 `X-API-Key: <api_key>`
- 默认响应格式：JSON
- SSE 响应类型：`text/event-stream`
- FastAPI 内置 `/docs`、`/redoc` 和 `/openapi.json` 当前未启用

## 认证规则

所有业务接口支持两种认证方式，任选其一：

1. **JWT Bearer Token** —— 用户登录后使用，适用于浏览器交互场景
2. **API Key** —— 机器对机器调用，无需登录，适用于内部系统集成

两种方式在中间件层等效，命中 API Key 后直接授予 admin 身份，跳过 JWT 校验。

启用认证中间件时（`YONYOUBOT_AUTH__ENABLED=true`），以下接口作为公开入口：

- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `GET /api/health`

### JWT Bearer Token

请求头示例：

```http
Authorization: Bearer eyJ...
```

### API Key

在配置中通过 `auth.apiKeys` 或环境变量 `YONYOUBOT_AUTH__API_KEYS` 设置允许的 key 列表。

请求头示例：

```http
X-API-Key: yb-internal-xxxxxxxx
```

配置示例（`.env`）：

```
YONYOUBOT_AUTH__API_KEYS='["yb-internal-xxxxxxxx"]'
```

或 `config.json`：

```json
"auth": {
  "apiKeys": ["yb-internal-xxxxxxxx"]
}
```

统一错误结构：

```json
{
  "error": {
    "message": "错误说明",
    "type": "invalid_request_error",
    "code": 400
  }
}
```

部分路由直接使用 FastAPI `HTTPException`，错误体可能为：

```json
{
  "detail": "错误说明"
}
```

## Auth 接口

### 登录

`POST /api/auth/login`

请求体：

```json
{
  "username": "admin",
  "password": "12345678"
}
```

响应：

```json
{
  "access_token": "access-token",
  "refresh_token": "refresh-token",
  "token_type": "bearer",
  "expires_in": 86400
}
```

常见状态码：

- `200`：登录成功
- `401`：用户名或密码错误

### 注册用户

`POST /api/auth/register`

需要管理员 token。

请求体：

```json
{
  "username": "user1",
  "password": "12345678",
  "display_name": "用户一",
  "group_id": "group-a",
  "role": "user"
}
```

响应：

```json
{
  "id": "user-id",
  "username": "user1",
  "display_name": "用户一",
  "group_id": "group-a",
  "role": "user"
}
```

常见状态码：

- `200`：注册成功
- `401`：未登录
- `403`：非管理员
- `409`：用户名已存在

### 刷新 token

`POST /api/auth/refresh`

请求体：

```json
{
  "user_id": "user-id",
  "refresh_token": "refresh-token"
}
```

响应同登录接口。刷新成功后旧 refresh token 会被撤销。

## Round 接口

术语说明：

| 术语 | 英文 | 含义 |
|------|------|------|
| round | round | 一次 agent 调用 |
| turn | turn | 一次模型调用（LLM API 请求） |
| message | message | 一次 round 最终累积出的 assistant `AgentMessage` |

一个 round 可能包含多次 turn（模型调用 → 工具执行 → 模型再调用）。每个会话在同一时间最多有一个活跃 round（状态为 `queued` 或 `running`）。round 进入 `completed` / `failed` / `cancelled` 其中之一后即为终端状态（`terminal: true`），不会再产生新事件；事件订阅会回放已有事件后关闭，取消接口会直接返回当前快照。

RoundSnapshot 结构：

```json
{
  "round_id": "round_abc123",
  "session_id": "session-id",
  "status": "running",
  "last_seq": 42,
  "terminal": false,
  "result": null,
  "error": null,
  "message": null,
  "created_at": "2026-06-17T10:00:00Z",
  "started_at": "2026-06-17T10:00:01Z",
  "finished_at": null
}
```

- `status` 取值：`"queued"` / `"running"` / `"completed"` / `"failed"` / `"cancelled"`
- `terminal`：`true` 表示 round 已结束，不会再产生新事件
- `result`：终端状态下可能包含执行结果（包含 `message`、`reason`、`usage` 等）
- `error`：`failed` 状态下包含 `{"code": "...", "message": "..."}` 错误详情
- `message`：当前已构建的 `AgentMessage`（仅当 round 有回复内容时非空），包含全部 content blocks
- `last_seq`：最后一条生命周期事件的序列号

### 创建轮次

`POST /api/sessions/{session_id}/rounds`

需要认证。请求会立即返回 RoundSnapshot，轮次在后台异步执行。

请求体：

```json
{
  "message": "你好",
  "metadata": {}
}
```

响应为 RoundSnapshot（`status` 初始为 `"running"`）。这是低层轮次接口，当前执行链路只使用 `message` 和 `metadata`；如果需要附件处理、结构化输出约束、会话自动创建和 guardrail，请使用 `/api/chat/complete` 或 `/api/chat/stream`。

常见状态码：

- `200`：创建成功，返回 RoundSnapshot
- `401`：缺少或无效 token
- `404`：会话不存在或不属于当前用户
- `409`：会话已有活跃轮次，返回 `{"error": "Active round exists", "active_round_id": "round_xxx"}`
- `503`：Round service 或 PostgreSQL session manager 未配置

### 获取轮次快照

`GET /api/rounds/{round_id}`

需要认证。返回 RoundSnapshot，包含终端状态及结果。

常见状态码：

- `200`：成功，返回 RoundSnapshot
- `401`：缺少或无效 token
- `404`：轮次不存在或不属于当前用户

### 轮次事件流

`GET /api/rounds/{round_id}/events?after_seq=0`

需要认证。认证方式支持两种：

- 请求头：`Authorization: Bearer <access_token>`
- 查询参数：`?token=<access_token>`，便于浏览器 `EventSource` 使用

返回 SSE 流。先回放 `seq > after_seq` 的已持久化事件，再订阅实时事件。轮次进入终端状态后流自动关闭。客户端断开连接**不会**取消轮次。

事件格式同 `/api/chat/stream` 中的 round 生命周期事件（`round.started`、`text.delta`、`tool_call.started`、`round.completed` 等）。完整事件类型见「流式聊天」章节。

常见状态码：

- `200`：SSE 流已建立
- `401`：缺少或无效 token
- `404`：轮次不存在或不属于当前用户

### 取消轮次

`POST /api/rounds/{round_id}/cancel`

需要认证。请求取消后台轮次并返回当前 RoundSnapshot。取消是异步生效的，活跃轮次可能先返回 `running` 快照，随后通过事件流或快照变为 `cancelled`；如果轮次已经终止，则直接返回已有终态。

常见状态码：

- `200`：取消请求已接收或轮次已是终态，返回 RoundSnapshot
- `401`：缺少或无效 token
- `404`：轮次不存在或不属于当前用户

### 获取活跃轮次

`GET /api/sessions/{session_id}/rounds/active`

需要认证。返回当前会话的活跃轮次（`queued` / `running`），没有活跃轮次时 `round` 为 `null`。

响应：

```json
{
  "round": {
    "round_id": "round_abc123",
    "session_id": "session-id",
    "status": "running",
    "last_seq": 10,
    "terminal": false,
    "result": null,
    "error": null
  }
}
```

常见状态码：

- `200`：成功，返回 `{"round": RoundSnapshot | null}`
- `401`：缺少或无效 token

### 获取会话消息

`GET /api/sessions/{session_id}/messages?limit=100`

需要认证。返回已持久化的消息列表，按创建时间升序。当前实现不会单独校验 session 存在性；会话不存在、不属于当前用户或没有消息时返回空数组。每条消息的 `message` 字段为 `AgentMessage` 结构。

响应：

```json
[
  {
    "message": {
      "id": "msg_abc123",
      "role": "user",
      "status": "completed",
      "content": [
        {"id": "blk_0", "type": "text", "order": 0, "text": "你好", "markdown": false}
      ],
      "source": "chat",
      "name": null,
      "metadata": {},
      "usage": null,
      "created_at": "2026-06-17T10:00:00Z",
      "ended_at": "2026-06-17T10:00:00Z"
    },
    "round_id": "round_abc123"
  },
  {
    "message": {
      "id": "msg_def456",
      "role": "assistant",
      "status": "completed",
      "content": [
        {"id": "blk_1", "type": "text", "order": 0, "text": "你好！有什么可以帮助你的？", "markdown": true}
      ],
      "source": null,
      "name": null,
      "metadata": {},
      "usage": {"input_tokens": 150, "output_tokens": 30, "total_tokens": 180},
      "created_at": "2026-06-17T10:00:05Z",
      "ended_at": "2026-06-17T10:00:06Z"
    },
    "round_id": "round_abc123"
  }
]
```

- `message`：`AgentMessage` 对象，结构详见下方「AgentMessage 数据模型」
- `round_id`：所属轮次 ID

常见状态码：

- `200`：成功，返回消息数组
- `401`：缺少或无效 token
- `503`：PostgreSQL session manager 未配置

## AgentMessage 数据模型

`AgentMessage` 是整个系统的核心消息结构，用于 Chat 接口的 `message` 字段、RoundSnapshot 的 `message` 字段以及会话消息的 `message` 字段。

### AgentMessage

```json
{
  "id": "msg_xxx",
  "role": "user",
  "status": "completed",
  "reason": null,
  "content": [],
  "source": "chat",
  "name": null,
  "metadata": {},
  "usage": null,
  "created_at": "2026-06-17T10:00:00Z",
  "ended_at": "2026-06-17T10:00:00Z"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 消息唯一 ID |
| `role` | `"system"` \| `"user"` \| `"assistant"` | 消息角色 |
| `status` | `"running"` \| `"completed"` \| `"failed"` \| `"interrupted"` \| `"denied"` | 消息状态；流式中 `running`，完成后变为 `completed` |
| `reason` | string \| null | 结束原因（`"done"` / `"tool_error"` / `"model_error"` / `"max_steps"` / `"structured_output"` / `"needs_help"`） |
| `content` | ContentBlock[] | 有序的内容块数组 |
| `source` | string \| null | 消息来源 |
| `name` | string \| null | 消息名称（如子 Agent 名称） |
| `metadata` | object | 扩展元数据 |
| `usage` | UsageSummary \| null | token 消耗统计 |
| `created_at` | ISO 8601 string | 创建时间 |
| `ended_at` | ISO 8601 string \| null | 结束时间 |

### ContentBlock 类型

`content` 数组包含以下类型的 block，通过 `type` 字段区分：

#### text —— 文本块

```json
{
  "id": "blk_001",
  "type": "text",
  "order": 0,
  "status": "completed",
  "text": "回复正文内容",
  "markdown": true
}
```

#### thinking —— 思考块

```json
{
  "id": "blk_002",
  "type": "thinking",
  "order": 0,
  "status": "completed",
  "text": "模型的推理过程..."
}
```

#### data —— 数据块

通过 `media_type` 区分具体数据类型。常见类型：

```json
{
  "id": "blk_003",
  "type": "data",
  "order": 1,
  "status": "completed",
  "media_type": "application/vnd.yonyoubot.canvas+json",
  "source": {
    "type": "json",
    "data": {
      "canvas_id": "canvas_xxx",
      "title": "文档标题",
      "kind": "markdown_document",
      "version_id": "ver_001",
      "version_number": 1,
      "updated_at": "2026-06-17T10:00:00Z",
      "preview": "前 240 字符预览..."
    }
  },
  "name": "文档标题",
  "metadata": {"kind": "canvas"}
}
```

`source` 支持四种类型，通过 `type` 字段区分：
- `"json"`：内联 JSON 数据（`data` 字段）
- `"url"`：外部 URL（`url` 字段）
- `"base64"`：Base64 编码数据（`data` 字段）
- `"artifact"`：制品引用（`artifact_id` 字段）

#### tool_call —— 工具调用块

```json
{
  "id": "blk_004",
  "type": "tool_call",
  "order": 2,
  "status": "completed",
  "tool_call_id": "call_001",
  "tool_name": "web_search",
  "arguments": {
    "query": "搜索关键词"
  }
}
```

#### tool_result —— 工具结果块

```json
{
  "id": "blk_005",
  "type": "tool_result",
  "order": 3,
  "status": "completed",
  "tool_call_id": "call_001",
  "tool_name": "web_search",
  "content": [
    {"id": "blk_005_text_0", "type": "text", "order": 0, "text": "工具返回的文本结果..."},
    {"id": "blk_005_data_0", "type": "data", "order": 1, "media_type": "application/vnd.yonyoubot.canvas+json", "source": {...}}
  ],
  "error": null
}
```

`tool_result.content` 只包含 `text` 和 `data` 两种子块。`error` 字段在工具执行失败时包含 `{"code": "...", "message": "..."}`。

#### structured_output 的识别

结构化输出结果以 `data` block 形式存在，通过以下特征识别：
- `media_type` 为 `"application/vnd.yonyoubot.structured-output+json"`
- 或 `metadata.kind` 为 `"structured_output"`

### 从 AgentMessage 中提取最终回复文本

`AgentMessage.content` 中各 block 按 `order` 排序，时序反映了模型的真实输出顺序：
1. 模型先输出 `thinking`（如果有）
2. 然后输出 `text`（工具调用前的说明文字）
3. 接着是 `tool_call` → `tool_result`（可能多轮）
4. 最后的 `text` block(s) 是**最终回复正文**

要获取最终回复，取最后一个 `tool_result` 之后的所有 `text` block 拼接。

## Chat 接口

聊天接口已重构为 Round 系统的薄 facade。所有聊天请求最终都通过 RoundService 创建轮次并进入后台执行。客户端断开连接**不会**取消轮次。

聊天接口支持 `application/json` 和 `multipart/form-data` 两种请求。

JSON 请求字段：

```json
{
  "message": "你好",
  "session_id": "可选，缺失时服务端自动创建",
  "wait_timeout_s": 30,
  "output_schema": {
    "type": "json",
    "name": "task_result",
    "schema": {
      "summary": "摘要示例",
      "done": true
    }
  }
}
```

multipart 请求字段：

- `message`：文本消息，可为空，但必须至少上传一个附件
- `session_id`：可选
- `output_schema`：可选，JSON 字符串
- `attachments`：可重复出现的文件字段

`wait_timeout_s` 仅支持 JSON 请求，并且只对 `/api/chat/complete` 生效。

`output_schema` 字段含义：

- `type`：结构描述模式，取值为 `"json"` 或 `"model"`
- `name`：结构化输出名称，必填；响应会原样返回到 `structured_output.name`
- `schema`：结构要求，必填；最终 `structured_output.result` 的根节点必须是 object

只要请求传入 `output_schema`，就表示本轮必须返回结构化结果。模型没有成功提交结构化结果时，本轮会失败，不会把普通文本包装成结构化成功结果。

`output_schema` 支持两种模式：

- `type: "json"`：传普通 JSON 数据样例，后端根据样例值推断结构。适合字段类型能从样例直接表达的简单场景。
- `type: "model"`：传安全版模型描述，用于精确控制必填字段、枚举、说明和部分数值/字符串约束。

模式选择建议：

| 场景 | 推荐模式 |
| --- | --- |
| 简单结构，字段类型能从值推断 | `"json"` |
| 需要枚举、description、数值或字符串约束 | `"model"` |
| 需要精确控制可选/必填字段 | `"model"` |
| 嵌套对象数组 | 两者皆可，`"json"` 更简洁，`"model"` 更精确 |

#### `type: "json"`

`type: "json"` 时，`output_schema.schema` 是一个普通 JSON object。调用方不需要写 JSON Schema，直接给一个数据样例即可。

类型推断规则：

| 样例值 | 推断结果 | 说明 |
| --- | --- | --- |
| `"hello"` | string | 字符串 |
| `123` | integer | 整数 |
| `12.5` | number | 浮点数 |
| `true` / `false` | boolean | 布尔 |
| `["a", "b"]` | array of string | 从第一个元素推断数组项类型 |
| `[]` | array | 空数组不约束元素类型 |
| `{"name": "张三", "age": 30}` | object | 递归推断嵌套对象 |
| `{}` | object | 空对象不约束子字段 |
| `null` | unconstrained optional | 字段不进入 required，类型不约束 |

示例：

```json
{
  "type": "json",
  "name": "person_info",
  "schema": {
    "name": "张三",
    "age": 30,
    "is_member": true,
    "score": 85.5,
    "tags": ["技术"],
    "note": null,
    "metadata": {}
  }
}
```

注意事项：

- 非 `null` 字段会被视为必填。
- 数组只根据第一个元素推断元素类型，混合类型数组建议使用 `"model"` 模式。
- 空数组不约束元素类型，空对象不约束子字段。
- 不支持从 `datetime` 等非 JSON 值推断类型。

#### `type: "model"`

`type: "model"` 时，`output_schema.schema` 是 JSON 形式的模型描述，不是 Python 代码。

```json
{
  "type": "model",
  "name": "task_result",
  "schema": {
    "type": "object",
    "fields": {
      "summary": {
        "type": "string",
        "required": true,
        "description": "任务摘要"
      },
      "priority": {
        "type": "enum",
        "required": false,
        "values": ["high", "medium", "low"]
      }
    }
  }
}
```

字段规则：

- 根节点必须是 `{"type": "object", "fields": {...}}`。
- `object` 通过 `fields` 描述子字段。
- `array` 通过 `items` 描述元素结构。
- 每个字段可设置 `required`；未设置时按非必填处理。
- `description` 会传给模型，帮助模型理解字段语义。
- `enum` 通过 `values` 描述候选值。

支持类型：

```text
string
integer
number
boolean
object
array
enum
```

### 非流式聊天

`POST /api/chat/complete`

此接口是 Round 系统的薄 facade：内部调用创建轮次 API，等待轮次结束后返回最终响应。客户端断开连接**不会**取消轮次。

等待超时时（默认由服务端 `request_timeout` 控制，可通过 `wait_timeout_s` 覆盖）返回 `202` 及 `round_id`，客户端可随后通过轮次事件流或轮次快照 API 获取结果。

请求示例：

```bash
# JWT Bearer Token
curl -X POST http://127.0.0.1:8900/api/chat/complete \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"总结一下这个项目"}'

# API Key（无需登录，适用于内部系统集成）
curl -X POST http://127.0.0.1:8900/api/chat/complete \
  -H "X-API-Key: yb-internal-xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"message":"总结一下这个项目"}'
```

响应格式：

```json
{
  "request_id": "req_xxx",
  "user_id": "user-id",
  "session_id": "session-id",
  "model": "deepseek-v4",
  "round_id": "round_xxx",
  "status": "completed",
  "message": {
    "id": "msg_xxx",
    "role": "assistant",
    "status": "completed",
    "reason": null,
    "content": [
      {"id": "blk_0", "type": "thinking", "order": 0, "text": "模型思考过程..."},
      {"id": "blk_1", "type": "text", "order": 1, "text": "回答内容", "markdown": true},
      {"id": "blk_2", "type": "tool_call", "order": 2, "status": "completed",
       "tool_call_id": "call_001", "tool_name": "web_search",
       "arguments": {"query": "搜索关键词"}},
      {"id": "blk_3", "type": "tool_result", "order": 3, "status": "completed",
       "tool_call_id": "call_001", "tool_name": "web_search",
       "content": [
         {"id": "blk_3_text_0", "type": "text", "order": 0, "text": "搜索结果文本..."}
       ],
       "error": null},
      {"id": "blk_4", "type": "text", "order": 4, "text": "工具调用后的最终回复。", "markdown": true}
    ],
    "source": null,
    "name": null,
    "metadata": {},
    "usage": {"input_tokens": 1500, "output_tokens": 800, "total_tokens": 2300},
    "created_at": "2026-06-17T10:00:00Z",
    "ended_at": "2026-06-17T10:00:05Z"
  },
  "reason": "done",
  "error": null,
  "usage": {
    "prompt_tokens": 1500,
    "completion_tokens": 800,
    "total_tokens": 2300
  }
}
```

- `message`：`AgentMessage` 对象，包含完整的 content blocks 数组。详见下方「AgentMessage 数据模型」
- `reason`：完成原因，取值：`"done"` / `"tool_error"` / `"model_error"` / `"max_steps"` / `"structured_output"` / `"needs_help"`
- `usage`：token 用量汇总

`AgentMessage.content` 中的 block 类型：

- `text`：Markdown 文本块（`markdown: true`），最终回复正文
- `thinking`：模型思考过程，通常默认折叠
- `data`：结构化数据块，通过 `media_type` 区分具体数据类型（如 Canvas 卡片、结构化输出等）
- `tool_call`：工具调用请求，含 `tool_name` 和 `arguments`
- `tool_result`：工具执行结果，`content` 中嵌套 `text` 或 `data` 子块，`error` 字段携带失败信息

常见状态码：

- `200`：请求完成，返回完整响应
- `202`：等待超时，轮次仍在后台运行，返回 `{"round_id": "round_xxx", "status": "running", ...}`
- `400`：请求体格式错误、空消息且无附件、附件不符合 guardrail，或 `output_schema` 不合法
- `401`：缺少或无效 token
- `404`：指定 `session_id` 不存在或不属于当前用户
- `409`：会话已有活跃轮次，返回 `{"error": "Active round exists", "active_round_id": "round_xxx"}`
- `422`：要求结构化输出但模型未提交
- `503`：Round service 或 PostgreSQL session manager 未配置

注意：客户端断开连接不会取消轮次。取消轮次请调用 `POST /api/rounds/{round_id}/cancel`。

### 流式聊天

`POST /api/chat/stream`

此接口是 Round 系统的薄 facade：内部调用创建轮次 API，然后将轮次生命周期事件以 SSE 流形式转发。客户端断开连接**不会**取消轮次。

响应为 SSE（`text/event-stream`）。第一个事件是 `round.attached`，包含 `round_id` 等轮次基本信息，随后回放并转发轮次生命周期事件。

所有事件的 `data` JSON 均包含公共字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `round_id` | string | 轮次 ID |
| `seq` | int | 事件序号（单调递增，可做去重） |
| `ts` | ISO 8601 string | 事件发生时间 |
| `reply_id` | string | 当前回复 ID |

空闲时服务端发送 SSE 注释帧保持连接：

```text
: ping
```

#### 事件类型完整参考

##### 生命周期事件

**`round.attached`** —— 流式连接建立成功，首个事件：

```text
event: round.attached
data: {"request_id":"req_xxx","user_id":"user-id","session_id":"session-id","model":"deepseek-v4","round_id":"round_abc123","status":"running","last_seq":0}
```

**`round.started`** —— 轮次开始执行：

```text
event: round.started
data: {"round_id":"round_xxx","seq":2,"ts":"2026-06-17T10:00:01Z","session_id":"sess_xxx","status":"running","last_seq":0}
```

**`round.completed`** —— 轮次成功完成，携带最终 message：

```text
event: round.completed
data: {"round_id":"round_xxx","seq":42,"ts":"2026-06-17T10:00:10Z","result":{"message":{<AgentMessage>},"usage":{"input_tokens":1500,"output_tokens":800,"total_tokens":2300},"reason":"done","status":"completed"}}
```

**`round.failed`** —— 轮次执行失败：

```text
event: round.failed
data: {"round_id":"round_xxx","seq":15,"ts":"2026-06-17T10:00:05Z","error":{"code":"model_error","message":"错误描述"},"message":"错误描述"}
```

**`round.cancelled`** —— 轮次被取消：

```text
event: round.cancelled
data: {"round_id":"round_xxx","seq":16,"ts":"2026-06-17T10:00:06Z"}
```

##### 文本内容事件

**`text.started`** → **`text.delta`**（可多次）→ **`text.ended`**：

```text
event: text.started
data: {"round_id":"round_xxx","seq":6,"ts":"...","reply_id":"reply_abc","block_id":"block_text_001","order":0}

event: text.delta
data: {"round_id":"round_xxx","seq":7,"ts":"...","reply_id":"reply_abc","block_id":"block_text_001","delta":"你好"}

event: text.delta
data: {"round_id":"round_xxx","seq":8,"ts":"...","reply_id":"reply_abc","block_id":"block_text_001","delta":"，请问有什么可以帮你的？"}

event: text.ended
data: {"round_id":"round_xxx","seq":9,"ts":"...","reply_id":"reply_abc","block_id":"block_text_001","status":"completed"}
```

##### 思考内容事件

**`thinking.started`** → **`thinking.delta`**（可多次）→ **`thinking.ended`**：

```text
event: thinking.started
data: {"round_id":"round_xxx","seq":3,"ts":"...","reply_id":"reply_abc","block_id":"block_thinking_001","order":0}

event: thinking.delta
data: {"round_id":"round_xxx","seq":4,"ts":"...","reply_id":"reply_abc","block_id":"block_thinking_001","delta":"我需要先理解用户的问题..."}

event: thinking.ended
data: {"round_id":"round_xxx","seq":5,"ts":"...","reply_id":"reply_abc","block_id":"block_thinking_001","status":"completed"}
```

##### 工具调用事件

**`tool_call.started`** → **`tool_call.delta`** → **`tool_call.ended`**：

```text
event: tool_call.started
data: {"round_id":"round_xxx","seq":10,"ts":"...","reply_id":"reply_abc","block_id":"block_tool_call_001","order":2,"tool_call_id":"call_001","tool_name":"web_search"}

event: tool_call.delta
data: {"round_id":"round_xxx","seq":11,"ts":"...","reply_id":"reply_abc","block_id":"block_tool_call_001","arguments_delta":"{\"query\":\"搜索关键词\"}"}

event: tool_call.ended
data: {"round_id":"round_xxx","seq":12,"ts":"...","reply_id":"reply_abc","block_id":"block_tool_call_001","status":"completed"}
```

##### 工具结果事件

**`tool_result.started`** → `tool_result.text` / `tool_result.data` → **`tool_result.ended`**：

```text
event: tool_result.started
data: {"round_id":"round_xxx","seq":13,"ts":"...","reply_id":"reply_abc","block_id":"block_tool_result_001","order":3,"tool_call_id":"call_001","tool_name":"web_search"}

event: tool_result.text
data: {"round_id":"round_xxx","seq":14,"ts":"...","reply_id":"reply_abc","block_id":"block_tool_result_001","text":"搜索到以下结果：..."}

event: tool_result.data
data: {"round_id":"round_xxx","seq":15,"ts":"...","reply_id":"reply_abc","block_id":"block_tool_result_001","data_block":{"id":"canvas_data","type":"data","order":1,"status":"completed","media_type":"application/vnd.yonyoubot.canvas+json","source":{"type":"json","data":{"canvas_id":"canvas_xxx","title":"文档标题","kind":"markdown_document","version_id":"ver_001","version_number":1,"preview":"预览文本..."}},"name":"文档标题","metadata":{"kind":"canvas"}}}

event: tool_result.ended
data: {"round_id":"round_xxx","seq":16,"ts":"...","reply_id":"reply_abc","block_id":"block_tool_result_001","status":"completed","error":null}
```

##### 独立数据事件

**`data.ended`** —— 非工具上下文中的数据块（较少独立使用，通常嵌套在 tool_result 中）：

```text
event: data.ended
data: {"round_id":"round_xxx","seq":20,"ts":"...","reply_id":"reply_abc","block_id":"block_data_001","order":5,"status":"completed","media_type":"application/vnd.yonyoubot.structured-output+json","source":{"type":"json","data":{...}},"name":"结构化结果","metadata":{"kind":"structured_output"}}
```

#### 事件类型汇总

| 事件类型 | 用途 |
|---------|------|
| `round.attached` | 流式连接建立，携带 round_id |
| `round.started` | 轮次开始执行 |
| `round.completed` | 轮次成功完成，携带最终 message |
| `round.failed` | 轮次执行失败 |
| `round.cancelled` | 轮次被取消 |
| `turn.started` | 一次模型调用开始（round 内可多次） |
| `turn.ended` | 一次模型调用结束 |
| `text.started` | 新文本块开始 |
| `text.delta` | 文本增量 |
| `text.ended` | 文本块完成 |
| `thinking.started` | 新思考块开始 |
| `thinking.delta` | 思考增量 |
| `thinking.ended` | 思考块完成 |
| `data.ended` | 数据块（Canvas 卡片、结构化输出等） |
| `tool_call.started` | 工具调用开始 |
| `tool_call.delta` | 工具参数增量 |
| `tool_call.ended` | 工具调用完成 |
| `tool_result.started` | 工具结果开始 |
| `tool_result.text` | 工具结果文本（完整内容，非增量） |
| `tool_result.data` | 工具结果数据块（Canvas 等） |
| `tool_result.ended` | 工具结果完成 |

#### 模型调用生命周期事件（Turn 级别）

一个 round 内部可能包含多次模型调用（LLM API 请求），每次调用通过 `turn.started` / `turn.ended` 事件标识。注意这里的 `turn` 是模型调用粒度的术语，与 public API 的 round 层 term `round_id` 不同。

**`turn.started`** —— 一次模型调用开始：

```text
event: turn.started
data: {"round_id":"round_xxx","turn_id":"turn_001","seq":17,"ts":"...","session_id":"sess_xxx","status":"running"}
```

**`turn.ended`** —— 一次模型调用结束：

```text
event: turn.ended
data: {"round_id":"round_xxx","turn_id":"turn_001","seq":33,"ts":"...","session_id":"sess_xxx","status":"completed"}
```

- `turn_id`：模型调用级别的唯一标识（区别于 round 级别的 `round_id`）
- round 内的多次 turn 可通过 `round_id` 关联，`turn_id` 在模型粒度区分每次 LLM 请求

常见状态码：

- `200`：请求已进入流式处理
- `400`：请求体格式错误、空消息且无附件、附件不符合 guardrail，或 `output_schema` 不合法
- `401`：缺少或无效 token
- `404`：指定 `session_id` 不存在或不属于当前用户
- `409`：会话已有活跃轮次，返回 `{"error": "Active round exists", "active_round_id": "round_xxx"}`
- `503`：Round service 或 PostgreSQL session manager 未配置

注意：客户端断开连接不会导致错误状态码——流继续在后台执行。取消轮次请调用 `POST /api/rounds/{round_id}/cancel`。流式接口不会在模型未提交结构化结果时把 HTTP 响应改成 `422`；此类结果会随 `round.completed` / `round.failed` 等事件体现，客户端需要检查事件内容。

结构化输出相关错误示例：

请求阶段发现 `output_schema` 不合法时返回 `400`：

```json
{
  "error": {
    "message": "All keys in the example must be non-empty strings",
    "type": "invalid_request_error",
    "code": 400
  }
}
```

非流式接口请求带 `output_schema`，但模型没有成功提交结构化结果时返回 `422`：

```json
{
  "error": {
    "message": "Structured output was required but not submitted",
    "type": "validation_error",
    "code": 422
  }
}
```

## 从响应中提取内容

无论是非流式接口（`POST /api/chat/complete`、`GET /api/rounds/{round_id}`）还是流式 SSE 事件，最终回复内容都通过 `AgentMessage.content` 数组承载。本章说明如何从这个数组中提取各类内容。

### 获取最终文本回复

`AgentMessage.content` 中的 `text` block 按 `order` 排序。模型的回复可能穿插工具调用，最后一组 `text` block（最后一个 `tool_result` 之后的所有 `text`）即为最终回复正文。

**非流式**：直接从 `round.completed.result.message.content` 或 `ChatCompleteResponse.message.content` 中取最后出现的 `type: "text"` block(s)，拼接其 `text` 字段。

**流式**：监听 SSE 事件 `text.delta`，累积当前 `block_id` 的 `delta` 增量。`text.ended` 时该 block 完成。取最后一组 `text` block。

### 获取工具调用

遍历 `content`，筛选 `type: "tool_call"` 的 block：

```json
{
  "id": "blk_004",
  "type": "tool_call",
  "order": 2,
  "status": "completed",
  "tool_call_id": "call_001",
  "tool_name": "web_search",
  "arguments": { "query": "搜索关键词" }
}
```

- `tool_name`：被调用的工具名
- `arguments`：模型传入的工具参数
- `tool_call_id`：与下方 `tool_result` 的 `tool_call_id` 对应

**流式**：监听 `tool_call.started` → `tool_call.delta`（`arguments_delta` 增量）→ `tool_call.ended`。

工具执行结果在 `type: "tool_result"` 的 block 中：

```json
{
  "id": "blk_005",
  "type": "tool_result",
  "order": 3,
  "status": "completed",
  "tool_call_id": "call_001",
  "tool_name": "web_search",
  "content": [
    { "type": "text", "text": "搜索结果文本..." },
    { "type": "data", "media_type": "application/vnd.yonyoubot.canvas+json", ... }
  ],
  "error": null
}
```

### 获取结构化输出

结构化输出以 `data` block 的形式出现在 `content` 中。通过 `media_type` 或 `metadata.kind` 识别：

```json
{
  "id": "blk_xxx",
  "type": "data",
  "order": 5,
  "status": "completed",
  "media_type": "application/vnd.yonyoubot.structured-output+json",
  "source": {
    "type": "json",
    "data": {
      "summary": "任务摘要",
      "done": true
    }
  },
  "name": "task_result",
  "metadata": { "kind": "structured_output" }
}
```

**识别特征**：`media_type == "application/vnd.yonyoubot.structured-output+json"` 或 `metadata.kind == "structured_output"`。

**提取方式**：

- **非流式**：遍历 `message.content`，找到匹配的 `data` block，读取 `source.data` 即为结构化结果。注意结构化输出通常在 `ToolResultBlock.content` 中嵌套（由 `submit_structured_output` 工具产生）。
- **流式**：监听 `tool_result.data` 事件，检查 `data_block.media_type` 是否匹配。也可在收到 `round.completed` 后从 `result.message.content` 中提取。

**查找辅助逻辑**（伪代码）：

```text
function findStructuredOutputs(message):
  for block in message.content:
    if block.type == "tool_result":
      for child in block.content:
        if child.type == "data" and (
           child.media_type == "application/vnd.yonyoubot.structured-output+json" or
           child.metadata?.kind == "structured_output"
        ):
          yield { name: child.name, result: child.source.data }
    // 也可能出现在顶层的 data block
    if block.type == "data" and (
       block.media_type == "application/vnd.yonyoubot.structured-output+json" or
       block.metadata?.kind == "structured_output"
    ):
      yield { name: block.name, result: block.source.data }
```

### 获取 Canvas 文档内容

Canvas 文档的获取分两步：先从 `message.content` 中找到 Canvas 卡片（获取元数据和预览），再通过 Canvas API 获取完整内容。

#### 第一步：找到 Canvas 卡片

在 `message.content` 中找到 `media_type` 为 `canvas+json` 的 `data` block：

```json
{
  "type": "data",
  "media_type": "application/vnd.yonyoubot.canvas+json",
  "source": {
    "type": "json",
    "data": {
      "canvas_id": "canvas_abc123",
      "title": "预算报告",
      "kind": "markdown_document",
      "version_id": "ver_001",
      "version_number": 3,
      "updated_at": "2026-06-17T10:00:00Z",
      "preview": "前 240 字符预览..."
    }
  },
  "name": "预算报告",
  "metadata": { "kind": "canvas" }
}
```

**识别特征**：`media_type == "application/vnd.yonyoubot.canvas+json"` 或 `metadata.kind == "canvas"`。

Canvas 卡片数据通常嵌套在 `ToolResultBlock.content` 中（由 `create_canvas`、`update_canvas`、`read_canvas` 等工具产生）。

**非流式**：遍历 `message.content`，对每个 `tool_result` 检查其 `content` 中的 `data` block。

**流式**：监听 `tool_result.data` 事件，检查 `data_block.media_type`。

`source.data` 中的 `canvas_id` 是后续操作的关键标识。

#### 第二步：获取 Canvas 完整内容

用 `canvas_id` 调用 Canvas API：

```bash
# 获取当前版本（含完整 Markdown 内容）
GET /api/canvases/{canvas_id}/versions/current
```

返回 `CanvasVersionResponse`，包含完整 `content` 字段：

```json
{
  "canvas_id": "canvas_abc123",
  "title": "预算报告",
  "kind": "markdown_document",
  "version_id": "ver_001",
  "version_number": 3,
  "updated_at": "2026-06-17T10:00:00Z",
  "preview": "前 240 字符预览...",
  "content": "# 预算报告\n\n## 一、收入预算\n\n..."
}
```

也可获取历史版本：

```bash
GET /api/canvases/{canvas_id}/versions/{version_id}
```

#### 第三步（可选）：导出为文件

```bash
# 导出为 Markdown / docx / pdf
GET /api/canvases/{canvas_id}/download?format=md
GET /api/canvases/{canvas_id}/download?format=docx
GET /api/canvases/{canvas_id}/download?format=pdf
```

### 查找辅助伪代码汇总

```text
// 获取最终文本回复
function getFinalText(message):
  blocks = message.content.filter(b -> b.type == "text")
  return blocks.map(b -> b.text).join("")

// 获取所有工具调用
function getToolCalls(message):
  return message.content.filter(b -> b.type == "tool_call")

// 获取结构化输出
function getStructuredOutputs(message):
  // 遍历顶层和 ToolResultBlock.content 中的 data block
  // 匹配 media_type 或 metadata.kind

// 获取 Canvas 卡片
function getCanvasCards(message):
  // 遍历 ToolResultBlock.content 中的 data block
  // 匹配 media_type 或 metadata.kind
  // 返回 source.data.canvas_id 列表

// 获取 Canvas 完整内容
async function getCanvasContent(canvasId):
  response = await fetch(`/api/canvases/${canvasId}/versions/current`)
  return response.content
```

## Session 与当前用户接口

### 获取当前用户

`GET /api/users/me`

响应：

```json
{
  "id": "user-id",
  "group_id": "group-a",
  "role": "user"
}
```

### 获取当前用户会话列表

`GET /api/users/me/sessions`

响应：

```json
[
  {
    "id": "session-id",
    "title": "会话标题",
    "updated_at": "2026-05-19T10:00:00Z"
  }
]
```

### 创建当前用户会话

`POST /api/users/me/sessions`

成功状态码为 `201`。

响应：

```json
{
  "id": "session-id",
  "title": null,
  "updated_at": "2026-05-19T10:00:00Z"
}
```

### 获取当前用户记忆

`GET /api/users/me/memory`

响应：

```json
[
  {
    "key": "preferences",
    "value": "{}"
  }
]
```

具体字段取决于 memory store 的实现。

### 订阅会话后台事件

`GET /api/sessions/{session_id}/events`

用于接收当前会话的后台事件流（包括其他会话发起的新 turn 和子 Agent 事件）。

认证方式支持两种：

- 请求头：`Authorization: Bearer <access_token>`
- 查询参数：`?token=<access_token>` 或 `?api_key=<api_key>`，便于浏览器 `EventSource` 使用（EventSource 无法设置自定义请求头）

响应为 SSE（`text/event-stream`）。发送的事件类型与 `/api/chat/stream` 完全一致，但额外包含 `user_id` 和 `session_id` 字段。所有事件类型同上方的「事件类型汇总」。

子 Agent 事件同样通过此通道发送，payload 中包含 `sub_id` 和 `parent_turn_id` 字段标识为子 Agent 事件，可据此分流到独立的子 Agent 日志面板：

```text
event: round.started
data: {"user_id":"user-id","session_id":"session-id","round_id":"sub_round_xxx","seq":1,"ts":"...","sub_id":"sub_agent_001","parent_turn_id":"parent_round_xxx"}

event: tool_call.started
data: {"user_id":"user-id","session_id":"session-id","round_id":"sub_round_xxx","seq":2,"ts":"...","tool_name":"read_file","sub_id":"sub_agent_001","parent_turn_id":"parent_round_xxx"}

event: tool_result.ended
data: {"user_id":"user-id","session_id":"session-id","round_id":"sub_round_xxx","seq":3,"ts":"...","tool_name":"read_file","status":"completed","sub_id":"sub_agent_001","parent_turn_id":"parent_round_xxx"}

event: round.completed
data: {"user_id":"user-id","session_id":"session-id","round_id":"sub_round_xxx","seq":4,"ts":"...","sub_id":"sub_agent_001","parent_turn_id":"parent_round_xxx"}
```

常见状态码：

- `200`：SSE 流已建立
- `401`：缺少或无效 token
- `404`：会话不存在或不属于当前用户
- `503`：PostgreSQL session manager 未配置

## 文件与产物下载接口

### 下载 session sandbox 文件

`GET /api/sessions/{session_id}/files/{file_path}`

用于下载当前用户会话 sandbox 中的文件。服务端会校验 session 归属和路径逃逸。

常见状态码：

- `200`：返回文件
- `403`：路径逃逸
- `404`：会话或文件不存在
- `410`：session sandbox 已过期
- `503`：PostgreSQL session manager 未配置

### 下载 artifact

`GET /api/artifacts/{artifact_id}/download`

用于下载 runtime 注册过的 artifact。

常见状态码：

- `200`：返回文件
- `401`：缺少 token
- `403`：artifact 不属于当前用户
- `404`：artifact 不存在
- `410`：artifact 记录过期或文件已不可用

## Canvas 接口

Canvas 是系统内的持久化可编辑 Markdown 文档。Agent 可通过 `create_canvas`、`update_canvas`、`read_canvas` 工具操作 Canvas，前端可通过以下接口读取和编辑。

Canvas 数据在 SSE 事件流中以 `data` block 形式出现，`media_type` 为 `"application/vnd.yonyoubot.canvas+json"`。

### Canvas 卡片载荷（CanvasCardPayload）

出现在事件流和工具结果中，包含 Canvas 元数据和预览：

```json
{
  "canvas_id": "canvas_abc123",
  "title": "预算报告",
  "kind": "markdown_document",
  "version_id": "ver_001",
  "version_number": 3,
  "updated_at": "2026-06-17T10:00:00Z",
  "preview": "前 240 字符预览..."
}
```

- `kind`：当前只有 `"markdown_document"`
- `preview`：内容的前 240 字符，用于卡片预览

### Canvas 版本（CanvasVersionResponse）

继承 CanvasCardPayload 全部字段，额外包含完整内容：

```json
{
  "canvas_id": "canvas_abc123",
  "title": "预算报告",
  "kind": "markdown_document",
  "version_id": "ver_001",
  "version_number": 3,
  "updated_at": "2026-06-17T10:00:00Z",
  "preview": "前 240 字符预览...",
  "content": "# 预算报告\n\n## 一、收入预算\n\n..."
}
```

### 获取 Canvas 元数据

`GET /api/canvases/{canvas_id}`

需要认证。返回 `CanvasCardPayload`，不包含完整内容。

### 获取 Canvas 当前版本（含完整内容）

`GET /api/canvases/{canvas_id}/versions/current`

需要认证。返回 `CanvasVersionResponse`，包含完整 `content`。

### 获取 Canvas 指定版本

`GET /api/canvases/{canvas_id}/versions/{version_id}`

需要认证。返回 `CanvasVersionResponse`。

### 保存 Canvas 新版本

`POST /api/canvases/{canvas_id}/versions`

需要认证。用于前端编辑 Canvas 后保存。

请求体：

```json
{
  "content": "# 修改后的完整 Markdown 内容",
  "expected_version_id": "ver_001",
  "change_summary": "更新了收入预算章节",
  "force": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `content` | string | 是 | 完整的 Markdown 内容（非增量） |
| `expected_version_id` | string \| null | 否 | 期望的基础版本 ID，用于乐观锁冲突检测 |
| `change_summary` | string \| null | 否 | 变更说明 |
| `force` | bool | 否 | 为 `true` 时忽略版本冲突强制保存 |

返回 `CanvasVersionResponse`。版本冲突时（`expected_version_id` 与服务端当前版本不一致且 `force` 不为 `true`）返回 `409`。

常见状态码：

- `200`：保存成功，返回新版本
- `400`：参数错误（如空内容）
- `401`：缺少或无效 token
- `404`：Canvas 不存在
- `409`：版本冲突（`expected_version_id` 不匹配），返回 `{"error": {"type": "version_conflict", "message": "Canvas version conflict. Current version: ver_002"}}`
- `503`：Canvas service 未配置

### 列出会话的 Canvas

`GET /api/sessions/{session_id}/canvases`

需要认证。返回 `CanvasMetadataResponse[]`。

### 导出 / 下载 Canvas

`GET /api/canvases/{canvas_id}/download?format=md`

需要认证。

format 取值：

- `md` —— 原始 Markdown（`text/markdown`）
- `docx` —— Word 文档（`application/vnd.openxmlformats-officedocument.wordprocessingml.document`）
- `pdf` —— PDF 文档（`application/pdf`）

响应为文件下载，`Content-Disposition` 头包含文件名。

常见状态码：

- `200`：返回文件
- `400`：不支持的 format
- `401`：缺少或无效 token
- `404`：Canvas 不存在

## 知识库接口

知识库可见性：

- `private`：仅 owner 可访问
- `group`：同组用户可访问
- `public`：所有登录用户可访问

### 列出可访问知识库

`GET /api/knowledge-bases`

响应：

```json
[
  {
    "kb_id": "kb-id",
    "name": "项目资料",
    "visibility": "private",
    "lifecycle": "persistent",
    "owner_id": "user-id",
    "group_id": null,
    "created_at": "2026-05-19T10:00:00Z",
    "last_accessed_at": "2026-05-19T10:00:00Z"
  }
]
```

### 创建知识库

`POST /api/knowledge-bases`

请求体：

```json
{
  "name": "项目资料",
  "visibility": "private",
  "group_id": null
}
```

响应为创建后的知识库对象，状态码 `201`。

### 重命名知识库

`PATCH /api/knowledge-bases/{kb_id}`

请求体沿用创建知识库的 schema，但当前实现只使用 `name` 字段：

```json
{
  "name": "新的知识库名称",
  "visibility": "private",
  "group_id": null
}
```

### 删除知识库

`DELETE /api/knowledge-bases/{kb_id}`

成功返回 `204 No Content`。

### 搜索知识库

`POST /api/knowledge-bases/search`

请求体：

```json
{
  "query": "检索问题",
  "owners": ["user-id"],
  "kb_ids": ["kb-id"],
  "file_id": "file-id",
  "top_k": 10
}
```

响应：

```json
{
  "items": [
    {
      "kb_id": "kb-id",
      "kb_name": "项目资料",
      "visibility": "private",
      "owner_id": "user-id",
      "group_id": null,
      "chunk_id": "chunk-id",
      "chunk_text": "命中的文本片段",
      "score": 0.91,
      "file_id": "file-id",
      "filename": "需求文档.pdf"
    }
  ]
}
```

### 列出知识库文件

`GET /api/knowledge-bases/{kb_id}/files`

响应：

```json
[
  {
    "file_id": "file-id",
    "filename": "需求文档.pdf",
    "content_type": "application/pdf",
    "size": 1024,
    "sha256": "hex",
    "created_at": "2026-05-19T10:00:00Z",
    "chunk_count": 12,
    "status": "ready",
    "preview_text": "预览文本",
    "error_message": null
  }
]
```

### 上传知识库文件

`POST /api/knowledge-bases/{kb_id}/files`

请求类型：`multipart/form-data`

字段：

- `attachments`：可重复的文件字段

示例：

```bash
curl -X POST http://127.0.0.1:8900/api/knowledge-bases/$KB_ID/files \
  -H "Authorization: Bearer $TOKEN" \
  -F "attachments=@需求文档.pdf" \
  -F "attachments=@会议纪要.docx"
```

响应：

```json
{
  "file_ids": ["file-id-1", "file-id-2"]
}
```

### 删除知识库文件

`DELETE /api/knowledge-bases/{kb_id}/files/{file_id}`

成功返回 `204 No Content`。

## 管理员接口

以下接口都需要管理员 token。

### 用户列表

`GET /api/admin/users`

响应：

```json
[
  {
    "id": "user-id",
    "username": "user1",
    "display_name": "用户一",
    "group_id": "group-a",
    "role": "user",
    "is_active": true,
    "created_at": "2026-05-19T10:00:00Z"
  }
]
```

### 创建用户

`POST /api/admin/users`

请求体：

```json
{
  "username": "user1",
  "password": "12345678",
  "display_name": "用户一",
  "group_id": "group-a",
  "role": "user"
}
```

响应为创建后的用户对象，状态码 `201`。

### 更新用户

`PATCH /api/admin/users/{user_id}`

请求体：

```json
{
  "display_name": "新名称",
  "group_id": "group-b",
  "role": "group_admin",
  "is_active": true
}
```

禁用用户时，服务端会撤销该用户所有 refresh token。

### 删除用户

`DELETE /api/admin/users/{user_id}`

成功返回 `204 No Content`。

### 重置用户密码

`POST /api/admin/users/{user_id}/reset-password`

请求体：

```json
{
  "new_password": "new-password"
}
```

成功返回 `204 No Content`，并撤销该用户所有 refresh token。

### 用户组列表

`GET /api/admin/groups`

响应：

```json
[
  {
    "id": "group-a",
    "name": "A 组",
    "config_override": {},
    "tool_whitelist": ["web_search", "knowledge_search"],
    "user_count": 3
  }
]
```

### 创建用户组

`POST /api/admin/groups`

请求体：

```json
{
  "id": "group-a",
  "name": "A 组",
  "config_override": {
    "knowledge_base_ids": ["kb-id"]
  },
  "tool_whitelist": ["web_search", "knowledge_search"]
}
```

响应为创建后的用户组对象，状态码 `201`。

### 更新用户组

`PATCH /api/admin/groups/{group_id}`

请求体：

```json
{
  "name": "A 组新名称",
  "config_override": {},
  "tool_whitelist": ["knowledge_search"]
}
```

### 删除用户组

`DELETE /api/admin/groups/{group_id}`

成功返回 `204 No Content`。

## 健康检查

`GET /api/health`

响应：

```json
{
  "status": "ok"
}
```

## 接入建议

1. 登录后缓存 `access_token` 和 `refresh_token`，普通业务请求只带 `access_token`。
2. `POST /api/chat/complete` 缺失 `session_id` 时会创建新会话，响应里的 `session_id` 应保存给后续请求。
3. 浏览器原生 `EventSource` 无法设置自定义请求头，可使用 `/api/sessions/{session_id}/events?token=...` 订阅后台会话事件，或使用 `/api/rounds/{round_id}/events?token=...` 恢复轮次事件。
4. 文件上传统一使用 `attachments` 字段，不再兼容旧的 `images`、`media` 或其他上传字段名。
5. 如果启用了知识库能力，必须先配置 PostgreSQL + pgvector、embedding API，并执行 Alembic migration。
