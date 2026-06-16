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

from typing import List

from a2a.client.interceptors import ClientCallInterceptor, BeforeArgs, AfterArgs
from a2a.client.client import ClientCallContext
from a2a.extensions.common import HTTP_EXTENSION_HEADER, get_requested_extensions
from loguru import logger


class ExtensionInterceptor(ClientCallInterceptor):
    """An interceptor that adds A2A extension URIs from the AgentCard to the HTTP headers.

    Reads the agent's declared extensions (from capabilities.extensions[].uri) and
    sets the A2A-Extensions header so the server knows which extensions the client supports.

    Uses the official a2a-sdk `get_requested_extensions()` utility for safe URI
    merging and deduplication, per the A2A protocol specification.
    """

    def __init__(self, extension_uris: List[str]):
        self._uris = list(extension_uris) if extension_uris else []

    async def before(self, args: BeforeArgs) -> None:
        if not self._uris:
            return

        if args.context is None:
            args.context = ClientCallContext()

        if args.context.service_parameters is None:
            args.context.service_parameters = {}

        existing = args.context.service_parameters.get(HTTP_EXTENSION_HEADER, "")
        existing_values = [existing] if existing else []
        merged = sorted(get_requested_extensions([*existing_values, *self._uris]))
        args.context.service_parameters[HTTP_EXTENSION_HEADER] = ",".join(merged)

        logger.debug(
            f"[Extensions] Set {HTTP_EXTENSION_HEADER}={args.context.service_parameters[HTTP_EXTENSION_HEADER]}"
        )

    async def after(self, args: AfterArgs) -> None:
        pass
