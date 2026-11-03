"""The YouTube uploader against a fake Google: what it sends, and that it can only ever send private."""

import io
import json
import urllib.error
from pathlib import Path

import pytest

from storyrender import youtube

CREDS = {"client_id": "id", "client_secret": "secret", "refresh_token": "refresh"}


class _Resp(io.BytesIO):
    def __init__(self, body=b"", headers=None):
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Google:
    def __init__(self, fail_upload=None):
        self.requests, self.fail_upload = [], fail_upload

    def __call__(self, req, timeout=0):
        self.requests.append(req)
        if req.full_url == youtube.TOKEN_URL:
            return _Resp(json.dumps({"access_token": "tok"}).encode())
        if req.full_url == youtube.UPLOAD_URL:
            if self.fail_upload:
                raise urllib.error.HTTPError(req.full_url, self.fail_upload, "no", {}, io.BytesIO(b'{"error":"quotaExceeded"}'))
            return _Resp(headers={"Location": "https://upload.example/session"})
        if req.full_url == "https://upload.example/session":
            return _Resp(json.dumps({"id": "abc123", "status": {"privacyStatus": "private"}}).encode())
        if req.full_url == youtube.CHANNELS_URL:
            return _Resp(json.dumps({"items": [{"snippet": {"title": "Storyworld"}}]}).encode())
        raise AssertionError(req.full_url)


def test_metadata_is_private_and_states_the_kids_declaration_and_clips_the_title():
    meta = youtube.metadata("  The Last Onion " + "x" * 200, "d")
    assert meta["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "embeddable": True}
    assert len(meta["snippet"]["title"]) == youtube.MAX_TITLE and meta["snippet"]["title"].startswith("The Last Onion")
    with pytest.raises(youtube.YouTubeError, match="title"):
        youtube.metadata("  ")


def test_upload_refreshes_the_token_opens_a_session_then_puts_the_file(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake-mp4")
    google = _Google()

    out = youtube.upload(video, youtube.metadata("T"), CREDS, opener=google)

    assert out == {"id": "abc123", "url": "https://www.youtube.com/watch?v=abc123", "privacy": "private"}
    token, start, put = google.requests
    assert b"grant_type=refresh_token" in token.data and b"refresh_token=refresh" in token.data
    assert start.get_header("Authorization") == "Bearer tok" and json.loads(start.data)["status"]["privacyStatus"] == "private"
    assert start.get_header("X-upload-content-length") == "8" and put.data == b"fake-mp4" and put.get_method() == "PUT"


def test_anything_but_private_is_refused_before_any_request(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    meta = youtube.metadata("T")
    meta["status"]["privacyStatus"] = "public"
    google = _Google()
    with pytest.raises(youtube.YouTubeError, match="only makes private"):
        youtube.upload(video, meta, CREDS, opener=google)
    assert google.requests == []


def test_a_quota_error_surfaces_with_googles_words(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    with pytest.raises(youtube.YouTubeError, match="HTTP 403.*quotaExceeded"):
        youtube.upload(video, youtube.metadata("T"), CREDS, opener=_Google(fail_upload=403))


def test_check_names_the_channel_without_uploading():
    google = _Google()
    assert youtube.check(CREDS, opener=google) == {"token": "refreshed", "channel": "Storyworld"}
    assert all(r.full_url != youtube.UPLOAD_URL for r in google.requests)


def test_missing_credentials_name_what_to_set():
    with pytest.raises(youtube.YouTubeError, match="YOUTUBE_REFRESH_TOKEN"):
        youtube.credentials({"YOUTUBE_CLIENT_ID": "a", "YOUTUBE_CLIENT_SECRET": "b"})
    assert youtube.credentials({"YOUTUBE_CLIENT_ID": "a", "YOUTUBE_CLIENT_SECRET": "b", "YOUTUBE_REFRESH_TOKEN": "c"})["refresh_token"] == "c"


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(youtube.YouTubeError, match="no such file"):
        youtube.upload(Path(tmp_path / "nope.mp4"), youtube.metadata("T"), CREDS, opener=_Google())
