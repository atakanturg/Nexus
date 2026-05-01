"""
nexus.providers.notion_provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Notion integration via the ``notion-client`` SDK.

Provisioning creates a page in the tenant's onboarding database to
track onboarding checklists, welcome docs, and task assignments.
Deprovisioning archives the page.
"""

from __future__ import annotations

import logging
from typing import Any

from notion_client import Client as NotionClient
from notion_client.errors import APIResponseError

from core.exceptions import (
    ProviderAuthError,
    ProviderError,
    ProviderNotFoundError,
    RetryableProviderError,
)
from core.schema import TenantConfig, UserPayload
from providers.base import BaseProvider

logger = logging.getLogger(__name__)


class NotionProvider(BaseProvider):
    """Notion provisioning provider."""

    PROVIDER_NAME = "notion"

    def __init__(self, tenant_config: TenantConfig, *, dry_run: bool = False) -> None:
        super().__init__(tenant_config, dry_run=dry_run)
        self._client = NotionClient(auth=tenant_config.notion_token or "")
        self._onboarding_db_id = tenant_config.notion_onboarding_db_id

    # ── ABC implementation ───────────────────────────────────────────

    def provision(self, user: UserPayload) -> dict[str, Any]:
        """Create an onboarding page for the user in Notion."""
        self._log.info("Provisioning Notion page for %s", user.email)

        if not self._onboarding_db_id:
            self._log.warning("No onboarding DB configured — skipping Notion.")
            return {"status": "provisioned", "skipped": True, "reason": "no_db_configured"}

        page_properties = {
            "Name": {"title": [{"text": {"content": user.display_name}}]},
            "Email": {"email": user.email},
            "Role": {"select": {"name": user.role}},
            "User ID": {"rich_text": [{"text": {"content": user.user_id}}]},
            "Status": {"select": {"name": "Onboarding"}},
        }

        if user.department:
            page_properties["Department"] = {
                "select": {"name": user.department},
            }

        if user.start_date:
            page_properties["Start Date"] = {
                "date": {"start": user.start_date.isoformat()},
            }

        result = self._api_call(
            "pages.create",
            self._client.pages.create,
            parent={"database_id": self._onboarding_db_id},
            properties=page_properties,
        )

        page_id = result.get("id") if isinstance(result, dict) else None
        return {"status": "provisioned", "notion_page_id": page_id}

    def deprovision(self, user: UserPayload) -> dict[str, Any]:
        """Archive the user's onboarding page."""
        self._log.info("Deprovisioning Notion page for %s", user.email)

        if not self._onboarding_db_id:
            return {"status": "deprovisioned", "skipped": True, "reason": "no_db_configured"}

        # Find the page by querying the DB for the user's email.
        page_id = self._find_page_by_email(user.email)
        if not page_id:
            self._log.warning("No Notion page found for %s — nothing to archive.", user.email)
            return {"status": "deprovisioned", "already_absent": True}

        self._api_call(
            "pages.update",
            self._client.pages.update,
            page_id=page_id,
            archived=True,
        )

        return {"status": "deprovisioned", "notion_page_id": page_id, "archived": True}

    def sync_state(self) -> dict[str, Any]:
        """Query all pages in the onboarding database."""
        self._log.info("Syncing Notion state for tenant %s", self._config.tenant_id)

        if not self._onboarding_db_id:
            return {"pages": [], "skipped": True}

        result = self._api_call(
            "databases.query",
            self._client.databases.query,
            database_id=self._onboarding_db_id,
        )

        pages = result.get("results", []) if isinstance(result, dict) else []
        return {
            "total_pages": len(pages),
            "pages": [
                {
                    "id": p.get("id"),
                    "archived": p.get("archived", False),
                }
                for p in pages
            ],
        }

    def health_check(self) -> bool:
        """Verify the Notion token by listing the authenticated user."""
        try:
            result = self._api_call("users.me", self._client.users.me)
            return bool(result)
        except ProviderError:
            return False

    # ── Internal helpers ─────────────────────────────────────────────

    def _find_page_by_email(self, email: str) -> str | None:
        """Query the onboarding DB for a page matching *email*."""
        query_filter = {
            "property": "Email",
            "email": {"equals": email},
        }

        try:
            result = self._api_call(
                "databases.query",
                self._client.databases.query,
                database_id=self._onboarding_db_id,
                filter=query_filter,
            )
            results = result.get("results", []) if isinstance(result, dict) else []
            if results:
                return results[0]["id"]
            return None
        except ProviderError as exc:
            self._log.error("Failed to query Notion for %s: %s", email, exc)
            return None

    # ── Exception translation ────────────────────────────────────────

    def _translate_exception(self, operation: str, exc: Exception) -> None:
        if isinstance(exc, APIResponseError):
            status = exc.status

            if status == 404:
                raise ProviderNotFoundError(
                    f"[notion] Not found on {operation}",
                    provider="notion",
                    status_code=404,
                ) from exc
            if status in {401, 403}:
                raise ProviderAuthError(
                    f"[notion] Auth failure on {operation}",
                    provider="notion",
                    status_code=status,
                ) from exc
            if status == 429:
                raise RetryableProviderError(
                    f"[notion] Rate limited on {operation}",
                    provider="notion",
                    status_code=429,
                ) from exc
            if status and status >= 500:
                raise RetryableProviderError(
                    f"[notion] Server error on {operation}",
                    provider="notion",
                    status_code=status,
                ) from exc

            raise ProviderError(
                f"[notion] API error on {operation}: {exc}",
                provider="notion",
                status_code=status,
            ) from exc

        super()._translate_exception(operation, exc)
