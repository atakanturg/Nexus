"""
nexus.providers.google_workspace
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Google Workspace user provisioning via the Admin SDK Directory API.

Credentials are loaded from a service-account JSON key file; the
``delegated_admin`` address is used for domain-wide delegation.
"""

from __future__ import annotations

import logging
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from core.exceptions import (
    ProviderAuthError,
    ProviderConflictError,
    ProviderError,
    ProviderNotFoundError,
    RetryableProviderError,
)
from core.schema import TenantConfig, UserPayload
from providers.base import BaseProvider

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.user",
    "https://www.googleapis.com/auth/admin.directory.group",
]


class GoogleWorkspaceProvider(BaseProvider):
    """Google Workspace (Admin SDK) provisioning provider."""

    PROVIDER_NAME = "google_workspace"

    def __init__(self, tenant_config: TenantConfig, *, dry_run: bool = False) -> None:
        super().__init__(tenant_config, dry_run=dry_run)
        self._service = self._build_service()

    def _build_service(self) -> Any:
        """Construct an authenticated Admin SDK service object."""
        sa_file = self._config.google_service_account_file
        admin_email = self._config.google_delegated_admin

        if not sa_file or not admin_email:
            self._log.warning(
                "Google Workspace credentials incomplete — "
                "provider will fail on API calls."
            )
            return None

        credentials = service_account.Credentials.from_service_account_file(
            sa_file, scopes=_SCOPES
        )
        delegated = credentials.with_subject(admin_email)
        return build("admin", "directory_v1", credentials=delegated, cache_discovery=False)

    # ── ABC implementation ───────────────────────────────────────────

    def provision(self, user: UserPayload) -> dict[str, Any]:
        """Create a Google Workspace user account.

        The user body follows the Admin SDK ``users.insert`` schema.
        """
        self._log.info("Provisioning Google Workspace for %s", user.email)

        if self._service is None:
            raise ProviderError(
                "Google Workspace service not initialised (missing credentials)",
                provider=self.PROVIDER_NAME,
            )

        user_body = {
            "primaryEmail": user.email,
            "name": {
                "givenName": user.first_name,
                "familyName": user.last_name,
            },
            "password": self._generate_temp_password(),
            "changePasswordAtNextLogin": True,
            "orgUnitPath": f"/{user.department}" if user.department else "/",
            "externalIds": [
                {"type": "organization", "value": user.user_id},
            ],
        }

        result = self._api_call(
            "users.insert",
            self._service.users().insert,
            body=user_body,
        )

        return {
            "status": "provisioned",
            "google_id": result.get("id") if isinstance(result, dict) else None,
            "primary_email": user.email,
        }

    def deprovision(self, user: UserPayload) -> dict[str, Any]:
        """Suspend (not delete) a Google Workspace user."""
        self._log.info("Deprovisioning Google Workspace for %s", user.email)

        if self._service is None:
            raise ProviderError(
                "Google Workspace service not initialised (missing credentials)",
                provider=self.PROVIDER_NAME,
            )

        # Suspend rather than delete — preserves data for compliance.
        update_body = {"suspended": True, "suspensionReason": "nexus_offboarding"}

        self._api_call(
            "users.update",
            self._service.users().update,
            userKey=user.email,
            body=update_body,
        )

        return {"status": "deprovisioned", "primary_email": user.email, "suspended": True}

    def sync_state(self) -> dict[str, Any]:
        """List all users in the domain for drift detection."""
        self._log.info("Syncing Google Workspace state for %s", self._config.domain)

        if self._service is None:
            raise ProviderError(
                "Google Workspace service not initialised (missing credentials)",
                provider=self.PROVIDER_NAME,
            )

        result = self._api_call(
            "users.list",
            self._service.users().list,
            domain=self._config.domain,
            maxResults=500,
            orderBy="email",
        )

        users_list = result.get("users", []) if isinstance(result, dict) else []
        return {
            "total_users": len(users_list),
            "users": [
                {
                    "email": u.get("primaryEmail"),
                    "suspended": u.get("suspended", False),
                    "id": u.get("id"),
                }
                for u in users_list
            ],
        }

    def health_check(self) -> bool:
        """Verify we can authenticate and list at least one user."""
        if self._service is None:
            self._log.error("Google service not initialised (missing creds).")
            return False
        try:
            result = self._api_call(
                "users.list",
                self._service.users().list,
                domain=self._config.domain,
                maxResults=1,
            )
            return bool(result)
        except ProviderError:
            return False

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _generate_temp_password() -> str:
        """Generate a random temporary password.

        In production, integrate with a secrets manager or send a
        password-reset link instead.
        """
        import secrets
        import string

        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return "".join(secrets.choice(alphabet) for _ in range(24))

    # ── Exception translation ────────────────────────────────────────

    def _translate_exception(self, operation: str, exc: Exception) -> None:
        if isinstance(exc, HttpError):
            status = exc.resp.status if exc.resp else None

            if status == 409:
                raise ProviderConflictError(
                    f"[google] Resource conflict on {operation}",
                    provider="google_workspace",
                    status_code=409,
                ) from exc
            if status == 404:
                raise ProviderNotFoundError(
                    f"[google] Not found on {operation}",
                    provider="google_workspace",
                    status_code=404,
                ) from exc
            if status in {401, 403}:
                raise ProviderAuthError(
                    f"[google] Auth failure on {operation}",
                    provider="google_workspace",
                    status_code=status,
                ) from exc
            if status == 429:
                raise RetryableProviderError(
                    f"[google] Rate limited on {operation}",
                    provider="google_workspace",
                    status_code=429,
                ) from exc
            if status and status >= 500:
                raise RetryableProviderError(
                    f"[google] Server error on {operation}",
                    provider="google_workspace",
                    status_code=status,
                ) from exc

            raise ProviderError(
                f"[google] API error on {operation}: {exc}",
                provider="google_workspace",
                status_code=status,
            ) from exc

        super()._translate_exception(operation, exc)
