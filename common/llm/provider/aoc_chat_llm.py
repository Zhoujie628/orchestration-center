# common/llm/provider/aoc_chat_llm.py

import json
from typing import Dict, Any, Tuple

from common.llm.config.llm_config import LLMType, LLMConfig
from common.llm.provider.aoc_base_llm import AOCBaseLLM
from common.llm.provider.llm_provider_registry import registry_provider


@registry_provider(LLMType.AOC_CHAT_LLM)
class AOCChatLLM(AOCBaseLLM):
    """AOC 对话模型（如 Qwen3_32B）"""

    def __init__(self, llm_config: LLMConfig):
        super().__init__(llm_config)
        # 可从 extra 读取自定义模板，否则用默认格式
        extra = llm_config.config_item.extra
        self.request_template = extra.get('request_template')

    def _build_request_body(self, prompt: str) -> Dict[str, Any]:
        if self.request_template and isinstance(self.request_template, str):
            # 支持模板字符串
            template_str = self.request_template.replace(
                '{prompt}', json.dumps(prompt)[1:-1]
            )
            template_str = template_str.replace(
                '{enable_thinking}', str(self.enable_thinking).lower()
            )
            return json.loads(template_str)
        else:
            body = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
            }
            if self.enable_thinking:
                body["chat_template_kwargs"] = {"enable_thinking": True}
            return body

    def _parse_response(self, data: Dict[str, Any]) -> Tuple[str, str]:
        # 标准 OpenAI 格式解析
        try:
            choice = data.get('choices', [{}])[0]
            message = choice.get('message', {})
            reasoning = message.get('reasoning_content', '') or ''
            answer = message.get('content', '') or ''
            if not answer:
                answer = data.get('text', '') or json.dumps(data, ensure_ascii=False)
            return reasoning, answer
        except Exception as e:
            # 解析失败，返回原始 JSON 作为 answer
            return '', json.dumps(data, ensure_ascii=False)