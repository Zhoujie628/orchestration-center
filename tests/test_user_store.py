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

from unittest.mock import MagicMock, patch

from database.utils import user_store


def _mock_conn():
    return MagicMock()


class TestCreateUser:
    def test_defaults_role_and_must_change_password(self):
        with patch.object(user_store, "create_connection", return_value=_mock_conn()), \
             patch.object(user_store, "execute_query", return_value=(None, None)) as mock_exec:
            assert user_store.create_user("alice", "pw") is True
            params = mock_exec.call_args[0][2]
            assert params[3] == "user"
            assert params[4] is False

    def test_passes_through_role_and_must_change_password(self):
        with patch.object(user_store, "create_connection", return_value=_mock_conn()), \
             patch.object(user_store, "execute_query", return_value=(None, None)) as mock_exec:
            assert user_store.create_user("admin", "pw", role="admin", must_change_password=True) is True
            params = mock_exec.call_args[0][2]
            assert params[3] == "admin"
            assert params[4] is True

    def test_returns_false_on_db_error(self):
        with patch.object(user_store, "create_connection", return_value=_mock_conn()), \
             patch.object(user_store, "execute_query", return_value=(None, RuntimeError("boom"))):
            assert user_store.create_user("alice", "pw") is False

    def test_returns_false_when_no_connection(self):
        with patch.object(user_store, "create_connection", return_value=None):
            assert user_store.create_user("alice", "pw") is False


class TestAuthenticateUser:
    def _row_for(self, password, salt="salt123", role="user", must_change_password=False):
        password_hash = user_store._hash_password(password, salt)
        return ("alice", password_hash, salt, role, must_change_password)

    def test_returns_user_dict_on_correct_password(self):
        row = self._row_for("correct-horse")
        with patch.object(user_store, "create_connection", return_value=_mock_conn()), \
             patch.object(user_store, "execute_query", return_value=([row], None)):
            result = user_store.authenticate_user("alice", "correct-horse")
            assert result == {"username": "alice", "role": "user", "must_change_password": False}

    def test_surfaces_must_change_password_true(self):
        row = self._row_for("OpenAN@2026", role="admin", must_change_password=True)
        with patch.object(user_store, "create_connection", return_value=_mock_conn()), \
             patch.object(user_store, "execute_query", return_value=([row], None)):
            result = user_store.authenticate_user("alice", "OpenAN@2026")
            assert result["must_change_password"] is True

    def test_returns_none_on_wrong_password(self):
        row = self._row_for("correct-horse")
        with patch.object(user_store, "create_connection", return_value=_mock_conn()), \
             patch.object(user_store, "execute_query", return_value=([row], None)):
            assert user_store.authenticate_user("alice", "wrong") is None

    def test_returns_none_when_user_not_found(self):
        with patch.object(user_store, "create_connection", return_value=_mock_conn()), \
             patch.object(user_store, "execute_query", return_value=([], None)):
            assert user_store.authenticate_user("nobody", "pw") is None


class TestUpdatePassword:
    def test_clears_must_change_password_flag(self):
        with patch.object(user_store, "create_connection", return_value=_mock_conn()), \
             patch.object(user_store, "execute_query", return_value=(None, None)) as mock_exec:
            assert user_store.update_password("alice", "new-pw") is True
            query = mock_exec.call_args[0][1]
            assert "must_change_password = FALSE" in query

    def test_returns_false_on_db_error(self):
        with patch.object(user_store, "create_connection", return_value=_mock_conn()), \
             patch.object(user_store, "execute_query", return_value=(None, RuntimeError("boom"))):
            assert user_store.update_password("alice", "new-pw") is False


class TestSeedAdminIfEmpty:
    def test_creates_admin_flagged_must_change_password(self):
        with patch.object(user_store, "has_any_user", return_value=False), \
             patch.object(user_store, "create_user", return_value=True) as mock_create:
            assert user_store.seed_admin_if_empty("hashed-default") is True
            mock_create.assert_called_once_with("admin", "hashed-default", "admin", must_change_password=True)

    def test_no_op_when_users_already_exist(self):
        with patch.object(user_store, "has_any_user", return_value=True), \
             patch.object(user_store, "create_user") as mock_create:
            assert user_store.seed_admin_if_empty("hashed-default") is False
            mock_create.assert_not_called()


class TestListUsers:
    def test_includes_must_change_password(self):
        rows = [("alice", "admin", True, "2026-01-01 00:00:00")]
        with patch.object(user_store, "create_connection", return_value=_mock_conn()), \
             patch.object(user_store, "execute_query", return_value=(rows, None)):
            result = user_store.list_users()
            assert result == [{
                "username": "alice", "role": "admin",
                "must_change_password": True, "created_at": "2026-01-01 00:00:00",
            }]
