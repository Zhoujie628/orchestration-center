# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""Live Streaming Agent -- workflow execution host for live broadcast assurance.

Leader role: receives the raw intent via A2A-T, searches/loads the PSOP
workflow from the orchestration center, then executes the workflow via
the workflow-engine SDK (execute_psop), streaming SDK events back to the
caller as A2A-T TaskUpdate events.

SelfLoop steps (step1, step4, step7) are executed locally via LLM.
Other steps are dispatched to Assurance Agent / RAN Agent via A2A-T.
No Authorization-T or Notification-T pre-positioning.
"""

import asyncio
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    Artifact,
    Part,
    Message,
)

from workflow_engine import (
    A2ATransport,
    ControlPoint,
    EventCallback,
    EventType,
    RouteDecision,
    TaskResponse,
    Workflow as SDKWorkflow,
    WorkflowEngineClient,
    execute_psop,
    load_psop,
    search_psop,
    RegistryClient,
)
from workflow_engine.client.extension_handlers import TaskTHandler, NegotiationTHandler

from common.llm import get_llm_instance
from common.util.config_util import get_conf


class LiveStreamingControlPoint(ControlPoint):
    """ControlPoint for Live Streaming Agent workflow execution.

    SelfLoop steps are executed locally via LLM (event info parsing,
    KQI monitoring). Other steps are dispatched to remote agents.
    """

    _llm_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ls_llm_")
    _NEGOTIATION_MAX_ROUNDS = 3

    def __init__(
        self,
        orch_url: str,
        ssl_verify: bool = False,
        a2at_env_path: Optional[str] = None,
        lang: str = "zh",
    ):
        self.orch_url = orch_url.rstrip("/")
        self.ssl_verify = ssl_verify
        self.a2at_env_path = a2at_env_path
        self.lang = lang or "zh"
        self.llm_client = get_llm_instance()
        self._sdk_workflow: Optional[SDKWorkflow] = None
        self._step_outputs: Dict[str, Dict[str, Any]] = {}
        self._current_step: Optional[str] = None
        self._engine_client: Optional[WorkflowEngineClient] = None

    def set_workflow(self, workflow: SDKWorkflow):
        self._sdk_workflow = workflow

    def set_engine_client(self, engine_client: WorkflowEngineClient):
        self._engine_client = engine_client

    def update_step_outputs(self, step_outputs: Dict[str, Dict[str, Any]]):
        self._step_outputs = dict(step_outputs)

    def set_current_step(self, step_name: str):
        self._current_step = step_name

    async def on_task(self, request, engine_client: WorkflowEngineClient) -> TaskResponse:
        task_label = request.description or request.message
        try:
            result = await engine_client.send_message(request.agent_name, request.message)
            if result.task_state and "INPUT_REQUIRED" in result.task_state:
                raise RuntimeError(
                    f"Negotiation with agent '{request.agent_name}' did not converge "
                    f"after {self._NEGOTIATION_MAX_ROUNDS} round(s)."
                )
            return TaskResponse(success=bool(result.text), output=result.text or "")
        except Exception as e:
            err = f"Agent call failed : {str(e)}"
            logger.error(f"  >Task failed: {task_label} | Error: {err}")
            return TaskResponse(success=False, error=err)

    async def on_self_task(self, request) -> TaskResponse:
        try:
            result = await self._llm_execute_task(request.message)
            return TaskResponse(success=True, output=result)
        except Exception as e:
            err = f"Self-loop task failed : {str(e)}"
            logger.error(f"  >Self-loop failed: {request.message[:60]} | Error: {err}")
            return TaskResponse(success=False, error=err)

    async def on_route(self, step_name: str, results: Dict[str, Any],
                       conditions: list) -> RouteDecision:
        sdk_step = self._find_step(step_name)
        next_name = await self._llm_route_decision(sdk_step, results)
        return RouteDecision(next_step=next_name)

    async def on_negotiation(self, agent_name: str, negotiation_text: str,
                             receive_result: Dict[str, Any]) -> str:
        predecessor_data = await self._forward_to_predecessors(agent_name, negotiation_text)
        if predecessor_data:
            return predecessor_data
        receive_msg = receive_result.get("message", "") if isinstance(receive_result, dict) else ""
        original_task = ""
        if isinstance(receive_result, dict):
            for key, value in receive_result.items():
                if "Task-T" in str(key) and isinstance(value, str) and len(value) > 20:
                    original_task = value
                    break
            if not original_task:
                original_task = receive_result.get("negotiationConcern", "") or ""
        workflow_intent = ""
        if self._sdk_workflow and hasattr(self._sdk_workflow, "user_intent"):
            workflow_intent = self._sdk_workflow.user_intent or ""
        clarification = await self._generate_clarification(
            agent_name=agent_name,
            original_task=original_task,
            negotiation_text=negotiation_text,
            receive_message=receive_msg,
            workflow_intent=workflow_intent,
        )
        return clarification or ""

    def _find_step(self, step_name: str):
        if not self._sdk_workflow:
            return None
        for s in self._sdk_workflow.steps:
            if s.name == step_name:
                return s
        return None

    async def _forward_to_predecessors(self, agent_name: str, negotiation_text: str) -> Optional[str]:
        if not self._engine_client or not self._sdk_workflow or not self._current_step:
            return None
        try:
            current_step = self._find_step(self._current_step)
            if not current_step or not current_step.context_from:
                return None
            for pred_name in current_step.context_from:
                if pred_name == "*":
                    continue
                if pred_name in self._step_outputs:
                    pred_data = self._step_outputs[pred_name]
                    context = "\n".join(f"- {k}: {v}" for k, v in pred_data.items())
                    return f"前置步骤 {pred_name} 的执行结果：\n{context}"
        except Exception as e:
            logger.warning(f"[LiveStreamingCP] Forward to predecessors failed: {e}")
        return None

    async def _generate_clarification(self, agent_name: str, original_task: str,
                                       negotiation_text: str, receive_message: str,
                                       workflow_intent: str = "") -> str:
        if not self.llm_client:
            return "信息不足，请基于已有数据尽力完成任务。"
        workflow_context = self._build_merge_context()
        current_step_info = ""
        if self._current_step and self._sdk_workflow:
            for s in self._sdk_workflow.steps:
                if s.name == self._current_step and s.subtasks:
                    for sub in s.subtasks:
                        current_step_info += f"步骤: {s.name}, 任务描述: {sub.description or ''}, 目标Agent: {sub.agent or ''}\n"
        lang_hint = "请用中文回复。" if self.lang == "zh" else "Respond in English."
        prompt = f"""# 角色
你是直播保障工作台的协商处理器。一个执行Agent在收到任务后发起了协商，明确列出了它缺少的数据字段。
你的任务是：**针对Agent列出的每一个缺失字段，逐个补充具体的模拟数据**。

# 核心要求
- **必须逐个字段回复**，Agent说缺什么你就补什么，一一对应
- 每个字段给出具体数值，不要反问、不要说"请提供"
- 数据要符合电信赛事直播保障的真实场景，数值合理

# 工作流场景
{workflow_intent or "(未提供)"}

# 已完成步骤的执行结果
{workflow_context or "(当前是第一个步骤，尚无已完成的前置步骤)"}

# 当前步骤信息
{current_step_info or "(未提供)"}

# 当前Agent
{agent_name}

# 原始任务描述
{original_task or "(未提供)"}

# Agent的协商请求
{negotiation_text}

# 补充说明
{receive_message}

# 输出格式
请按以下格式输出：

## 补充数据
- **字段名**: 具体值
- **字段名**: 具体值

直接输出补充数据，不要添加其他前缀。{lang_hint}"""
        try:
            t0 = time.time()
            logger.info(f"[LiveStreamingCP] Negotiation clarification for '{agent_name}': calling LLM...")
            _, result = await asyncio.get_event_loop().run_in_executor(
                self._llm_executor, self.llm_client.ask_llm, prompt
            )
            logger.info(f"[LiveStreamingCP] Negotiation clarification for '{agent_name}': done ({time.time()-t0:.2f}s)")
            return result.strip() if result else ""
        except Exception as e:
            logger.error(f"[LiveStreamingCP] LLM clarification failed: {e}")
            return "信息不足，请基于已有数据尽力完成任务。"

    async def _llm_execute_task(self, message: str) -> str:
        context = self._build_merge_context()
        lang_hint = "请用中文回复。" if self.lang == "zh" else "Respond in English."
        prompt = f"""# 角色
你是赛事直播保障Agent（Live Streaming Agent），负责赛事需求解析和实时KQI监控。

# 已完成步骤的执行结果
{context or "(当前是第一个步骤，尚无已完成的前置步骤)"}

# 当前任务
{message}

# 输出要求
- 基于任务描述和已有上下文，生成符合电信赛事直播保障场景的具体数据
- 输出结构化的分析结果，包含具体的数值、时间、地点等信息
- 数据要真实合理，符合5G网络赛事直播保障的实际场景
{lang_hint}"""
        if not self.llm_client:
            return f"Live Streaming Agent 执行完成: {message[:100]}"
        try:
            t0 = time.time()
            logger.info(f"[LiveStreamingCP] Self-loop task: calling LLM...")
            _, result = await asyncio.get_event_loop().run_in_executor(
                self._llm_executor, self.llm_client.ask_llm, prompt
            )
            logger.info(f"[LiveStreamingCP] Self-loop task: done ({time.time()-t0:.2f}s)")
            return result.strip() if result else ""
        except Exception as e:
            logger.error(f"[LiveStreamingCP] LLM self-loop task failed: {e}")
            return f"Live Streaming Agent 执行完成（LLM不可用）: {message[:200]}"

    async def _llm_route_decision(self, current_step, task_result: Dict[str, Any]) -> str:
        results_context = []
        for skill, res in task_result.items():
            if isinstance(res, dict) and "error" in res:
                results_context.append(f"[{skill}]: Execution failed - {res['error']}")
            else:
                text_res = res if isinstance(res, str) else str(res)
                results_context.append(f"[{skill}]: Execution succeeded - Output summary: {text_res}")
        results_text = "\n".join(results_context)
        next_list = current_step.next if current_step is not None and current_step.next else []
        next_conditions = json.dumps(
            [{"step": c.step, "condition": c.condition} for c in next_list],
            ensure_ascii=False, indent=2,
        )
        if current_step is not None:
            step_name = current_step.name
            if hasattr(current_step, "step_type") and current_step.step_type is not None:
                step_type_val = current_step.step_type.value
            elif hasattr(current_step, "type") and current_step.type is not None:
                step_type_val = current_step.type.value
            else:
                step_type_val = "AllSuccess"
        else:
            step_name, step_type_val = "(unknown)", "AllSuccess"
        prompt_template = f"""
# Role
You are a workflow logic controller. Determine the next step based on execution results.

# Current Context
Current step: {step_name}
Step type: {step_type_val}

# Execution Results
{results_text}

# Next Conditions
{next_conditions}

# Decision Logic
1. Analyze the Execution Results.
2. Check whether any Next Conditions are satisfied.
3. Empty condition means unconditional transition.
4. Output exactly one word: the target step name, "end", or "retry".
"""
        if not self.llm_client:
            raise ValueError("LLM Client not initialized.")
        try:
            t0 = time.time()
            logger.info(f"[LiveStreamingCP] LLM route decision for step '{step_name}': calling LLM...")
            _, decision = await asyncio.get_event_loop().run_in_executor(
                self._llm_executor, self.llm_client.ask_llm, prompt_template
            )
            logger.info(f"[LiveStreamingCP] LLM route decision: done ({time.time()-t0:.2f}s)")
            decision = decision.strip() if decision else ""
            if not decision:
                return "end"
            if decision in ["end", "retry"]:
                return decision
            allowed_next = [jc.step for jc in next_list]
            allowed_lower = {n.lower(): n for n in allowed_next}
            if decision in allowed_next:
                return decision
            if decision.lower() in allowed_lower:
                return allowed_lower[decision.lower()]
            return "end"
        except Exception as e:
            logger.error(f"[LiveStreamingCP] LLM route decision failed: {e}")
            return "end"

    def _build_merge_context(self) -> str:
        if not self._step_outputs:
            return "(no completed steps yet)"
        steps = self._sdk_workflow.steps if self._sdk_workflow else []
        parts = []
        for step in steps:
            name = getattr(step, "name", None)
            if not name or name not in self._step_outputs:
                continue
            outputs = self._step_outputs[name]
            parts.append(f"### {name}")
            for task_desc, output in outputs.items():
                text = output if isinstance(output, str) else str(output)
                parts.append(f"- Task: {task_desc}")
                parts.append(f"  Output: {text}")
        return "\n".join(parts) if parts else "(no completed steps yet)"


class _LiveStreamingEventCallback(EventCallback):
    def __init__(self, cp: LiveStreamingControlPoint):
        self._cp = cp

    def on_event(self, event_type: str, data: Dict[str, Any]):
        if event_type == EventType.STEP_START:
            step_name = data.get("step")
            self._cp.set_current_step(step_name)
        elif event_type == EventType.TASK_STATUS_CHANGED:
            step_name = data.get("step")
            status = data.get("status", "")
            if step_name and status:
                outputs = self._cp._step_outputs.setdefault(step_name, {})
                outputs[data.get("subtask", "task")] = data.get("result", "")
        elif event_type == EventType.STEP_COMPLETE:
            step_name = data.get("step")
            if step_name:
                d = data if isinstance(data, dict) else {}
                self._cp.update_step_outputs({**self._cp._step_outputs, **{step_name: d.get("results", {})}})
        elif event_type == EventType.WORKFLOW_COMPLETE:
            d = data if isinstance(data, dict) else {}
            self._cp.update_step_outputs(d.get("step_outputs", {}))
        elif event_type == EventType.ERROR:
            d = data if isinstance(data, dict) else {}
            self._cp.update_step_outputs(d.get("step_outputs", {}))


class LiveStreamingAgentExecutor(AgentExecutor):
    """Live Streaming Agent -- workflow execution host for live broadcast assurance.

    Receives the raw intent, searches/loads the PSOP workflow, then executes
    it via the workflow-engine SDK. SelfLoop steps are handled locally via LLM,
    other steps are dispatched to Assurance/RAN agents via A2A-T.
    No Authorization-T or Notification-T pre-positioning.
    """

    def __init__(self) -> None:
        self.lang = "zh"
        self._a2at_env_path = str(Path(__file__).resolve().parents[2] / ".env")
        self._ssl_verify = str(get_conf().get("client_verify_server", "false")).lower() == "true"

        orch_port = get_conf().get("port", "5001")
        self._orch_url = f"https://127.0.0.1:{orch_port}"

        registry_url = get_conf().get("agent_registry_url", None)
        self._registry_url = registry_url or "https://127.0.0.1:5000"

        self._cred_path = str(
            Path(__file__).resolve().parent.parent / "agent_credentials.json"
        )

        logger.info(
            f"[LiveStreamingAgent] Initialized: orch_url={self._orch_url}, "
            f"registry_url={self._registry_url}, ssl_verify={self._ssl_verify}"
        )

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        t_execute = time.time()
        intent = context.get_user_input()
        task_id = context.task_id or "N/A"
        ctx_id = context.context_id or "N/A"
        logger.info(f"[LiveStreamingAgent] execute: task_id={task_id}, context_id={ctx_id}, intent={intent[:100]}")

        collected_events = []
        await event_queue.enqueue_event(Task(
            id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_WORKING),
            metadata={},
        ))

        try:
            request_metadata = context.metadata or {}
            psop_id = request_metadata.get("__orch_psop_id__")
            if psop_id:
                logger.info(f"[LiveStreamingAgent] Using psop_id from metadata: {psop_id}")
            else:
                t0 = time.time()
                psop_id = await self._search_psop(intent)
                logger.info(f"[LiveStreamingAgent] PSOP search done ({time.time()-t0:.2f}s)")

            t0 = time.time()
            workflow = await self._load_psop(psop_id)
            logger.info(f"[LiveStreamingAgent] PSOP load done ({time.time()-t0:.2f}s)")

            t0 = time.time()
            agent_cards = await self._load_agent_cards()
            logger.info(f"[LiveStreamingAgent] Agent cards load done: {len(agent_cards)} cards ({time.time()-t0:.2f}s)")

            transport = A2ATransport(
                agent_cards=agent_cards,
                a2at_env_path=self._a2at_env_path,
                credentials_config=self._cred_path,
                ssl_verify=self._ssl_verify,
            )
            engine_client = WorkflowEngineClient(
                transport,
                custom_handlers=[TaskTHandler(), NegotiationTHandler()],
                max_negotiation_rounds=3,
            )

            cp = LiveStreamingControlPoint(
                orch_url=self._orch_url,
                ssl_verify=self._ssl_verify,
                a2at_env_path=self._a2at_env_path,
                lang=self.lang,
            )
            cp.set_workflow(workflow)
            cp.set_engine_client(engine_client)
            engine_client.set_control_point(cp)
            engine_client.set_event_callback(_LiveStreamingEventCallback(cp))

            t0 = time.time()
            logger.info(f"[LiveStreamingAgent] Starting workflow execution")
            async for event in execute_psop(
                psop=workflow,
                agent_cards=agent_cards,
                control_point=cp,
                engine_client=engine_client,
                runtime_intent=intent,
                lang=self.lang,
                ssl_verify=self._ssl_verify,
            ):
                collected_events.append(event)
                task_update = self._event_to_task_update(event, context)
                await event_queue.enqueue_event(task_update)
            logger.info(f"[LiveStreamingAgent] Workflow execution done ({time.time()-t0:.2f}s), {len(collected_events)} events")

            await event_queue.enqueue_event(Task(
                id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
                metadata={"__sdk_events__": json.dumps(collected_events, ensure_ascii=False, default=str)},
            ))
            logger.info(f"[LiveStreamingAgent] Total execute time: {time.time()-t_execute:.2f}s")

            try:
                await engine_client.close()
            except Exception:
                pass

        except Exception as e:
            logger.error(f"[LiveStreamingAgent] Failed: {e}", exc_info=True)
            await event_queue.enqueue_event(self._error_task(context, str(e)))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info(f"[LiveStreamingAgent] Task cancelled: task_id={context.task_id}")

    async def _search_psop(self, intent: str) -> str:
        results = await search_psop(self._orch_url, intent, top_n=3, ssl_verify=self._ssl_verify)
        if results:
            logger.info(f"[LiveStreamingAgent] Found PSOP: {results[0].workflow_id}")
            return results[0].workflow_id
        raise RuntimeError("No matching workflow found")

    async def _load_psop(self, psop_id: str):
        workflow = await load_psop(self._orch_url, psop_id, ssl_verify=self._ssl_verify)
        logger.info(f"[LiveStreamingAgent] Loaded PSOP: {workflow.name} ({len(workflow.steps)} steps)")
        return workflow

    async def _load_agent_cards(self) -> list:
        registry = RegistryClient(self._registry_url, ssl_verify=self._ssl_verify)
        cards = await registry.fetch_agent_cards()
        logger.info(f"[LiveStreamingAgent] Loaded {len(cards)} agent cards from registry")
        return cards

    def _event_to_task_update(self, event: dict, context: RequestContext):
        etype = event.get("type", "")
        data = event.get("data", {})
        summary = self._event_summary(etype, data)
        metadata = {"__sdk_event__": json.dumps(event, ensure_ascii=False, default=str)}

        state = (
            TaskState.TASK_STATE_COMPLETED if etype in ("complete", "close")
            else TaskState.TASK_STATE_FAILED if etype == "error"
            else TaskState.TASK_STATE_WORKING
        )
        return TaskStatusUpdateEvent(
            task_id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(
                state=state,
                message=Message(role=2, parts=[Part(text=summary)]),
            ),
            metadata=metadata,
        )

    def _event_summary(self, etype: str, data: dict) -> str:
        if etype == "start":
            wf_name = data.get("workflow", "")
            return f"工作流开始: {wf_name}" if wf_name else "工作流开始"
        if etype == "step_start":
            return f"步骤开始: {data.get('step', '')}"
        if etype == "agent_request":
            return f"-> {data.get('agent', '')}"
        if etype == "agent_response":
            return f"<- {data.get('agent', '')}"
        if etype == "route_decision":
            return f"路由: {data.get('step', '')} -> {data.get('next', '')}"
        if etype == "step_complete":
            return f"步骤完成: {data.get('step', '')}"
        if etype == "task_status_changed":
            return f"状态: {data.get('status', '')}"
        if etype == "negotiation_request":
            return f"协商请求: {data.get('agent', '')}"
        if etype == "negotiation_resolved":
            return f"协商解决: {data.get('agent', '')}"
        if etype == "negotiation_failed":
            return f"协商失败: {data.get('agent', '')}"
        if etype == "complete":
            return "工作流执行完成"
        if etype == "error":
            return f"错误: {data.get('error', '')}"
        if etype == "close":
            return "流结束"
        return etype

    def _error_task(self, context: RequestContext, error_msg: str) -> TaskStatusUpdateEvent:
        return TaskStatusUpdateEvent(
            task_id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(
                state=TaskState.TASK_STATE_FAILED,
                message=Message(role=2, parts=[Part(text=f"错误: {error_msg}")]),
            ),
            metadata={"__sdk_event__": json.dumps(
                {"type": "error", "data": {"error": error_msg}}, ensure_ascii=False
            )},
        )
