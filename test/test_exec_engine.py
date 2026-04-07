# tests/test_exec_engine.py
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock, Mock
from a2a.types import AgentCard

from framework.runtime.exec_engine import DynamicWorkflowEngine
from framework.orchestration.model.psop import PSOP, Step, Subtask, Condition, TaskStatus


@pytest.fixture
def mock_llm():
    """模拟LLM客户端"""
    mock = MagicMock()
    mock.ask_llm.return_value = ("prompt", "step2")
    return mock


@pytest.fixture
def sample_psop():
    """创建示例PSOP"""
    return PSOP(
        id="test-psop",
        name="Test Workflow",
        description="A test workflow",
        steps=[
            Step(
                name="step1",
                type=MagicMock(value="action"),
                subtasks=[
                    Subtask(
                        agent="agent1",
                        skill="search",
                        description="Search for info"
                    )
                ],
                next=[Condition(step="step2", condition="success")]
            ),
            Step(
                name="step2",
                type=MagicMock(value="action"),
                subtasks=[],
                next=[]
            )
        ]
    )


@pytest.fixture
def sample_agent_cards():
    """创建示例AgentCard列表"""
    card = AgentCard(
        name="agent1",
        description="Test agent",
        url="http://test.com",
        version="1.0"
    )
    return [card]


@pytest.fixture
def engine(sample_psop, sample_agent_cards, mock_llm):
    """创建引擎实例"""
    with patch('framework.runtime.exec_engine.get_or_create_deepseek_llm_instance', return_value=mock_llm):
        eng = DynamicWorkflowEngine(sample_psop, sample_agent_cards)
        eng.llm_client = mock_llm
        return eng


class TestEngineInit:
    """测试引擎初始化"""

    def test_init_basic(self, sample_psop, sample_agent_cards, mock_llm):
        """测试基本初始化"""
        with patch('framework.runtime.exec_engine.get_or_create_deepseek_llm_instance', return_value=mock_llm):
            engine = DynamicWorkflowEngine(sample_psop, sample_agent_cards)

            assert engine.workflow == sample_psop
            assert engine.current_step_idx == 0
            assert engine.execution_history == []
            assert engine.agent_cards == sample_agent_cards
            assert engine.push_callback is None


class TestSetPushCallback:
    """测试 set_push_callback 方法"""

    def test_set_callback(self, engine):
        """测试设置回调函数"""
        callback = MagicMock()
        engine.set_push_callback(callback)
        assert engine.push_callback == callback


class TestPushEvent:
    """测试 _push_event 方法"""

    def test_push_with_callback(self, engine):
        """测试有回调时推送事件"""
        callback = MagicMock()
        engine.set_push_callback(callback)

        engine._push_event("test_event", {"key": "value"})

        callback.assert_called_once_with("test_event", {"key": "value"})

    def test_push_without_callback(self, engine):
        """测试无回调时不报错"""
        engine._push_event("test_event", {"key": "value"})
        # 应该静默执行，不抛出异常

    def test_push_callback_error(self, engine):
        """测试回调执行出错时记录日志"""
        callback = MagicMock(side_effect=Exception("Callback error"))
        engine.set_push_callback(callback)

        # 不应该抛出异常
        engine._push_event("test_event", {})


class TestRun:
    """测试 run 方法"""

    @pytest.mark.asyncio
    async def test_run_complete(self, engine):
        """测试工作流完整执行"""
        # 模拟单步执行成功并结束
        with patch.object(engine, '_execute_single_step', new_callable=AsyncMock) as mock_step:
            mock_step.side_effect = [None, None]  # 两步执行

            result = await engine.run()

            assert mock_step.call_count == 2
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_run_with_exception(self, engine):
        """测试执行过程中抛出异常"""
        with patch.object(engine, '_execute_single_step', new_callable=AsyncMock) as mock_step:
            mock_step.side_effect = Exception("Unexpected error")

            with pytest.raises(Exception, match="Unexpected error"):
                await engine.run()


class TestSendMessageToAgent:
    """测试 send_message_to_agent 方法"""

    @pytest.mark.asyncio
    async def test_send_agent_not_found(self, engine):
        """测试Agent不存在"""
        with pytest.raises(RuntimeError, match="未找到Agent"):
            await engine.send_message_to_agent("nonexistent_agent", "task")

    @pytest.mark.asyncio
    async def test_send_success(self, engine, sample_agent_cards):
        """测试成功发送消息"""
        # 模拟A2A客户端
        with patch('framework.runtime.exec_engine.ClientFactory') as MockFactory, \
                patch('framework.runtime.exec_engine.create_text_message_object') as mock_create:
            mock_client = AsyncMock()
            mock_factory_instance = MockFactory.return_value
            mock_factory_instance.create.return_value = mock_client

            # 模拟流式响应
            mock_task = MagicMock()
            mock_task.artifacts = [MagicMock()]
            mock_response = (mock_task, {})

            async def mock_send(msg):
                yield mock_response

            mock_client.send_message = mock_send

            mock_create.return_value = MagicMock()

            result = await engine.send_message_to_agent("agent1", "test task")

            assert result is not None

    @pytest.mark.asyncio
    async def test_send_timeout(self, engine):
        """测试请求超时"""
        import httpx
        with patch('framework.runtime.exec_engine.ClientFactory') as MockFactory:
            mock_client = AsyncMock()
            MockFactory.return_value.create.return_value = mock_client

            async def mock_timeout(msg):
                raise httpx.TimeoutException("Timeout")

            mock_client.send_message = mock_timeout

            with pytest.raises(RuntimeError, match="timed out"):
                await engine.send_message_to_agent("agent1", "task")

    @pytest.mark.asyncio
    async def test_send_connect_error(self, engine):
        """测试连接错误"""
        import httpx
        with patch('framework.runtime.exec_engine.ClientFactory') as MockFactory:
            mock_client = AsyncMock()
            MockFactory.return_value.create.return_value = mock_client

            async def mock_connect_error(msg):
                raise httpx.ConnectError("Connection failed")

            mock_client.send_message = mock_connect_error

            with pytest.raises(RuntimeError, match="Faild to connect"):
                await engine.send_message_to_agent("agent1", "task")


class TestExecuteSubtasks:
    """测试 _execute_subtasks 方法"""

    @pytest.mark.asyncio
    async def test_execute_success(self, engine):
        """测试子任务执行成功"""
        step = engine.workflow.steps[0]

        with patch.object(engine, 'send_message_to_agent', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = "Agent response"

            results, success = await engine._execute_subtasks(step)

            assert success is True
            assert "Search for info" in results
            assert results["Search for info"] == "Agent response"

    @pytest.mark.asyncio
    async def test_execute_failure(self, engine):
        """测试子任务执行失败"""
        step = engine.workflow.steps[0]

        with patch.object(engine, 'send_message_to_agent', new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception("Agent error")

            results, success = await engine._execute_subtasks(step)

            assert success is False
            assert step.subtasks[0].status == TaskStatus.FAILED


class TestLlmRouteDecision:
    """测试 _llm_route_decision 方法"""

    def test_decision_goto_next(self, engine):
        """测试决定跳转到下一步"""
        step = engine.workflow.steps[0]
        task_result = {"Search for info": "Success"}

        engine.llm_client.ask_llm.return_value = ("prompt", "step2")

        result = engine._llm_route_decision(step, task_result)
        assert result == "step2"

    def test_decision_end(self, engine):
        """测试决定结束流程"""
        step = engine.workflow.steps[0]
        task_result = {"Search for info": {"error": "Failed"}}

        engine.llm_client.ask_llm.return_value = ("prompt", "end")

        result = engine._llm_route_decision(step, task_result)
        assert result == "end"

    def test_decision_retry(self, engine):
        """测试决定重试"""
        step = engine.workflow.steps[0]
        task_result = {"Search for info": "Unclear result"}

        engine.llm_client.ask_llm.return_value = ("prompt", "retry")

        result = engine._llm_route_decision(step, task_result)
        assert result == "retry"

    def test_decision_invalid_step_name(self, engine):
        """测试返回无效的步骤名时默认结束"""
        step = engine.workflow.steps[0]
        task_result = {"Search for info": "Success"}

        engine.llm_client.ask_llm.return_value = ("prompt", "invalid_step")

        result = engine._llm_route_decision(step, task_result)
        assert result == "end"

    def test_decision_llm_error(self, engine):
        """测试LLM调用失败时默认结束"""
        step = engine.workflow.steps[0]
        task_result = {}

        engine.llm_client.ask_llm.side_effect = Exception("LLM error")

        result = engine._llm_route_decision(step, task_result)
        assert result == "end"

    def test_decision_no_llm_client(self, sample_psop, sample_agent_cards):
        """测试未初始化LLM客户端"""
        with patch('framework.runtime.exec_engine.get_or_create_deepseek_llm_instance'):
            eng = DynamicWorkflowEngine(sample_psop, sample_agent_cards)
            eng.llm_client = None

            with pytest.raises(ValueError, match="LLM Client not initialized"):
                eng._llm_route_decision(sample_psop.steps[0], {})


class TestFindStepIndex:
    """测试 _find_step_index 方法"""

    def test_find_existing_step(self, engine):
        """测试找到已存在的步骤"""
        idx = engine._find_step_index("step2")
        assert idx == 1

    def test_find_nonexistent_step(self, engine):
        """测试查找不存在的步骤"""
        idx = engine._find_step_index("nonexistent")
        assert idx is None


class TestProcessLlmDecision:
    """测试 _process_llm_decision 方法"""

    @pytest.mark.asyncio
    async def test_process_end_decision(self, engine):
        """测试处理结束决策"""
        step = engine.workflow.steps[0]

        await engine._process_llm_decision(step, "end")

        assert engine.current_step_idx == len(engine.workflow.steps)

    @pytest.mark.asyncio
    async def test_process_goto_decision(self, engine):
        """测试处理跳转决策"""
        step = engine.workflow.steps[0]

        await engine._process_llm_decision(step, "step2")

        assert engine.current_step_idx == 1

    @pytest.mark.asyncio
    async def test_process_invalid_target(self, engine):
        """测试处理无效目标步骤"""
        step = engine.workflow.steps[0]

        await engine._process_llm_decision(step, "invalid_step")

        # 应该终止流程
        assert engine.current_step_idx == len(engine.workflow.steps)


class TestExecuteSingleStep:
    """测试 _execute_single_step 方法"""

    @pytest.mark.asyncio
    async def test_execute_step_success(self, engine):
        """测试成功执行单步"""
        with patch.object(engine, '_execute_subtasks', new_callable=AsyncMock) as mock_sub, \
                patch.object(engine, '_process_llm_decision', new_callable=AsyncMock) as mock_llm:
            mock_sub.return_value = ({"task": "result"}, True)

            await engine._execute_single_step()

            mock_sub.assert_called_once()
            mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_step_failure(self, engine):
        """测试执行失败时记录停止事件"""
        with patch.object(engine, '_execute_subtasks', new_callable=AsyncMock) as mock_sub, \
                patch.object(engine, '_record_stop_event') as mock_record:
            mock_sub.return_value = ({"error": "failed"}, False)

            await engine._execute_single_step()

            mock_record.assert_called_once()
            # 应该跳转到末尾
            assert engine.current_step_idx == len(engine.workflow.steps)