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

from samples.agents.negotiation_base_agent import NegotiationBaseAgentExecutor
from loguru import logger


SPN_DOMAIN_PROMPT = """
You are an SPN Domain Agent simulator for City1 (Shanghai) OMC.
You receive a private-line fault diagnosis task for the Shanghai area.
Based on the received task, simulate a diagnosis result.

IMPORTANT: Shanghai side has a FAULT. Your response must include:

1. 诊断结果类型: 诊断成功
2. 诊断结果详细信息: 上海地市OMC诊断结果 - 端口Down, 光功率-28dBm(低于阈值), 存在故障
3. 修复方案: 更换上海侧OMC端口光模块, 恢复端口Down状态。此修复方案需要人工授权后执行。
   修复方案字段: needs_authorization=true, risk_level=medium
4. 故障根因列表:
   - 故障根因名称: 上海侧OMC端口光模块故障
   - 详细描述: 客户A上海-广州间专线中断, 上海OMC告警端口Down, 光功率-28dBm低于正常阈值
   - 修复建议: 更换上海侧OMC端口光模块, 需要人工授权后执行
   - 资源对象标识: port-shanghai-omc-01
   - 资源对象类型: 端口
   - 资源对象名称: 上海OMC端口01
   - 详细位置: 上海地市OMC机房

Format your response in Chinese as a structured diagnosis report.

Task content: {task}
"""


class SpnDomainAgentExecutor(NegotiationBaseAgentExecutor):

    def __init__(self) -> None:
        super().__init__(agent_prompt_template=SPN_DOMAIN_PROMPT)
