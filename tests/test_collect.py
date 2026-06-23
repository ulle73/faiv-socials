from datetime import datetime, timezone

from src.collect import ApifyCollector, build_actor_input, dedupe_posts, normalize_post_item
from src.models import CollectedPost, SourceAccount


def test_dedupe_posts_keeps_only_new_urls():
    posts = [
        CollectedPost(
            source_handle="ekstralys.no",
            post_url="https://example.com/post-1",
            published_at="2026-06-23T07:00:00+02:00",
            caption="Första",
            post_type="image",
            media_urls=["https://example.com/a.jpg"],
            hook_signal="Första",
            batch_date="2026-06-23",
        ),
        CollectedPost(
            source_handle="ekstralys.no",
            post_url="https://example.com/post-2",
            published_at="2026-06-23T07:00:00+02:00",
            caption="Andra",
            post_type="image",
            media_urls=["https://example.com/b.jpg"],
            hook_signal="Andra",
            batch_date="2026-06-23",
        ),
    ]

    result = dedupe_posts(posts, existing_urls={"https://example.com/post-1"})

    assert [post.post_url for post in result] == ["https://example.com/post-2"]


def test_build_actor_input_uses_username_list_and_results_limit_for_batch_scraper():
    source = SourceAccount(
        priority=1,
        tier="1",
        company_name="FAIV",
        raw_lookup="@f.a.i.v.ab",
        lookup_term="@f.a.i.v.ab",
        country="Sverige",
        faiv_categories=["Kundbyggen"],
        frequency="Dagligen",
        comment="",
        handle="f.a.i.v.ab",
        active=True,
    )
    second_source = SourceAccount(
        priority=2,
        tier="1",
        company_name="Lumen",
        raw_lookup="@lumensystems",
        lookup_term="@lumensystems",
        country="Norge",
        faiv_categories=["Rätt val"],
        frequency="Dagligen",
        comment="",
        handle="lumensystems",
        active=True,
    )

    payload = build_actor_input([source, second_source], posts_per_account=5)

    assert payload == {
        "dataDetailLevel": "basicData",
        "resultsLimit": 5,
        "skipPinnedPosts": False,
        "username": ["f.a.i.v.ab", "lumensystems"],
    }


def test_collect_posts_for_sources_uses_single_batch_request_and_marks_missing_sources():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "ownerUsername": "f.a.i.v.ab",
                    "ownerFullName": "Fordonsanpassning i Väst AB",
                    "caption": "Första posten",
                    "url": "https://www.instagram.com/p/post-1/",
                    "timestamp": "2026-06-23T07:00:00.000Z",
                    "type": "Image",
                    "displayUrl": "https://example.com/post-1.jpg",
                }
            ]

    class FakeSession:
        def __init__(self):
            self.calls = []

        def post(self, url, params, json, timeout):
            self.calls.append(
                {
                    "url": url,
                    "params": params,
                    "json": json,
                    "timeout": timeout,
                }
            )
            return FakeResponse()

    first_source = SourceAccount(
        priority=1,
        tier="1",
        company_name="FAIV",
        raw_lookup="@f.a.i.v.ab",
        lookup_term="@f.a.i.v.ab",
        country="Sverige",
        faiv_categories=["Kundbyggen"],
        frequency="Dagligen",
        comment="",
        handle="f.a.i.v.ab",
        active=True,
    )
    second_source = SourceAccount(
        priority=2,
        tier="1",
        company_name="Lumen",
        raw_lookup="@lumensystems",
        lookup_term="@lumensystems",
        country="Norge",
        faiv_categories=["Rätt val"],
        frequency="Dagligen",
        comment="",
        handle="lumensystems",
        active=True,
    )
    session = FakeSession()
    collector = ApifyCollector(api_token="token", actor_id="apify/instagram-post-scraper", session=session)

    outcome = collector.collect_posts_for_sources(
        [first_source, second_source],
        posts_per_account=5,
        batch_date="2026-06-23",
        existing_urls=set(),
        throttle_seconds=0,
    )

    assert len(session.calls) == 1
    assert session.calls[0]["json"]["username"] == ["f.a.i.v.ab", "lumensystems"]
    assert [post.source_handle for post in outcome.posts] == ["f.a.i.v.ab"]
    assert first_source.status == "ok"
    assert first_source.last_fetched == "2026-06-23"
    assert second_source.status == "tom"


def test_collect_posts_for_sources_archives_raw_payload_and_tracks_archive_key():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "ownerUsername": "f.a.i.v.ab",
                    "ownerFullName": "Fordonsanpassning i Väst AB",
                    "caption": "Första posten",
                    "url": "https://www.instagram.com/p/post-1/",
                    "timestamp": "2026-06-23T07:00:00.000Z",
                    "type": "Image",
                    "displayUrl": "https://example.com/post-1.jpg",
                }
            ]

    class FakeSession:
        def post(self, url, params, json, timeout):
            return FakeResponse()

    class FakeArchive:
        def __init__(self):
            self.calls = []

        def archive_apify_payload(self, *, items, actor_id, batch_date, source_handles):
            self.calls.append(
                {
                    "items": items,
                    "actor_id": actor_id,
                    "batch_date": batch_date,
                    "source_handles": source_handles,
                }
            )
            return "apify/raw/2026/06/23/test.json.gz"

    source = SourceAccount(
        priority=1,
        tier="1",
        company_name="FAIV",
        raw_lookup="@f.a.i.v.ab",
        lookup_term="@f.a.i.v.ab",
        country="Sverige",
        faiv_categories=["Kundbyggen"],
        frequency="Dagligen",
        comment="",
        handle="f.a.i.v.ab",
        active=True,
    )
    archive = FakeArchive()
    collector = ApifyCollector(
        api_token="token",
        actor_id="apify/instagram-post-scraper",
        session=FakeSession(),
        raw_archive=archive,
    )

    outcome = collector.collect_posts_for_sources(
        [source],
        posts_per_account=5,
        batch_date="2026-06-23",
        existing_urls=set(),
        throttle_seconds=0,
    )

    assert archive.calls == [
        {
            "items": [
                {
                    "ownerUsername": "f.a.i.v.ab",
                    "ownerFullName": "Fordonsanpassning i Väst AB",
                    "caption": "Första posten",
                    "url": "https://www.instagram.com/p/post-1/",
                    "timestamp": "2026-06-23T07:00:00.000Z",
                    "type": "Image",
                    "displayUrl": "https://example.com/post-1.jpg",
                }
            ],
            "actor_id": "apify~instagram-post-scraper",
            "batch_date": "2026-06-23",
            "source_handles": ["f.a.i.v.ab"],
        }
    ]
    assert outcome.raw_archive_key == "apify/raw/2026/06/23/test.json.gz"
    assert outcome.posts[0].raw_archive_key == "apify/raw/2026/06/23/test.json.gz"


def test_collect_posts_for_sources_marks_sources_blocked_when_raw_archive_fails():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "ownerUsername": "f.a.i.v.ab",
                    "url": "https://www.instagram.com/p/post-1/",
                }
            ]

    class FakeSession:
        def post(self, url, params, json, timeout):
            return FakeResponse()

    class FailingArchive:
        def archive_apify_payload(self, *, items, actor_id, batch_date, source_handles):
            raise RuntimeError("R2-arkivering misslyckades")

    source = SourceAccount(
        priority=1,
        tier="1",
        company_name="FAIV",
        raw_lookup="@f.a.i.v.ab",
        lookup_term="@f.a.i.v.ab",
        country="Sverige",
        faiv_categories=["Kundbyggen"],
        frequency="Dagligen",
        comment="",
        handle="f.a.i.v.ab",
        active=True,
    )
    collector = ApifyCollector(
        api_token="token",
        actor_id="apify/instagram-post-scraper",
        session=FakeSession(),
        raw_archive=FailingArchive(),
    )

    outcome = collector.collect_posts_for_sources(
        [source],
        posts_per_account=5,
        batch_date="2026-06-23",
        existing_urls=set(),
        throttle_seconds=0,
    )

    assert outcome.posts == []
    assert outcome.blocked_accounts == []
    assert outcome.raw_archive_key is None
    assert "R2-arkivering misslyckades" in outcome.warnings[0]
    assert source.status == "fel"


def test_normalize_post_item_extracts_analysis_fields_from_apify_basic_data():
    source = SourceAccount(
        priority=1,
        tier="1",
        company_name="FAIV",
        raw_lookup="@f.a.i.v.ab",
        lookup_term="@f.a.i.v.ab",
        country="Sverige",
        faiv_categories=["Kundbyggen"],
        frequency="Dagligen",
        comment="",
        handle="f.a.i.v.ab",
        active=True,
    )

    post = normalize_post_item(
        source,
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
        },
        batch_date="2026-06-23",
        raw_archive_key="apify/raw/test.json.gz",
        run_id="run-123",
        collected_at=datetime(2026, 6, 23, 17, 45, 47, tzinfo=timezone.utc),
    )

    assert post.instagram_post_id == "3922784827972436843"
    assert post.short_code == "DZwiARplsNr"
    assert post.owner_id == "12345"
    assert post.owner_username == "f.a.i.v.ab"
    assert post.owner_full_name == "Fordonsanpassning i Väst AB"
    assert post.likes_count == 7
    assert post.comments_count == 2
    assert post.engagement_count == 9
    assert post.hashtags == ["FAIV", "Test"]
    assert post.hashtag_count == 2
    assert post.dimensions_width == 1080
    assert post.dimensions_height == 1080
    assert post.is_image is True
    assert post.is_carousel is False
    assert post.is_video is False
    assert post.has_cta is True
    assert post.has_emoji is True
    assert post.has_question is False
    assert post.caption_first_line == "Hör av dig till oss 😀"
    assert post.caption_length == len("Hör av dig till oss 😀\n#FAIV #Test")
    assert post.published_age_hours_at_collect == 106
