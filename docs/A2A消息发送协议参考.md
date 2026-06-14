# A2A 消息发送协议参考

## 1. 协议概述

A2A（Agent-to-Agent）消息发送在集中模式下支持两种协议绑定：

| 协议 | 说明 |
|---|---|
| **HTTP+JSON (REST)** | URL + 端点路径，裸 JSON 请求体 |
| **JSONRPC** | 单一 URL，请求体包裹 JSON-RPC 2.0 外壳 |

协议由 AgentCard 的 `supportedInterfaces[].protocolBinding` 决定。

---

## 2. 流式 vs 非流式判定

需同时满足两个条件才走流式：
- `ClientConfig.streaming == True`
- `AgentCard.capabilities.streaming == True`

调度位置：`a2a/client/base_client.py:70`

---

## 3. 请求体结构（SendMessageRequest）

```json
{
  "message": {
    "messageId": "<uuid>",
    "role": "ROLE_AGENT",
    "parts": [
      { "text": "任务描述文本", "mediaType": "" }
    ],
    "contextId": "<execution_context_id>",
    "metadata": {
      "<TASK-T URI>": "<结构化 TASK-T prompt>"
    }
  },
  "configuration": {
    "acceptedOutputModes": [],
    "returnImmediately": false
  },
  "tenant": ""
}
```

### Part 字段说明

`Part` 是 A2A protobuf 定义的消息内容单元，字段如下：

| 字段 | 类型 | 说明 |
|---|---|---|
| `text` | `string` | 文本内容 |
| `raw` | `bytes` | 二进制内容 |
| `url` | `string` | 文件 URL |
| `data` | `Value` | 结构化数据（JSON） |
| `metadata` | `Struct` | 元数据 |
| `filename` | `string` | 文件名 |
| `mediaType` | `string` | **MIME 类型**（`text/plain`、`text/markdown`、`application/json` 等），缺省为空字符串 `""` |

> `mediaType` 是 A2A protobuf `Part` 的自带字段（字段号 7），SDK 中 `new_text_part()` 创建文本 Part 时默认传空字符串。

---

## 4. HTTP+JSON (REST) 协议

### 非流式

```
POST {url}/message:send
Content-Type: application/json
```

**请求体：**

```json
{
  "message": {
    "messageId": "550e8400-e29b-41d4-a716-446655440000",
    "role": "ROLE_AGENT",
    "parts": [
      { "text": "对 xxx 进行故障诊断...", "mediaType": "" }
    ],
    "contextId": "exec-ctx-abc123"
  },
  "configuration": {
    "acceptedOutputModes": [],
    "returnImmediately": false
  }
}
```

**curl 示例：**

```bash
curl -X POST http://127.0.0.1:26335/a2a/json/message:send \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "messageId": "550e8400-e29b-41d4-a716-446655440000",
      "role": "ROLE_AGENT",
      "parts": [{"text": "对 xxx 进行故障诊断...", "mediaType": ""}],
      "contextId": "exec-ctx-abc123"
    },
    "configuration": {
      "acceptedOutputModes": [],
      "returnImmediately": false
    }
  }'
```

**响应：**

```json
{
  "task": {
    "id": "task-xxx",
    "contextId": "exec-ctx-abc123",
    "status": { "state": "TASK_STATE_COMPLETED" },
    "artifacts": [
      {
        "artifactId": "...",
        "parts": [
          { "text": "诊断结果：...", "mediaType": "" }
        ]
      }
    ]
  }
}
```

### 流式

```
POST {url}/message:stream
Accept: text/event-stream
Content-Type: application/json
```

**请求体：** 同上（与非流式完全一致）

**curl 示例：**

```bash
curl -X POST http://127.0.0.1:26335/a2a/json/message:stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "message": {
      "messageId": "550e8400-e29b-41d4-a716-446655440000",
      "role": "ROLE_AGENT",
      "parts": [{"text": "对 xxx 进行故障诊断...", "mediaType": ""}],
      "contextId": "exec-ctx-abc123"
    },
    "configuration": {
      "acceptedOutputModes": [],
      "returnImmediately": false
    }
  }'
```

**响应（SSE 事件流）：**

```
data: {"task": {"id": "task-xxx", "status": {"state": "TASK_STATE_WORKING"}, ...}}
data: {"artifactUpdate": {"artifact": {"parts": [{"text": "正在分析中...", "mediaType": ""}]}}}
data: {"task": {"id": "task-xxx", "status": {"state": "TASK_STATE_COMPLETED"}, "artifacts": [...]}}
```

---

## 5. JSONRPC 协议

### 非流式

```
POST {url}
Content-Type: application/json
```

**请求体：**

```json
{
  "jsonrpc": "2.0",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "550e8400-e29b-41d4-a716-446655440000",
      "role": "ROLE_AGENT",
      "parts": [
        { "text": "对 xxx 进行故障诊断...", "mediaType": "" }
      ],
      "contextId": "exec-ctx-abc123"
    },
    "configuration": {
      "acceptedOutputModes": [],
      "returnImmediately": false
    }
  },
  "id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**curl 示例：**

```bash
curl -X POST http://127.0.0.1:26335/a2a/v1 \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "550e8400-e29b-41d4-a716-446655440000",
        "role": "ROLE_AGENT",
        "parts": [{"text": "对 xxx 进行故障诊断...", "mediaType": ""}],
        "contextId": "exec-ctx-abc123"
      },
      "configuration": {
        "acceptedOutputModes": [],
        "returnImmediately": false
      }
    },
    "id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

**响应：**

```json
{
  "jsonrpc": "2.0",
  "result": {
    "task": {
      "id": "task-xxx",
      "contextId": "exec-ctx-abc123",
      "status": { "state": "TASK_STATE_COMPLETED" },
      "artifacts": [
        {
          "artifactId": "...",
          "parts": [
            { "text": "诊断结果：...", "mediaType": "" }
          ]
        }
      ]
    }
  },
  "id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### 流式

```
POST {url}
Accept: text/event-stream
Content-Type: application/json
```

**请求体：**

```json
{
  "jsonrpc": "2.0",
  "method": "SendStreamingMessage",
  "params": {
    "message": {
      "messageId": "550e8400-e29b-41d4-a716-446655440000",
      "role": "ROLE_AGENT",
      "parts": [
        { "text": "对 xxx 进行故障诊断...", "mediaType": "" }
      ],
      "contextId": "exec-ctx-abc123"
    },
    "configuration": {
      "acceptedOutputModes": [],
      "returnImmediately": false
    }
  },
  "id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**curl 示例：**

```bash
curl -X POST http://127.0.0.1:26335/a2a/v1 \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "SendStreamingMessage",
    "params": {
      "message": {
        "messageId": "550e8400-e29b-41d4-a716-446655440000",
        "role": "ROLE_AGENT",
        "parts": [{"text": "对 xxx 进行故障诊断...", "mediaType": ""}],
        "contextId": "exec-ctx-abc123"
      },
      "configuration": {
        "acceptedOutputModes": [],
        "returnImmediately": false
      }
    },
    "id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

**响应（SSE 事件流）：**

```
data: {"jsonrpc": "2.0", "result": {"task": {"id": "task-xxx", "status": {"state": "TASK_STATE_WORKING"}, ...}}, "id": "..."}
data: {"jsonrpc": "2.0", "result": {"artifactUpdate": {"artifact": {"parts": [{"text": "正在分析中...", "mediaType": ""}]}}}, "id": "..."}
data: {"jsonrpc": "2.0", "result": {"task": {"id": "task-xxx", "status": {"state": "TASK_STATE_COMPLETED"}, "artifacts": [...]}}, "id": "..."}
```

---

## 6. Agent 实例

### 6.1 SPN Domain Agent

| 属性 | 值 |
|---|---|
| Agent 名称 | `SPN Domain Agent` |
| 流式支持 | `true` |
| TASK-T 扩展 | 已启用 `uri: https://projects.tmforum.org/.../Task-T/v1` |
| 认证 | `Bearer`（登录获取 accessSession） |

#### AgentCard — 支持的接口

```json
{
  "supportedInterfaces": [
    {
      "protocolBinding": "JSONRPC",
      "url": "http://127.0.0.1:26335/a2a/v1",
      "protocolVersion": "1.0"
    },
    {
      "protocolBinding": "HTTP+JSON",
      "url": "http://127.0.0.1:26335/a2a/json",
      "protocolVersion": "1.0"
    }
  ]
}
```

#### HTTP+JSON，流式

```
POST http://127.0.0.1:26335/a2a/json/message:stream
Accept: text/event-stream
Content-Type: application/json
Authorization: Bearer <accessSession>
A2A-Extensions: https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1
```

```json
{
  "message": {
    "messageId": "d4f1a2b3-c5e6-7890-abcd-ef1234567890",
    "role": "ROLE_AGENT",
    "parts": [],
    "contextId": "exec-spn-20250101-001",
    "metadata": {
      "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1": "## Task Type\nSPN专线投诉诊断\n## Task Description\n..."
    }
  },
  "configuration": {
    "acceptedOutputModes": [],
    "returnImmediately": false
  }
}
```

**curl：**

```bash
curl -X POST http://127.0.0.1:26335/a2a/json/message:stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "Authorization: Bearer <accessSession>" \
  -H "A2A-Extensions: https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1" \
  -d '{
    "message": {
      "messageId": "d4f1a2b3-c5e6-7890-abcd-ef1234567890",
      "role": "ROLE_AGENT",
      "parts": [],
      "contextId": "exec-spn-20250101-001",
      "metadata": {
        "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1": "## Task Type\nSPN专线投诉诊断\n## Task Description\n..."
      }
    },
    "configuration": {
      "acceptedOutputModes": [],
      "returnImmediately": false
    }
  }'
```

> **注意**：SPN Agent 启用了 TASK-T 扩展，消息文本通过 `message.metadata` 中的 TASK-T URI 字段传递，`parts[].text` 为空。

#### JSONRPC，流式

```
POST http://127.0.0.1:26335/a2a/v1
Accept: text/event-stream
Content-Type: application/json
Authorization: Bearer <accessSession>
A2A-Extensions: https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1
```

```json
{
  "jsonrpc": "2.0",
  "method": "SendStreamingMessage",
  "params": {
    "message": {
      "messageId": "d4f1a2b3-c5e6-7890-abcd-ef1234567890",
      "role": "ROLE_AGENT",
      "parts": [],
      "contextId": "exec-spn-20250101-001",
      "metadata": {
        "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1": "## Task Type\nSPN专线投诉诊断\n## Task Description\n..."
      }
    },
    "configuration": {
      "acceptedOutputModes": [],
      "returnImmediately": false
    }
  },
  "id": "d4f1a2b3-c5e6-7890-abcd-ef1234567890"
}
```

**curl：**

```bash
curl -X POST http://127.0.0.1:26335/a2a/v1 \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "Authorization: Bearer <accessSession>" \
  -H "A2A-Extensions: https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1" \
  -d '{
    "jsonrpc": "2.0",
    "method": "SendStreamingMessage",
    "params": {
      "message": {
        "messageId": "d4f1a2b3-c5e6-7890-abcd-ef1234567890",
        "role": "ROLE_AGENT",
        "parts": [],
        "contextId": "exec-spn-20250101-001",
        "metadata": {
          "https://projects.tmforum.org/a2aproject/telecommunication/extensions/Task-T/v1": "## Task Type\nSPN专线投诉诊断\n## Task Description\n..."
        }
      },
      "configuration": {
        "acceptedOutputModes": [],
        "returnImmediately": false
      }
    },
    "id": "d4f1a2b3-c5e6-7890-abcd-ef1234567890"
  }'
```

---

### 6.2 Workbench Platform Agent

| 属性 | 值 |
|---|---|
| Agent 名称 | `Workbench Platform Agent` |
| 流式支持 | `true` |
| TASK-T 扩展 | 未启用 |
| 认证 | `Bearer`（OAuth2 Password Grant 获取 access_token，通过 `fmind-auth` 头部认证） |

#### AgentCard — 支持的接口

```json
{
  "supportedInterfaces": [
    {
      "protocolBinding": "JSONRPC",
      "url": "http://127.0.0.1:26336/a2a/v1",
      "protocolVersion": "1.0"
    },
    {
      "protocolBinding": "HTTP+JSON",
      "url": "http://127.0.0.1:26336/a2a/json",
      "protocolVersion": "1.0"
    }
  ]
}
```

#### HTTP+JSON，流式

```
POST http://127.0.0.1:26336/a2a/json/message:stream
Accept: text/event-stream
Content-Type: application/json
fmind-auth: Bearer <access_token>
```

```json
{
  "message": {
    "messageId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "role": "ROLE_AGENT",
    "parts": [
      { "text": "## Task Type\n工作台故障诊断\n## Task Description\n对工作台平台的相关故障进行诊断分析，返回根因及修复建议。", "mediaType": "" }
    ],
    "contextId": "exec-wp-20250101-001"
  },
  "configuration": {
    "acceptedOutputModes": [],
    "returnImmediately": false
  }
}
```

**curl：**

```bash
curl -X POST http://127.0.0.1:26336/a2a/json/message:stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "fmind-auth: Bearer <access_token>" \
  -d '{
    "message": {
      "messageId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "role": "ROLE_AGENT",
      "parts": [{"text": "## Task Type\n工作台故障诊断\n## Task Description\n对工作台平台的相关故障进行诊断分析，返回根因及修复建议。", "mediaType": ""}],
      "contextId": "exec-wp-20250101-001"
    },
    "configuration": {
      "acceptedOutputModes": [],
      "returnImmediately": false
    }
  }'
```

> **注意**：Workbench Agent 未启用 TASK-T 扩展，消息直接以纯文本通过 `parts[].text` 传递。

#### JSONRPC，流式

```
POST http://127.0.0.1:26336/a2a/v1
Accept: text/event-stream
Content-Type: application/json
fmind-auth: Bearer <access_token>
```

```json
{
  "jsonrpc": "2.0",
  "method": "SendStreamingMessage",
  "params": {
    "message": {
      "messageId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "role": "ROLE_AGENT",
      "parts": [
        { "text": "## Task Type\n工作台故障诊断\n## Task Description\n对工作台平台的相关故障进行诊断分析，返回根因及修复建议。", "mediaType": "" }
      ],
      "contextId": "exec-wp-20250101-001"
    },
    "configuration": {
      "acceptedOutputModes": [],
      "returnImmediately": false
    }
  },
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**curl：**

```bash
curl -X POST http://127.0.0.1:26336/a2a/v1 \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "fmind-auth: Bearer <access_token>" \
  -d '{
    "jsonrpc": "2.0",
    "method": "SendStreamingMessage",
    "params": {
      "message": {
        "messageId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "role": "ROLE_AGENT",
        "parts": [{"text": "## Task Type\n工作台故障诊断\n## Task Description\n对工作台平台的相关故障进行诊断分析，返回根因及修复建议。", "mediaType": ""}],
        "contextId": "exec-wp-20250101-001"
      },
      "configuration": {
        "acceptedOutputModes": [],
        "returnImmediately": false
      }
    },
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }'
```

---

## 7. 关键差异对比

| | SPN Domain Agent | Workbench Platform Agent |
|---|---|---|
| **URL（JSONRPC）** | `http://127.0.0.1:26335/a2a/v1` | `http://127.0.0.1:26336/a2a/v1` |
| **URL（HTTP+JSON）** | `http://127.0.0.1:26335/a2a/json` | `http://127.0.0.1:26336/a2a/json` |
| **TASK-T 扩展** | 启用，text 走 `metadata` | 未启用，text 走 `parts[].text` |
| **parts[].text** | 空（`[]`） | 包含任务描述文本 |
| **认证头** | `Authorization: Bearer <accessSession>` | `fmind-auth: Bearer <access_token>` |
| **扩展头** | `A2A-Extensions: <Task-T URI>` | 无 |

---

## 8. 协议对比总表

| | HTTP+JSON 非流式 | HTTP+JSON 流式 | JSONRPC 非流式 | JSONRPC 流式 |
|---|---|---|---|---|
| **端点** | `{url}/message:send` | `{url}/message:stream` | `{url}` | `{url}` |
| **method 字段** | 无 | 无 | `"SendMessage"` | `"SendStreamingMessage"` |
| **请求体外壳** | 裸 JSON | 裸 JSON | `{jsonrpc, method, params, id}` | `{jsonrpc, method, params, id}` |
| **Accept** | `application/json` | `text/event-stream` | `application/json` | `text/event-stream` |
| **响应格式** | `SendMessageResponse` JSON | SSE 事件流 | `{jsonrpc, result, id}` | SSE 事件流 (`{jsonrpc, result, id}`) |
| **params 内部结构** | 相同 | 相同 | 相同 | 相同 |
