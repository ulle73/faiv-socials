from src.workflow_guard import build_failure_message, notify_failure


def test_build_failure_message_includes_failed_job_and_run_url():
    message = build_failure_message(
        {
            "WORKFLOW_NAME": "FAIV Daily Run",
            "REPOSITORY": "ulle73/faiv-socials",
            "SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "123456789",
            "FAILED_JOB": "run-pipeline",
        }
    )

    assert "**GitHub Actions misslyckades**" in message
    assert "Jobb: run-pipeline" in message
    assert "Repo: ulle73/faiv-socials" in message
    assert "Run: https://github.com/ulle73/faiv-socials/actions/runs/123456789" in message


def test_notify_failure_posts_to_discord(monkeypatch):
    calls = {}

    class FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout):
        calls["url"] = req.full_url
        calls["timeout"] = timeout
        calls["body"] = req.data.decode("utf-8")
        return FakeResponse()

    monkeypatch.setattr("src.workflow_guard.request.urlopen", fake_urlopen)

    exit_code = notify_failure(
        {
            "DISCORD_WEBHOOK_URL": "https://discord.example/webhook",
            "WORKFLOW_NAME": "FAIV Daily Run",
            "REPOSITORY": "ulle73/faiv-socials",
            "SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "123456789",
            "FAILED_JOB": "run-pipeline",
        }
    )

    assert exit_code == 0
    assert calls["url"] == "https://discord.example/webhook"
    assert calls["timeout"] == 30
    assert "run-pipeline" in calls["body"]
