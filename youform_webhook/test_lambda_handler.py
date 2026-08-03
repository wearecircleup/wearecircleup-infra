import lambda_handler as mod
from urllib.error import HTTPError


def test_store_submission_copies_signature_to_s3_and_persists_s3_reference(monkeypatch):
    saved: dict[str, object] = {}
    uploaded: dict[str, object] = {}

    class FakeTable:
        def put_item(self, Item):
            saved["Item"] = Item

    class FakeS3:
        def put_object(self, **kwargs):
            uploaded.update(kwargs)

    class FakeHeaders:
        def get_content_type(self):
            return "image/png"

    class FakeResponse:
        def __init__(self, content: bytes):
            self._content = content
            self.headers = FakeHeaders()

        def read(self):
            return self._content

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    parsed_body = {
        "submission_id": "2jgxyorbkf",
        "form_id": "iamr7tnj",
        "form_name": "Adult Authorization for Minor",
        "event_id": "5155b508-96d8-4b3a-b2eb-ec3fdc38ca5c",
        "event_type": "submission",
        "started_at": "2026-08-03T14:30:02.000000Z",
        "completed_at": "2026-08-03T15:32:33.000000Z",
        "answers": {
            "Nombre Completo": "Juan Mesa",
            "Firma para autorizar": "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png",
        },
    }

    monkeypatch.setenv("SUBMISSIONS_TABLE_NAME", "test-table")
    monkeypatch.setenv("SIGNATURES_BUCKET_NAME", "test-signatures")
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeTable())
    monkeypatch.setattr(mod, "_s3_client", lambda: FakeS3())
    monkeypatch.setattr(mod, "urlopen", lambda request, timeout=20: FakeResponse(b"png-binary"))

    stored = mod._store_submission(parsed_body)

    assert stored is True
    assert uploaded == {
        "Bucket": "test-signatures",
        "Key": "youform-signatures/2jgxyorbkf/signature.png",
        "Body": b"png-binary",
        "ContentType": "image/png",
    }
    assert saved["Item"] == {
        "pk": "SUBMISSION#2jgxyorbkf",
        "sk": "SUBMISSION#2jgxyorbkf",
        "submission_id": "2jgxyorbkf",
        "form_id": "iamr7tnj",
        "form_name": "Adult Authorization for Minor",
        "event_id": "5155b508-96d8-4b3a-b2eb-ec3fdc38ca5c",
        "event_type": "submission",
        "started_at": "2026-08-03T14:30:02.000000Z",
        "completed_at": "2026-08-03T15:32:33.000000Z",
        "answers": [
            {"question": "Nombre Completo", "answer": "Juan Mesa"},
            {
                "question": "Firma para autorizar",
                "answer": "s3://test-signatures/youform-signatures/2jgxyorbkf/signature.png",
            },
        ],
    }


def test_store_submission_skips_without_submission_id(monkeypatch):
    monkeypatch.setenv("SUBMISSIONS_TABLE_NAME", "test-table")

    stored = mod._store_submission({"answers": {"Nombre Completo": "Juan"}})

    assert stored is False


def test_store_submission_keeps_original_signature_url_when_copy_fails(monkeypatch):
    saved: dict[str, object] = {}

    class FakeTable:
        def put_item(self, Item):
            saved["Item"] = Item

    parsed_body = {
        "submission_id": "2jgxyorbkf",
        "form_id": "iamr7tnj",
        "form_name": "Adult Authorization for Minor",
        "event_id": "5155b508-96d8-4b3a-b2eb-ec3fdc38ca5c",
        "event_type": "submission",
        "started_at": "2026-08-03T14:30:02.000000Z",
        "completed_at": "2026-08-03T15:32:33.000000Z",
        "answers": {
            "Firma para autorizar": "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png",
        },
    }

    monkeypatch.setenv("SUBMISSIONS_TABLE_NAME", "test-table")
    monkeypatch.setenv("SIGNATURES_BUCKET_NAME", "test-signatures")
    monkeypatch.setattr(mod, "_dynamodb_table", lambda table_name: FakeTable())

    def fail_download(_: str):
        raise HTTPError(
            "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png",
            403,
            "Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(mod, "_download_signature", fail_download)

    stored = mod._store_submission(parsed_body)

    assert stored is True
    assert saved["Item"]["answers"] == [
        {
            "question": "Firma para autorizar",
            "answer": "https://files.youform.com/signature-9ad1e753-b04a-47bb-b222-a02febabb170.png",
        }
    ]
