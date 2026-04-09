# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
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

import os
import sys
import zipfile
from datetime import timezone, datetime

from loguru import logger
from pathlib import Path

from common.util.config_util import get_root_path

root_path = get_root_path()
_LOG_DIR = Path(root_path) / "log"
_LOG_DIR.mkdir(exist_ok=True)
os.chmod(_LOG_DIR, 0o700)

LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} - {name} - {level} - {message}"


def add_module_logger(module_prefix: str):
    def compress_and_set_permission(source_file):
        zip_file = Path(str(source_file) + ".zip")

        try:
            with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(source_file, arcname=Path(source_file).name)

            os.chmod(zip_file, 0o440)

            os.remove(source_file)
            return zip_file
        except Exception as e:
            logger.error(f"add_module_logger error: {e}")
            return None

    logger.configure(extra={"request_id": ''})
    logger.remove()
    old_mask = os.umask(0o027)
    try:
        logger.add(sys.stdout, format=LOG_FORMAT, level="INFO", backtrace=False, colorize=True)

        logger.add(
            _LOG_DIR / f"{module_prefix}_log_{{time:YYYY-MM-DD}}.log",
            format=LOG_FORMAT,
            level="INFO",
            rotation=lambda message, file: (
                    os.stat(file.name).st_size > 10 * 1024 * 1024
                    or datetime.now(tz=timezone.utc).date() != datetime.fromtimestamp(
                os.path.getctime(file.name)).date()
            ),
            retention="30 days",
            compression=compress_and_set_permission,
            encoding="utf-8",
            enqueue=True,
        )

    finally:
        os.umask(old_mask)
