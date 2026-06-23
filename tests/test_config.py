import pytest

from src.config import AppConfig, ConfigError, RuntimeSettings, load_app_config, load_dotenv_values
from src.config import resolve_r2_bucket
from src.d1 import build_d1_store
from src.raw_archive import build_raw_archive_client


def test_runtime_settings_default_to_requested_apify_actor():
    app_config = AppConfig(
        apify_token="token",
        openrouter_api_key="openrouter",
        google_client_secrets_path=None, google_token_path=None,
        spreadsheet_id=None,
        output_folder_id=None,
        asset_root_folder_id=None,
        notify_email="test@example.com",
    )

    settings = RuntimeSettings.from_sheet({}, app_config)

    assert settings.apify_actor_id == "apify/instagram-post-scraper"


def test_load_app_config_reads_values_from_dotenv_file(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "APIFY_TOKEN=test-apify",
                "OPENROUTER_API_KEY=test-openrouter",
                'GOOGLE_CLIENT_SECRETS_FILE=client_secrets.json',
                "NOTIFY_EMAIL=test@example.com",
                "R2_ACCOUNT_ID=test-account",
                "R2_BUCKET=faiv-raw",
                "R2_ACCESS_KEY_ID=test-r2-key",
                "R2_SECRET_ACCESS_KEY=test-r2-secret",
                "CLOUDFLARE_ACCOUNT_ID=cf-account",
                "CLOUDFLARE_API_TOKEN=cf-token",
                "CLOUDFLARE_D1_DATABASE_ID=d1-db-id",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRETS_FILE", raising=False)
    monkeypatch.delenv("NOTIFY_EMAIL", raising=False)

    config = load_app_config()

    assert config.apify_token == "test-apify"
    assert config.openrouter_api_key == "test-openrouter"
    assert config.google_client_secrets_path is not None
    assert config.notify_email == "test@example.com"
    assert config.r2_bucket == "faiv-raw"
    assert config.r2_access_key_id == "test-r2-key"
    assert config.r2_secret_access_key == "test-r2-secret"
    assert config.r2_endpoint == "https://test-account.r2.cloudflarestorage.com"
    assert config.cloudflare_account_id == "cf-account"
    assert config.cloudflare_api_token == "cf-token"
    assert config.cloudflare_d1_database_id == "d1-db-id"


def test_load_dotenv_values_strips_utf8_bom_from_first_key(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("\ufeffAPIFY_TOKEN=test-apify\n", encoding="utf-8")

    values = load_dotenv_values(dotenv)

    assert values["APIFY_TOKEN"] == "test-apify"


def test_load_app_config_can_require_only_apify_for_collect_only(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "APIFY_TOKEN=test-apify",
                "R2_BUCKET=faiv-raw",
                "R2_ACCOUNT_ID=test-account",
                "R2_ACCESS_KEY_ID=test-r2-key",
                "R2_SECRET_ACCESS_KEY=test-r2-secret",
                "CLOUDFLARE_ACCOUNT_ID=cf-account",
                "CLOUDFLARE_API_TOKEN=cf-token",
                "CLOUDFLARE_D1_DATABASE_ID=d1-db-id",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRETS_FILE", raising=False)

    config = load_app_config(required_secrets=("APIFY_TOKEN",))

    assert config.apify_token == "test-apify"
    assert config.openrouter_api_key == ""
    assert config.google_client_secrets_path is None


def test_build_raw_archive_client_rejects_bucket_that_looks_like_endpoint():
    app_config = AppConfig(
        apify_token="token",
        openrouter_api_key="openrouter",
        google_client_secrets_path=None, google_token_path=None,
        spreadsheet_id=None,
        output_folder_id=None,
        asset_root_folder_id=None,
        notify_email="test@example.com",
        r2_bucket="example-bucket.1234567890.r2.cloudflarestorage.com",
        r2_endpoint="https://1234567890.r2.cloudflarestorage.com",
        r2_access_key_id="key",
        r2_secret_access_key="secret",
    )

    with pytest.raises(ConfigError, match="R2_BUCKET"):
        build_raw_archive_client(app_config)


def test_build_d1_store_requires_complete_cloudflare_config_when_any_value_is_present():
    app_config = AppConfig(
        apify_token="token",
        openrouter_api_key="openrouter",
        google_client_secrets_path=None, google_token_path=None,
        spreadsheet_id=None,
        output_folder_id=None,
        asset_root_folder_id=None,
        notify_email="test@example.com",
        cloudflare_account_id="cf-account",
        cloudflare_api_token=None,
        cloudflare_d1_database_id=None,
    )

    with pytest.raises(ConfigError, match="CLOUDFLARE_API_TOKEN"):
        build_d1_store(app_config)


def test_resolve_r2_bucket_does_not_infer_bucket_from_endpoint_host_only():
    bucket = resolve_r2_bucket(
        {
            "R2_ENDPOINT": "https://example-account.r2.cloudflarestorage.com",
        }
    )

    assert bucket is None


