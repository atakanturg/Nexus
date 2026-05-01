import pytest
from unittest.mock import MagicMock, patch

from core.schema import TenantConfig, UserPayload
from providers.notion_provider import NotionProvider

@pytest.fixture
def mock_tenant_config():
    return TenantConfig(
        tenant_id="ACME",
        domain="acme.com",
        org_name="Acme Corp",
        notion_enabled=True,
        notion_token="secret_notion_token",
        notion_onboarding_db_id="db_12345"
    )

@pytest.fixture
def mock_user():
    return UserPayload(
        user_id="u-001",
        email="test@acme.com",
        first_name="Test",
        last_name="User",
        role="engineering"
    )

@patch("providers.notion_provider.NotionClient")
def test_provision_success(mock_client_cls, mock_tenant_config, mock_user):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.pages.create.return_value = {"id": "page_123"}
    
    provider = NotionProvider(mock_tenant_config)
    result = provider.provision(mock_user)
    
    assert result["status"] == "provisioned"
    assert result["notion_page_id"] == "page_123"
    mock_client.pages.create.assert_called_once()
    
    # Check that it uses the correct schema
    kwargs = mock_client.pages.create.call_args[1]
    assert kwargs["parent"] == {"database_id": "db_12345"}
    assert "Role" in kwargs["properties"]
    assert "Status" in kwargs["properties"]

@patch("providers.notion_provider.NotionClient")
def test_health_check_success(mock_client_cls, mock_tenant_config):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.users.me.return_value = {"id": "bot_123"}
    
    provider = NotionProvider(mock_tenant_config)
    assert provider.health_check() is True

@patch("providers.notion_provider.NotionClient")
def test_health_check_failure(mock_client_cls, mock_tenant_config):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    
    from core.exceptions import ProviderError
    
    mock_client.users.me.side_effect = ProviderError("notion auth error", provider="notion")
    
    provider = NotionProvider(mock_tenant_config)
    assert provider.health_check() is False
