# 编排中心API参考

## 使用前必读

### 简介

  编排中心是一个面向多智能体（Agent）协作的可视化编排平台，对外提供以下 RESTful API 接口，供其他系统集成调用：

  - **SOP 编排**：上传 PDF 文件或提交自然语言 SOP 步骤，自动生成 PSOP 工作流。
  - **意图编排**：提交自然语言任务意图，由 LLM 自主规划生成 PSOP 工作流。
  - **自动编排+执行**：提交任务描述，自动检索匹配工作流并执行，无匹配则自动生成后执行（SSE 实时推送）。
  - **执行指定工作流**：根据已知 PSOP ID 启动执行，通过 SSE 实时推送执行进度。
  - **查询 Agent 列表**：获取所有可用 Agent 及其技能列表。
  - **查询执行结果**：根据执行 ID 获取工作流执行记录详情。

  所有接口基础路径为 **`/api/v1`**。

### 响应格式

  所有接口（除 SSE 流式接口外）统一返回以下 JSON 结构：

  | 参数名称  | 类型     | 描述                                      |
  |-----------|----------|-------------------------------------------|
  | code      | integer  | HTTP 状态码，200 表示成功，201 表示创建成功 |
  | message   | string   | 响应消息描述                              |
  | status    | string   | 响应状态，成功为 `"success"`              |
  | data      | object   | 响应数据，具体结构参见各接口              |

  错误响应（HTTPException）格式：

  | 参数名称 | 类型    | 描述         |
  |----------|---------|--------------|
  | detail   | string  | 错误描述信息 |

### 约束与限制

  - 各接口均受并发控制（Semaphore）与令牌桶限流（RateLimiter）双重保护，详见各接口约束。
  - 服务端口默认为 **60000**。

---

## 1. SOP 编排接口

- 典型场景

    用户持有 PDF 格式的解决方案包文档，或直接输入自然语言 SOP 步骤描述，需要自动生成多 Agent 协作的 PSOP 工作流。

- 功能描述

    接收 PDF 文件（解析 "5. Interaction Flow" 章节）或 JSON 格式的 SOP 步骤文本，结合可用 Agent 列表，由 LLM 生成 PSOP 工作流并自动保存。

- 接口约束

  - 文件上传模式：仅支持 PDF、TXT、MD 格式，文件名须匹配 `^[\w\-. ]{1,128}\.(pdf|txt|md)$`。
  - 单文件不超过 100 MB。
  - PDF 文件须以 `%PDF-` 开头（magic bytes 校验）。
  - 单实例上该接口最大并发数由 `server.conf` 中 `FLOW_CTL_PLAN` 配置决定。
  - 限流标识：`sop_orchestrate`，速率由 `FLOW_CTL_PLAN` 配置决定。

- 调用方法

    POST

- URI

    `/api/v1/orchestrate/sop`

- 请求参数

    **模式 A：文件上传（multipart/form-data）**

    | 参数名称 | 是否必选 | 类型   | 值域            | 默认值 | 描述                        |
    |----------|----------|--------|-----------------|--------|-----------------------------|
    | file     | 否       | file   | PDF/TXT/MD 文件  | -      | 待解析的解决方案包文件       |
    | name     | 否       | string | -               | -      | 可选的工作流名称            |

    **模式 B：JSON 请求体（application/json）**

    | 参数名称    | 是否必选 | 类型   | 值域 | 默认值 | 描述                      |
    |-------------|----------|--------|------|--------|---------------------------|
    | sop_content | 是       | string | -    | -      | 自然语言 SOP 步骤（Markdown） |
    | name        | 否       | string | -    | -      | 可选的工作流名称           |

    > **优先级**：若同时提供文件与 JSON 请求体，文件优先。

- 请求示例

    **文件上传：**

    ```
    POST /api/v1/orchestrate/sop HTTP/1.1
    Host: your-host:60000
    Content-Type: multipart/form-data; boundary=----WebKitFormBoundary

    ------WebKitFormBoundary
    Content-Disposition: form-data; name="file"; filename="solution.pdf"
    Content-Type: application/pdf

    [PDF文件二进制数据]
    ------WebKitFormBoundary
    Content-Disposition: form-data; name="name"

    我的工作流
    ------WebKitFormBoundary--
    ```

    **JSON 请求体：**

    ```json
    POST /api/v1/orchestrate/sop HTTP/1.1
    Host: your-host:60000
    Content-Type: application/json

    {
        "sop_content": "## 节能流程\n1. 收集设备状态数据\n2. 分析能耗基线\n3. 执行节能策略",
        "name": "节能评估"
    }
    ```

- 响应参数

    | 参数名称 | 类型   | 描述                           |
    |----------|--------|--------------------------------|
    | code     | integer | 201 表示创建成功               |
    | message  | string | 固定返回 `"PSOP generated and saved"` |
    | status   | string | `"success"`                    |
    | data     | object | 生成的 PSOP 工作流完整对象      |

    **PSOP 对象结构（data 字段）**: 参见 [附录 A：PSOP 数据结构](#附录-apsop-数据结构)。

- 响应示例

    ```json
    {
        "code": 201,
        "message": "PSOP generated and saved",
        "status": "success",
        "data": {
            "id": "a1b2c3d4-...",
            "name": "节能评估",
            "description": "基于SOP生成的节能工作流",
            "created_at": "2026-05-22T10:30:00.123456",
            "steps": [ ... ],
            "related_preflow": "preflow-uuid-...",
            "user_intent": "用户原始SOP步骤文本前200字符",
            "tags": []
        }
    }
    ```

- 错误码

    | 状态码 | 说明                               |
    |--------|------------------------------------|
    | 400    | 文件名不合法、PDF 格式无效、SOP 内容为空、解析章节失败 |
    | 413    | 文件超过 100 MB                     |
    | 503    | 并发数已满，服务器繁忙              |

---

## 2. 意图编排接口

- 典型场景

    用户仅有高层次的业务意图描述（如"帮我做一次全网节能优化"），无需提供具体步骤，由 LLM 自主规划生成工作流。

- 功能描述

    接收自然语言任务意图，结合可用 Agent 列表，由 LLM 自主规划并生成 PSOP 工作流，自动保存。

- 接口约束

  - 单实例上该接口最大并发数由 `server.conf` 中 `FLOW_CTL_GENERATE_PSOP` 配置决定。
  - 限流标识：`intent_orchestrate`，速率由 `FLOW_CTL_GENERATE_PSOP` 配置决定。

- 调用方法

    POST

- URI

    `/api/v1/orchestrate/intent`

- 请求参数

    JSON 请求体（application/json）：

    | 参数名称 | 是否必选 | 类型   | 值域 | 默认值 | 描述                       |
    |----------|----------|--------|------|--------|----------------------------|
    | intent   | 是       | string | -    | -      | 自然语言任务意图描述        |
    | name     | 否       | string | -    | -      | 可选的工作流名称            |

- 请求示例

    ```json
    POST /api/v1/orchestrate/intent HTTP/1.1
    Host: your-host:60000
    Content-Type: application/json

    {
        "intent": "帮我做一次全网节能优化",
        "name": "全网节能优化"
    }
    ```

- 响应参数

    | 参数名称 | 类型   | 描述                           |
    |----------|--------|--------------------------------|
    | code     | integer | 201 表示创建成功               |
    | message  | string | 固定返回 `"PSOP generated and saved"` |
    | status   | string | `"success"`                    |
    | data     | object | 生成的 PSOP 工作流完整对象      |

- 响应示例

    ```json
    {
        "code": 201,
        "message": "PSOP generated and saved",
        "status": "success",
        "data": {
            "id": "e5f6g7h8-...",
            "name": "全网节能优化",
            "description": null,
            "created_at": "2026-05-22T10:31:00.123456",
            "steps": [ ... ],
            "tags": ["节能", "全网"]
        }
    }
    ```

- 错误码

    | 状态码 | 说明                  |
    |--------|-----------------------|
    | 404    | 无可用 Agent          |
    | 503    | 并发数已满，服务器繁忙 |

---

## 3. 自动编排+执行接口

- 典型场景

    用户直接提交任务需求，系统自动判定是否有匹配的已有工作流，有则直接执行，无则先生成再执行。适用于"一句话驱动"的端到端任务场景。

- 功能描述

    接收任务描述文本，首先通过 LLM 检索匹配的已有 PSOP 工作流。若匹配成功，直接以 SSE 流执行；若无匹配，自动调用意图编排生成新的 PSOP，保存后立即执行。全程通过 SSE（Server-Sent Events）实时推送执行进度。

- 接口约束

  - 单实例上该接口最大并发数由 `server.conf` 中 `FLOW_CTL_START_PROCESS_STREAM` 配置决定。
  - 限流标识：`ext_execute_auto`，速率由 `FLOW_CTL_START_PROCESS_STREAM` 配置决定。
  - 响应为 SSE 流式连接，请确保客户端支持 `text/event-stream` 类型的长连接。

- 调用方法

    POST

- URI

    `/api/v1/orchestrate/execute`

- 请求参数

    JSON 请求体（application/json）：

    | 参数名称 | 是否必选 | 类型   | 值域 | 默认值 | 描述                                   |
    |----------|----------|--------|------|--------|----------------------------------------|
    | task     | 是       | string | -    | -      | 任务描述，系统会先检索已有 PSOP，无匹配则自动生成 |
    | name     | 否       | string | -    | -      | 可选的工作流名称（用于自动生成场景）     |

- 请求示例

    ```json
    POST /api/v1/orchestrate/execute HTTP/1.1
    Host: your-host:60000
    Content-Type: application/json

    {
        "task": "帮我做一次网络故障根因分析",
        "name": "故障根因分析"
    }
    ```

- 响应格式（SSE 事件流）

    响应为 `text/event-stream`，事件格式如下：

    ```
    data: {"type": "init", "data": {...}}
    data: {"type": "start", "data": {...}}
    data: {"type": "agent_request", "data": {...}}
    data: {"type": "agent_response", "data": {...}}
    data: {"type": "psop_update", "data": {...}}
    data: {"type": "complete", "data": {...}}
    event: close
    data: {}
    ```

    **SSE 事件类型说明：**

    | 事件类型       | 描述                                                    |
    |----------------|---------------------------------------------------------|
    | init           | 执行引擎初始化，包含 `psop_id`                           |
    | start          | 执行开始通知                                            |
    | agent_request  | Agent 任务下发事件，包含 `task_id`、`agent`、`description` |
    | agent_response | Agent 执行结果返回事件，包含 `task_id`、`status`、`result` |
    | psop_update    | PSOP 工作流步骤状态更新，包含 `step_name`、`status`       |
    | complete       | 所有步骤执行完成，包含 `execution_history` 汇总           |
    | error          | 执行失败，包含 `error` 描述                              |
    | close          | SSE 流结束信号                                          |

    每个事件 JSON 包含 `type`（事件类型）、`data`（事件数据）、`timestamp`（时间戳）三个字段。

    执行完成后，系统自动保存 `ExecutionRecord` 执行记录，可通过 [查询执行结果接口](#6-查询执行结果接口) 获取详情。

- 响应示例

    ```
    data: {"type":"init","data":{"psop_id":"a1b2c3d4-...","message":"Initializing execution engine"},"timestamp":12345.67}
    data: {"type":"start","data":{"psop_id":"a1b2c3d4-...","message":"Execution started"},"timestamp":12345.68}
    data: {"type":"agent_request","data":{"task_id":"task-001","agent":"RAN Energy Saver","skill":"analyze_energy","description":"分析基站节能数据"},"timestamp":12345.70}
    data: {"type":"agent_response","data":{"task_id":"task-001","status":"success","result":{"details":"节能分析完成"}},"timestamp":12346.50}
    data: {"type":"psop_update","data":{"step_name":"step1","status":"completed"},"timestamp":12346.51}
    data: {"type":"complete","data":{"psop_id":"a1b2c3d4-...","execution_history":[...]},"timestamp":12347.00}
    event: close
    data: {}
    ```

- 错误码

    | 状态码 | 说明                              |
    |--------|-----------------------------------|
    | 500    | 自动生成 PSOP 失败                 |
    | 503    | 并发数已满，服务器繁忙             |

    > 执行过程中的运行时错误通过 SSE `error` 事件推送，不会体现在 HTTP 状态码上。

---

## 4. 执行指定工作流接口

- 典型场景

    调用方已知道目标 PSOP 的 ID（例如从数据库中查询获得），希望直接执行该工作流，无需检索匹配。

- 功能描述

    根据 PSOP ID 查找工作流，以 SSE 流方式启动执行，实时推送执行进度。

- 接口约束

  - 单实例上该接口最大并发数由 `server.conf` 中 `FLOW_CTL_START_PROCESS_STREAM` 配置决定。
  - 限流标识：`ext_execute_by_id`，速率由 `FLOW_CTL_START_PROCESS_STREAM` 配置决定。
  - 响应为 SSE 流式连接。

- 调用方法

    GET

- URI

    `/api/v1/orchestrate/execute/{psop_id}`

- 请求参数

    | 参数名称     | 是否必选 | 类型   | 位置   | 默认值 | 描述                                           |
    |--------------|----------|--------|--------|--------|------------------------------------------------|
    | psop_id      | 是       | string | path   | -      | PSOP 工作流 ID                                  |
    | user_intent  | 否       | string | query  | -      | 运行时用户意图，用于 Agent 上下文注入，执行时传入 |

- 请求示例

    ```
    GET /api/v1/orchestrate/execute/a1b2c3d4-e5f6-7890-abcd-ef1234567890?user_intent=帮我查基站节能率 HTTP/1.1
    Host: your-host:60000
    ```

- 响应格式（SSE 事件流）

    与 [自动编排+执行接口](#3-自动编排执行接口) 相同的 SSE 事件格式。

- 错误码

    | 状态码 | 说明                  |
    |--------|-----------------------|
    | 404    | 指定 PSOP 不存在      |
    | 503    | 并发数已满，服务器繁忙 |

---

## 5. 查询 Agent 列表接口

- 典型场景

    调用方需要了解当前可用的 Agent 及其技能，以便构造合适的任务描述。

- 功能描述

    从 Agent Registry 获取所有已注册的 Agent 卡片列表（含 Agent 名称、描述、技能列表等元信息）。

- 接口约束

  - 限流标识：`list_agents`，速率由 `FLOW_CTL_AGENT_CARDS` 配置决定。

- 调用方法

    GET

- URI

    `/api/v1/agents`

- 请求参数

    无。

- 请求示例

    ```
    GET /api/v1/agents HTTP/1.1
    Host: your-host:60000
    ```

- 响应参数

    | 参数名称 | 类型   | 描述                   |
    |----------|--------|------------------------|
    | code     | integer | 200 表示成功           |
    | message  | string | 固定返回 `"success"`   |
    | status   | string | `"success"`            |
    | data     | array  | AgentCard 对象列表，每个元素包含 Agent 的 `name`、`description`、`skills`、`url` 等字段 |

- 响应示例

    ```json
    {
        "code": 200,
        "message": "success",
        "status": "success",
        "data": [
            {
                "name": "RAN Energy Saver",
                "description": "无线接入网节能优化Agent",
                "skills": [
                    {
                        "name": "analyze_energy",
                        "description": "分析基站能耗数据"
                    }
                ],
                "url": "http://agent-host:9001/"
            }
        ]
    }
    ```

---

## 6. 查询执行结果接口

- 典型场景

    工作流执行完成后（或执行中断后），调用方需要查询某次执行的完整记录，包括步骤级执行历史、Agent 交互事件、最终状态等。

- 功能描述

    根据执行 ID 获取执行记录详情，包含执行状态、步骤历史、Agent 交互事件、完成时间、错误信息（如有）等。

- 接口约束

  - 限流标识：`get_execution`，速率由 `FLOW_CTL_ONE_PSOP` 配置决定。

- 调用方法

    GET

- URI

    `/api/v1/executions/{execution_id}`

- 请求参数

    | 参数名称      | 是否必选 | 类型   | 位置 | 默认值 | 描述           |
    |---------------|----------|--------|------|--------|----------------|
    | execution_id  | 是       | string | path | -      | 执行记录 ID     |

- 请求示例

    ```
    GET /api/v1/executions/exec-uuid-12345678 HTTP/1.1
    Host: your-host:60000
    ```

- 响应参数

    | 参数名称 | 类型   | 描述                                          |
    |----------|--------|-----------------------------------------------|
    | code     | integer | 200 表示成功                                  |
    | message  | string | 固定返回 `"success"`                          |
    | status   | string | `"success"`                                   |
    | data     | object | ExecutionRecord 执行记录对象                   |

    **ExecutionRecord 对象结构（data 字段）**：参见 [附录 B：ExecutionRecord 数据结构](#附录-bexecutionrecord-数据结构)。

- 响应示例

    ```json
    {
        "code": 200,
        "message": "success",
        "status": "success",
        "data": {
            "execution_id": "exec-uuid-12345678",
            "psop_id": "a1b2c3d4-...",
            "psop_name": "节能评估",
            "started_at": "2026-05-22T10:30:00.000000",
            "completed_at": "2026-05-22T10:31:30.000000",
            "status": "success",
            "execution_history": [ ... ],
            "final_psop": { ... },
            "events": [ ... ],
            "error": null
        }
    }
    ```

- 错误码

    | 状态码 | 说明                      |
    |--------|---------------------------|
    | 404    | 指定执行记录不存在         |

---

## 附录

### 附录 A：PSOP 数据结构

| 字段名          | 类型             | 描述                                                        |
|-----------------|------------------|-------------------------------------------------------------|
| id              | string (UUID)    | 工作流唯一标识                                                |
| name            | string           | 工作流名称                                                    |
| description     | string \| null   | 工作流简要描述                                                |
| created_at      | string (ISO8601) | 创建时间戳                                                    |
| steps           | array[Step]      | 工作流步骤列表（见下方 Step 结构）                             |
| related_preflow | string \| null   | 关联的 PreFlow ID（由 SOP 编排生成时填充）                     |
| user_intent     | string \| null   | 生成该工作流的原始用户意图                                    |
| tags            | array[string]    | 标签列表，用于分类和检索                                      |

**Step 结构：**

| 字段名      | 类型                   | 描述                                                              |
|-------------|------------------------|-------------------------------------------------------------------|
| name        | string                 | 步骤标识（如 `"step1"`）                                          |
| type        | string                 | 步骤成功条件：`"AllSuccess"`（全部子任务成功）或 `"AnySuccess"`（任一子任务成功） |
| subtasks    | array[Task]            | 子任务列表，子任务间无依赖，可并行执行                            |
| next        | array[JumpCondition] \| null | 跳转条件列表，指向下一步骤；空值表示无条件顺序执行              |
| layer       | integer                | 编排层级：0 = 执行层（叶子 Agent），1+ = 聚合层                  |
| context_from | array[string] \| null  | 上下文来源步骤列表，`["*"]` 表示包含所有先前步骤的输出；为 null 且 layer > 0 时自动从图拓扑推导 |

**Task 结构：**

| 字段名      | 类型   | 描述                               |
|-------------|--------|------------------------------------|
| task_id     | string | 唯一任务标识 (UUID)                |
| description | string | 任务描述                           |
| agent       | string | 执行该任务的 Agent 名称            |
| skill       | string | 执行该任务所需的技能名称           |
| status      | string | 任务状态：`"pending"` / `"running"` / `"success"` / `"failed"` |

**JumpCondition 结构：**

| 字段名    | 类型   | 描述                 |
|-----------|--------|----------------------|
| step      | string | 目标步骤名称         |
| condition | string | 跳转条件描述         |

---

### 附录 B：ExecutionRecord 数据结构

| 字段名            | 类型             | 描述                                                    |
|-------------------|------------------|---------------------------------------------------------|
| execution_id      | string (UUID)    | 执行记录唯一标识                                          |
| psop_id           | string           | 执行的 PSOP 工作流 ID                                    |
| psop_name         | string           | 执行的 PSOP 工作流名称                                    |
| started_at        | string (ISO8601) | 执行开始时间                                              |
| completed_at      | string \| null   | 执行完成时间（失败时仍会记录）                            |
| status            | string           | 执行状态：`"running"` / `"success"` / `"failed"` / `"stopped"` |
| execution_history | array[object]    | 步骤级执行历史，每项包含 `step_name`、`subtask`、`status`、`result` |
| final_psop        | object \| null   | 执行完成时带任务状态的最终 PSOP 快照                       |
| events            | array[object]    | Agent 交互事件记录（`agent_request` / `agent_response` 事件） |
| error             | string \| null   | 执行失败时的错误信息                                      |
