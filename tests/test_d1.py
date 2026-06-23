from src.config import AppConfig
from src.d1 import CloudflareD1Store, build_d1_store
from src.models import CollectedPost


def test_build_d1_store_returns_none_when_cloudflare_d1_is_not_configured():
    app_config = AppConfig(
        apify_token="token",
        openrouter_api_key="openrouter",
        google_client_secrets_path=None, google_token_path=None,
        spreadsheet_id=None,
        output_folder_id=None,
        asset_root_folder_id=None,
        notify_email="test@example.com",
        smtp_host=None,
        smtp_port=587,
        smtp_username=None,
        smtp_password=None,
        smtp_from=None,
    )

    assert build_d1_store(app_config) is None


def test_get_existing_post_urls_filters_by_source_handles():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "result": [
                    {
                        "success": True,
                        "results": [
                            {"post_url": "https://example.com/post-1"},
                            {"post_url": "https://example.com/post-2"},
                        ],
                    }
                ],
            }

    class FakeSession:
        def __init__(self):
            self.calls = []

        def post(self, url, headers, json, timeout):
            self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return FakeResponse()

    session = FakeSession()
    store = CloudflareD1Store(
        account_id="cf-account",
        api_token="cf-token",
        database_id="d1-db-id",
        session=session,
    )

    result = store.get_existing_post_urls(["f.a.i.v.ab", "lumensystems"])

    assert result == {"https://example.com/post-1", "https://example.com/post-2"}
    assert len(session.calls) == 1
    query = session.calls[0]["json"]
    assert query["sql"].count("?") == 2
    assert query["params"] == ["f.a.i.v.ab", "lumensystems"]


def test_get_posts_for_run_returns_normalized_posts():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "result": [
                    {
                        "success": True,
                        "results": [
                            {
                                "instagram_post_id": "3922784827972436843",
                                "short_code": "DZwiARplsNr",
                                "owner_id": "12345",
                                "owner_username": "f.a.i.v.ab",
                                "owner_full_name": "Fordonsanpassning i Väst AB",
                                "source_handle": "f.a.i.v.ab",
                                "post_url": "https://www.instagram.com/p/post-1/",
                                "published_at": "2026-06-23T07:00:00.000Z",
                                "caption": "Testpost",
                                "post_type": "Image",
                                "media_urls_json": "[\"https://example.com/post-1.jpg\"]",
                                "hook_signal": "Testpost",
                                "batch_date": "2026-06-23",
                                "run_id": "run-123",
                                "raw_archive_key": "apify/raw/2026/06/23/test.json.gz",
                                "likes_count": 7,
                                "comments_count": 2,
                                "is_comments_disabled": 0,
                                "hashtags_json": "[\"FAIV\", \"Test\"]",
                                "dimensions_width": 1080,
                                "dimensions_height": 1080,
                                "engagement_count": 9,
                                "caption_length": 8,
                                "hashtag_count": 2,
                                "published_age_hours_at_collect": 12,
                                "caption_first_line": "Testpost",
                                "has_cta": 1,
                                "has_question": 0,
                                "has_emoji": 0,
                                "is_image": 1,
                                "is_carousel": 0,
                                "is_video": 0,
                            }
                        ],
                    }
                ],
            }

    class FakeSession:
        def post(self, url, headers, json, timeout):
            return FakeResponse()

    store = CloudflareD1Store(
        account_id="cf-account",
        api_token="cf-token",
        database_id="d1-db-id",
        session=FakeSession(),
    )

    posts = store.get_posts_for_run("run-123")

    assert posts == [
        CollectedPost(
            source_handle="f.a.i.v.ab",
            post_url="https://www.instagram.com/p/post-1/",
            published_at="2026-06-23T07:00:00.000Z",
            caption="Testpost",
            post_type="Image",
            media_urls=["https://example.com/post-1.jpg"],
            hook_signal="Testpost",
            batch_date="2026-06-23",
            raw_archive_key="apify/raw/2026/06/23/test.json.gz",
            raw_payload={},
            run_id="run-123",
            instagram_post_id="3922784827972436843",
            short_code="DZwiARplsNr",
            owner_id="12345",
            owner_username="f.a.i.v.ab",
            owner_full_name="Fordonsanpassning i Väst AB",
            likes_count=7,
            comments_count=2,
            is_comments_disabled=False,
            hashtags=["FAIV", "Test"],
            dimensions_width=1080,
            dimensions_height=1080,
            engagement_count=9,
            caption_length=8,
            hashtag_count=2,
            published_age_hours_at_collect=12,
            caption_first_line="Testpost",
            has_cta=True,
            has_question=False,
            has_emoji=False,
            is_image=True,
            is_carousel=False,
            is_video=False,
        )
    ]


def test_sync_run_posts_from_raw_archive_upserts_enriched_post_metrics():
    class FakeResponse:
        def __init__(self, responses):
            self._responses = responses

        def raise_for_status(self):
            return None

        def json(self):
            return self._responses.pop(0)

    class FakeSession:
        def __init__(self):
            self.calls = []
            self.responses = [
                {
                    "success": True,
                    "result": [
                        {
                            "success": True,
                            "results": [
                                {
                                    "run_date": "2026-06-23",
                                    "raw_archive_key": "apify/raw/test.json.gz",
                                }
                            ],
                        }
                    ],
                },
                {"success": True, "result": [{"success": True, "results": []}]},
            ]

        def post(self, url, headers, json, timeout):
            self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return FakeResponse(self.responses)

    store = CloudflareD1Store(
        account_id="cf-account",
        api_token="cf-token",
        database_id="d1-db-id",
        session=FakeSession(),
    )

    store.sync_run_posts_from_raw_archive(
        "run-123",
        {
            "archived_at": "2026-06-23T17:45:47+00:00",
            "items": [
                {
                    "id": "3922784827972436843",
                    "shortCode": "DZwiARplsNr",
                    "ownerId": "12345",
                    "ownerUsername": "f.a.i.v.ab",
                    "ownerFullName": "Fordonsanpassning i Väst AB",
                    "caption": "Hör av dig till oss 😀\n#FAIV #Test",
                    "url": "https://www.instagram.com/p/DZwiARplsNr/",
                    "timestamp": "2026-06-19T07:00:14.000Z",
                    "type": "Image",
                    "displayUrl": "https://example.com/post-1.jpg",
                    "likesCount": 7,
                    "commentsCount": 2,
                    "isCommentsDisabled": False,
                    "hashtags": ["FAIV", "Test"],
                    "dimensionsHeight": 1080,
                    "dimensionsWidth": 1080,
                }
            ],
        },
    )

    batch = store.session.calls[1]["json"]["batch"]
    params = batch[0]["params"]
    assert params[10] == "3922784827972436843"
    assert params[15] == 7
    assert params[16] == 2
    assert params[18] == "[\"FAIV\", \"Test\"]"
    assert params[21] == 9
