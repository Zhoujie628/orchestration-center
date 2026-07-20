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
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""DynamicWorkflowEngine -- thin wrapper delegating to a2at-engine SDK.

The orchestration center's execution engine now delegates DAG traversal,
context assembly, A2A communication, agent auth, and A2A-T extension
handling to the a2at-engine SDK (``a2at_engine`` package). What remains
here is orchestration-center-specific policy:

- LLM-driven route decisions at conditional branches (``_llm_route_decision``)
- Negotiation clarification via LLM + DAG-predecessor forwarding
- The push-event contract (``agent_request`` / ``agent_response`` /
  ``psop_update`` / ``negotiation_*``) expected by the SSE frontend
  (``sse_executor.py``)

Logic that has moved into the SDK and is no longer here:

- DAG traversal / ``_execute_subtasks`` / ``_determine_next_steps`` -> WorkflowExecutor
- Context assembly / ``_build_context_for_step`` / ``_build_task_message`` -> ContextBuilder
- A2A send / SSE normalization / SSL / httpx client -> WorkflowEngineClient
- Agent auth setup / interceptors -> AuthManager (SDK)
- A2A-T Task-T prompt + Negotiation-T receive/continue loop -> extension_handlers (SDK)
- AgentCard normalization -> agentcard_normalizer (SDK)
"""

import asyncio
import atexit
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncIterator, Dict, Any, Optional, Callable, List

from loguru import logger

from a2at_engine import (
    WorkflowExecutor, WorkflowEngineClient, ControlPoint, EventCallback,
    EventType, TaskResponse, RouteDecision, Workflow as SDKWorkflow,
    execute_psop,
)

from common.llm import get_llm_instance
from orchestrate.core.model.psop import PSOP, TaskStatus


class _EngineControlPoint(ControlPoint):
    """Maps the SDK's decision hooks onto the orchestration center's auto
    behavior: auto-send (with negotiation), LLM routing."""

    def __init__(self, engine: "DynamicWorkflowEngine"):
        self._engine = engine

    async def on_task(self, request, engine_client):
        return await self._engine._dispatch_task(request, engine_client)

    async def on_route(self, step_name, results, conditions):
        return await self._engine._route(step_name, results, conditions)

    async def on_authorization(self, agent_name, auth_request):
        return await self._engine._handle_authorization(agent_name, auth_request)

    async def on_notification(self, agent_name, notification):
        return await self._engine._handle_notification(agent_name, notification)


class _EngineEventCallback(EventCallback):
    """Tracks the current step (for negotiation forwarding) and records stop
    events onto execution_history for the SSE frontend."""

    def __init__(self, engine: "DynamicWorkflowEngine"):
        self._engine = engine

    def on_event(self, event_type, data):
        if event_type == EventType.STEP_START:
            step_name = data.get("step")
            self._engine._current_step_name = step_name
            for i, s in enumerate(self._engine.workflow.steps):
                if s.name == step_name:
                    self._engine.current_step_idx = i
                    break
        elif event_type == EventType.ERROR:
            self._engine._record_stop_event(
                f"Step {data.get('step')} failed", data.get("results")
            )


class DynamicWorkflowEngine:
    _llm_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm_")
    _NEGOTIATION_MAX_ROUNDS = 3

    @classmethod
    def _shutdown_executor(cls):
        cls._llm_executor.shutdown(wait=True)

    def __init__(self, psop: PSOP, agent_cards, runtime_intent: str = None,
                 a2at_env_path: Path = None, lang: str = None):
        self.workflow = psop
        self.runtime_intent = runtime_intent
        self.lang = lang or "zh"
        self.current_step_idx = 0
        self.execution_history: List[Dict[str, Any]] = []
        self.llm_client = get_llm_instance()
        self.agent_cards = agent_cards
        self.push_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
        self.step_outputs: Dict[str, Dict[str, Any]] = {}
        self._current_step_name: Optional[str] = None
        self._sdk_workflow = None

        # Read client_verify_server from config (default: false for dev).
        from common.util.config_util import get_conf
        self._ssl_verify = str(get_conf().get("client_verify_server", "false")).lower() == "true"

        # Resolve the a2at env path + language for the SDK WorkflowEngineClient,
        # which builds its own A2ATClient from env_path. common.a2at_config is
        # imported lazily -- it may fail on some a2a-t-sdk versions, and we
        # must not break module import over it.
        env_path = a2at_env_path
        if not env_path:
            try:
                from common.a2at_config import get_a2at_env_path
                env_path = get_a2at_env_path()
            except Exception:
                env_path = None
        if env_path:
            try:
                from common.a2at_config import update_a2at_language
                update_a2at_language(self.lang)
            except Exception:
                pass
        self._a2at_env_path = str(env_path) if env_path else None

        # SDK engine client -- constructed lazily (deferred to run() /
        # send_message_to_agent) so tests that mock send_message_to_agent
        # never trigger real client construction.
        self._engine_client: Optional[WorkflowEngineClient] = None

    # ------------------------------------------------------------------
    # SDK client construction (lazy)
    # ------------------------------------------------------------------

    def _get_engine_client(self) -> WorkflowEngineClient:
        if self._engine_client is None:
            cred_path = Path(__file__).resolve().parent.parent.parent / "etc" / "conf" / "agent_credentials.json"
            self._engine_client = WorkflowEngineClient(
                agent_cards=self.agent_cards,
                a2at_env_path=self._a2at_env_path,
                credentials_config=str(cred_path) if cred_path.is_file() else None,
                ssl_verify=False,  # orch-center internal: agents use self-signed certs
            )
            logger.info(
                f"[Engine] WorkflowEngineClient constructed "
                f"(ssl_verify=False, {len(self.agent_cards)} card(s))"
            )
        return self._engine_client

    # ------------------------------------------------------------------
    # Public API (preserved for sse_executor.py + samples + tests)
    # ------------------------------------------------------------------

    def set_push_callback(self, callback: Callable[[str, Dict[str, Any]], None]):
        self.push_callback = callback

    async def events(self, on_finish: Optional[Callable] = None) -> AsyncIterator[dict]:
        """Stream execution events. Drives the workflow end-to-end.

        Yields serialized event dicts: start, step_start, agent_request,
        agent_response, task_status_changed, route_decision, step_complete,
        negotiation_*, authorization_request, notification, psop_update
        (derived from task_status_changed), complete, error, close.

        The SDK runner (execute_psop) owns the lifecycle, cancellation, and
        event collection. ``on_finish`` is the business persistence hook,
        called with (ExecutionResult, collected_events) after the workflow.
        """
        engine_client = self._get_engine_client()
        self._sdk_workflow = SDKWorkflow.from_dict(self.workflow.model_dump())
        async for event in execute_psop(
            psop=self.workflow.model_dump(),
            agent_cards=self.agent_cards,
            control_point=_EngineControlPoint(self),
            engine_client=engine_client,
            runtime_intent=self.runtime_intent or "",
            lang=self.lang,
            ssl_verify=self._ssl_verify,
            on_finish=on_finish,
            on_event=self._shape_event,
        ):
            yield event

    async def run(self):
        """Legacy non-streaming entry: drain events(), forward to push_callback
        (if set), return execution_history."""
        async for event in self.events():
            if self.push_callback:
                try:
                    self.push_callback(event.get("type"), event.get("data", {}))
                except Exception as e:
                    logger.error(f"Failed to push event: {e}")
        return self.execution_history

    def _shape_event(self, event: dict):
        """on_event transformer for execute_psop.

        - task_status_changed -> update the PSOP task status + inject a
          psop_update event (the PSOP model is orch-center-specific; the SDK
          only emits the generic task_status_changed).
        - step_start -> track the current step (for negotiation forwarding).
        - complete -> capture execution_history + step_outputs.
        - error -> record a STOPPED entry (for callers that check for it).
        """
        t = event.get("type")
        if t == "task_status_changed":
            d = event.get("data", {})
            try:
                status = TaskStatus(d.get("status", "pending"))
            except Exception:
                status = TaskStatus.PENDING
            self._set_psop_task_status(d.get("step"), d.get("subtask_index", 0), status)
            return [
                {"type": "psop_update", "data": {"psop": self.workflow.model_dump()}, "timestamp": time.time()},
                event,
            ]
        if t == "step_start":
            self._current_step_name = event.get("data", {}).get("step")
        elif t == "complete":
            d = event.get("data", {})
            self.execution_history = list(d.get("history", []))
            self.step_outputs = dict(d.get("step_outputs", {}))
        elif t == "error":
            d = event.get("data", {})
            if d.get("history"):
                self.execution_history = list(d.get("history", []))
            self.step_outputs = dict(d.get("step_outputs", {}))
            self._record_stop_event(d.get("error", "execution failed"), None)
        return event

    async def send_message_to_agent(self, agent_name: str, task: str, *, engine_client=None):
        """Send a message to an agent. Delegates to SDK WorkflowEngineClient.

        Returns the response text (string) for backward compat with callers
        and tests that mock this method.
        """
        client = engine_client or self._get_engine_client()
        result = await client.send_message_with_negotiation(
            agent_name, task,
            max_rounds=self._NEGOTIATION_MAX_ROUNDS,
            negotiation_resolver=self._negotiation_resolver,
        )
        # Preserve original contract: raise if negotiation did not converge.
        if result.task_state and "INPUT_REQUIRED" in result.task_state:
            raise RuntimeError(
                f"Negotiation with agent '{agent_name}' did not converge after "
                f"{self._NEGOTIATION_MAX_ROUNDS} round(s)."
            )
        return result.text or ""

    # ------------------------------------------------------------------
    # ControlPoint implementation (called by SDK WorkflowExecutor)
    # ------------------------------------------------------------------

    async def _dispatch_task(self, request, engine_client):
        """on_task: auto-send via self.send_message_to_agent.

        Events (agent_request/agent_response) are emitted by the SDK's
        WorkflowEngineClient around send_message; task_status_changed and
        psop_update are emitted/derived by the SDK runner + _shape_event.
        The facade only decides + delegates the actual send.
        """
        task_label = request.description or request.message
        try:
            response_text = await self.send_message_to_agent(
                request.agent_name, request.message, engine_client=engine_client)
            return TaskResponse(success=True, output=response_text)
        except Exception as e:
            err = f"Agent call failed : {str(e)}"
            logger.error(f"  >Task failed: {task_label} | Error: {err}")
            return TaskResponse(success=False, error=err)

    async def _route(self, step_name, results, conditions):
        """on_route: LLM-driven branch decision (preserved from original)."""
        sdk_step = self._find_sdk_step(step_name)
        next_name = await self._llm_route_decision(sdk_step, results)
        return RouteDecision(next_step=next_name)

    async def _handle_authorization(self, agent_name, auth_request):
        """on_authorization: approve by default.

        Events (authorization_request/authorization_resolved) are emitted by
        the SDK's AuthorizationTHandler around this callback; the ControlPoint
        only decides approve/deny. Override to apply a custom policy
        (e.g. prompt a human operator). Only invoked when the agent's
        AgentCard declares the Authorization-T extension.
        """
        return True

    async def _handle_notification(self, agent_name, notification):
        """on_notification: no-op default.

        The notification event is emitted by the SDK's NotificationTHandler
        around this callback; the ControlPoint only decides how to handle.
        Only invoked when the agent's AgentCard declares the Notification-T
        extension.
        """
        return None

    # ------------------------------------------------------------------
    # Event push (preserved contract for sse_executor frontend)
    # ------------------------------------------------------------------

    def _push_event(self, event_type: str, data: Dict[str, Any]):
        log_data = dict(data)
        for key in ("request", "response"):
            if isinstance(log_data.get(key), str):
                try:
                    log_data[key] = json.loads(log_data[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        try:
            serialized = json.dumps(log_data, indent=4, ensure_ascii=False, default=str)
        except Exception as e:
            logger.debug(f"Failed to serialize push event data: {e}")
            serialized = str(log_data)
        logger.info(f"push {event_type}:\n{serialized}")
        if self.push_callback:
            try:
                self.push_callback(event_type, data)
            except Exception as e:
                logger.error(f"Failed to push event: {e}")

    def _push_psop_update(self):
        try:
            psop_data = (
                self.workflow.model_dump_json()
                if hasattr(self.workflow, 'model_dump_json')
                else self.workflow.model_dump()
            )
        except Exception as e:
            logger.warning(f"Failed to serialize PSOP for event push: {e}")
            psop_data = str(self.workflow)
        self._push_event("psop_update", {"psop": psop_data})

    def _record_stop_event(self, reason, details):
        self.execution_history.append({
            "event": "STOPPED",
            "reason": reason,
            "details": details,
        })

    def _set_psop_task_status(self, step_name, subtask_index, status):
        for s in self.workflow.steps:
            if s.name == step_name:
                if 0 <= subtask_index < len(s.subtasks):
                    s.subtasks[subtask_index].status = status
                return

    # ------------------------------------------------------------------
    # LLM route decision (preserved from original engine)
    # ------------------------------------------------------------------

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
            if hasattr(current_step, 'step_type') and current_step.step_type is not None:
                step_type_val = current_step.step_type.value
            elif hasattr(current_step, 'type') and current_step.type is not None:
                step_type_val = current_step.type.value
            else:
                step_type_val = "AllSuccess"
        else:
            step_name, step_type_val = "(unknown)", "AllSuccess"
        prompt_template = f"""
# Role
You are a workflow logic controller. Your task is to determine the next step of the
workflow based on the task execution results and predefined conditions.

# Current Context
Current step: {step_name}
Step type: {step_type_val}

# Execution Results (Previous Step Output)
{results_text}

# Next Conditions (Required for Transition)
{next_conditions}

# Decision Logic
1. Analyze the Execution Results above.
2. Check whether any of the Next Conditions' "condition" descriptions are satisfied.
   - If a condition says e.g. "xx succeeded", check the results for evidence that xx succeeded.
   - An empty condition ('""') typically means unconditional transition to the next step.
3. If a condition is met, output the corresponding target step name.
4. If no condition is met, or the task execution contains an error, output "end".
5. If the result is ambiguous but appears successful, output "retry" to request manual intervention.

# Output Format
- Output exactly one word or phrase: the target step name (e.g. "step2"), "end", or "retry".
- Do NOT output any explanation, punctuation, or other characters.
"""
        if not self.llm_client:
            raise ValueError("LLM Client not initialized. Please set engine.llm_client.")
        try:
            _, decision = await asyncio.get_event_loop().run_in_executor(
                DynamicWorkflowEngine._llm_executor, self.llm_client.ask_llm, prompt_template
            )
            decision = decision.strip() if decision else ""
            if not decision:
                logger.error(f"LLM returned empty decision for step '{step_name}', defaulting to termination.")
                return "end"
            logger.info(f"LLM route decision for step '{step_name}': raw='{decision}', conditions={next_conditions}")
            if decision in ["end", "retry"]:
                return decision
            allowed_next = [jc.step for jc in next_list]
            allowed_lower = {n.lower(): n for n in allowed_next}
            if decision in allowed_next:
                return decision
            if decision.lower() in allowed_lower:
                logger.info(f"LLM step name '{decision}' case-normalized to '{allowed_lower[decision.lower()]}'")
                return allowed_lower[decision.lower()]
            else:
                logger.warning(f"LLM returned step '{decision}' not in declared next {allowed_next}, defaulting to termination.")
                return "end"
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return "end"

    # ------------------------------------------------------------------
    # Negotiation resolver (for SDK send_message_with_negotiation)
    # ------------------------------------------------------------------

    async def _negotiation_resolver(self, agent_name, negotiation_text, receive_result):
        """SDK negotiation_resolver callback: returns clarification text.

        Events (negotiation_request/resolved/failed) are emitted by the SDK's
        WorkflowEngineClient around this callback; the resolver only decides
        the clarification. Strategy: forward to direct DAG predecessors first;
        if no predecessor data, LLM-generate a clarification from context.
        """
        predecessor_data = await self._forward_to_predecessors(agent_name, negotiation_text)
        if predecessor_data:
            return predecessor_data
        receive_msg = receive_result.get("message", "") if isinstance(receive_result, dict) else ""
        clarification = await self._generate_negotiation_clarification(
            agent_name=agent_name,
            original_task="",
            negotiation_text=negotiation_text,
            receive_message=receive_msg,
        )
        return clarification or ""

    async def _forward_to_predecessors(self, agent_name, negotiation_text):
        """Forward negotiation request to direct DAG predecessors."""
        current_name = self._current_step_name
        if not current_name or self._sdk_workflow is None:
            return None
        workflow = self._sdk_workflow
        predecessor_names = []
        for s in workflow.steps:
            if s.next:
                for jc in s.next:
                    if jc.step == current_name and s.name != current_name:
                        predecessor_names.append(s.name)
                        break
        if not predecessor_names:
            logger.info(f"Step '{current_name}' has no predecessor steps, cannot forward")
            return None
        logger.info(
            f"Forwarding negotiation from '{agent_name}' (step '{current_name}') "
            f"to predecessors: {predecessor_names}"
        )
        collected = {}
        for pred_name in predecessor_names:
            prior_output = self.step_outputs.get(pred_name, {})
            prior_summary = json.dumps(prior_output, ensure_ascii=False, default=str)[:2000]
            pred_step = None
            for s in workflow.steps:
                if s.name == pred_name:
                    pred_step = s
                    break
            if not pred_step or not pred_step.subtasks:
                continue
            for task in pred_step.subtasks:
                pred_agent = task.agent
                if not pred_agent:
                    continue
                forward_msg = (
                    f"[Negotiation Request - Forwarded from Orchestrator]\n\n"
                    f"Agent '{agent_name}' is processing a follow-up task "
                    f"and indicates it needs additional data or clarification.\n\n"
                    f"The original output you provided for step '{pred_name}':\n"
                    f"---\n{prior_summary}\n---\n\n"
                    f"The request from '{agent_name}':\n"
                    f"---\n{negotiation_text}\n---\n\n"
                    f"As the predecessor agent, please provide supplemental data "
                    f"or clarification to help resolve this."
                )
                logger.info(f"Forwarding to predecessor '{pred_agent}' (step '{pred_name}')")
                try:
                    result = await self._get_engine_client().send_message(pred_agent, forward_msg)
                    if result and result.text:
                        collected[pred_agent] = result.text
                        logger.info(f"Got response from '{pred_agent}' ({len(result.text)} chars)")
                    else:
                        logger.warning(f"Empty response from '{pred_agent}'")
                except Exception as e:
                    logger.warning(f"Failed to contact predecessor '{pred_agent}': {e}")
        if not collected:
            logger.warning(f"No data collected from any predecessor agent")
            return None
        parts = [f"[Response from {a}]:\n{d}" for a, d in collected.items()]
        return "\n\n".join(parts)

    async def _generate_negotiation_clarification(self, agent_name, original_task,
                                                   negotiation_text, receive_message):
        if not self.llm_client:
            return (
                "Engine received your negotiation request and has reviewed the execution "
                "context. Please proceed with the original task using the clarification "
                "above. If you have specific questions, state them clearly."
            )
        workflow_context = self._build_clarification_context()
        lang_hint = "Respond in Chinese." if self.lang == "zh" else "Respond in English."
        prompt = f"""# Role
You are the orchestration engine's negotiation handler. An agent expressed uncertainty
or confusion about a task you assigned. Based on the completed workflow execution
context below, provide an accurate clarification or supplementary explanation.

# Important Constraints
- You may ONLY base your answer on the actual outputs in the "Executed Workflow Context" below.
  **Do NOT fabricate or speculate about facts that have not occurred.**
- If the context is insufficient to answer the agent's concern, tell the agent directly:
  "Insufficient information available. Please do your best with what you have."
- Be concise and focused on the specific concern the agent raised.

# Workflow Goal
{self.runtime_intent or "(not specified)"}

# Executed Workflow Context (completed steps and their outputs)
{workflow_context}

# Current Agent
{agent_name}

# Original Task
{original_task or "(see request message)"}

# Agent's Negotiation Request (the concern or question)
{negotiation_text}

# Supplementary Notes
{receive_message}

# Task
Based on the execution context above, provide a clear clarification to the agent.
Do NOT add any prefix markers like "Clarification:". {lang_hint}"""
        try:
            _, clarification = await asyncio.get_event_loop().run_in_executor(
                DynamicWorkflowEngine._llm_executor,
                self.llm_client.ask_llm,
                prompt,
            )
            clarification = clarification.strip() if clarification else ""
            if clarification:
                logger.info(f"Generated negotiation clarification for '{agent_name}': {clarification[:150]}...")
                return clarification
        except Exception as e:
            logger.error(f"LLM clarification failed: {e}")
        return (
            "Engine received your negotiation request. Please re-attempt the original "
            "task. If you have specific questions, state them clearly."
        )

    def _build_clarification_context(self):
        if not self.step_outputs:
            return "(no completed steps yet)"
        steps = self._sdk_workflow.steps if self._sdk_workflow else self.workflow.steps
        parts = []
        for step in steps:
            name = getattr(step, 'name', None)
            if not name or name not in self.step_outputs:
                continue
            outputs = self.step_outputs[name]
            parts.append(f"### {name}")
            for task_desc, output in outputs.items():
                text = output if isinstance(output, str) else str(output)
                parts.append(f"- Task: {task_desc}")
                parts.append(f"  Output: {text}")
        return "\n".join(parts) if parts else "(no completed steps yet)"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_sdk_step(self, step_name):
        if self._sdk_workflow is None:
            return None
        for s in self._sdk_workflow.steps:
            if s.name == step_name:
                return s
        return None


atexit.register(DynamicWorkflowEngine._shutdown_executor)
