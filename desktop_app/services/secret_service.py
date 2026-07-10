import keyring

SERVICE_NAME = "ATRI_QQBOT"

class SecretService:
    @staticmethod
    def get_secret(key: str) -> str:
        try:
            return keyring.get_password(SERVICE_NAME, key) or ""
        except Exception:
            return ""

    @staticmethod
    def set_secret(key: str, value: str) -> None:
        value = (value or "").strip()
        try:
            if value:
                keyring.set_password(SERVICE_NAME, key, value)
            else:
                SecretService.delete_secret(key)
        except Exception:
            pass

    @staticmethod
    def delete_secret(key: str) -> None:
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except keyring.errors.PasswordDeleteError:
            pass
        except Exception:
            pass
