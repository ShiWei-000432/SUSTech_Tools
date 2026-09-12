"""仅使用操作系统 Keychain 保存可选 CAS 密码。"""

from __future__ import annotations

from .exceptions import CredentialStoreError


SERVICE_NAME = "SUSTech TIS 选课助手"


class KeychainCredentialStore:
    def save_password(self, username: str, password: str) -> None:
        try:
            import keyring

            keyring.set_password(SERVICE_NAME, username, password)
        except Exception as error:
            raise CredentialStoreError("无法写入 macOS Keychain") from error

    def get_password(self, username: str) -> str:
        try:
            import keyring

            password = keyring.get_password(SERVICE_NAME, username)
        except Exception as error:
            raise CredentialStoreError("无法读取 macOS Keychain") from error
        if not password:
            raise CredentialStoreError("Keychain 中没有该学号的已保存密码")
        return password

    def delete_password(self, username: str) -> None:
        try:
            import keyring
        except Exception as error:
            raise CredentialStoreError("无法连接 macOS Keychain") from error
        try:
            keyring.delete_password(SERVICE_NAME, username)
        except keyring.errors.PasswordDeleteError:
            return
        except Exception as error:
            raise CredentialStoreError("无法删除 macOS Keychain 密码") from error
