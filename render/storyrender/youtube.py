"""Upload a finished video to YouTube as a PRIVATE video (Data API v3 `videos.insert`, resumable upload). Standard library only.

Private is not a default here, it is the only thing this module will do: a person publishes from YouTube Studio after watching
it. Credentials come from the environment, never a file in the repo:

    YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN   (an OAuth client of type Desktop; scope youtube.upload)

`check` refreshes the token and asks which channel it is (needs the broader `youtube.readonly` scope, else it only proves the
token refreshes), so the credentials can be tried without uploading anything. Uploads need a user's OAuth: a service account
can't upload to YouTube.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true"
PRIVACY = "private"  # not a parameter
MAX_TITLE = 100
MAX_DESCRIPTION = 5000


class YouTubeError(RuntimeError):
    pass


def _request(opener, req: urllib.request.Request):
    try:
        return opener(req, timeout=300)
    except urllib.error.HTTPError as e:
        raise YouTubeError(f"YouTube returned HTTP {e.code}: {e.read()[:500].decode('utf-8', 'replace')}") from e
    except urllib.error.URLError as e:
        raise YouTubeError(f"can't reach Google: {e.reason}") from e


def credentials(env=os.environ) -> dict:
    missing = [k for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN") if not env.get(k)]
    if missing:
        raise YouTubeError(f"set {', '.join(missing)} in the environment (see the module docstring)")
    return {"client_id": env["YOUTUBE_CLIENT_ID"], "client_secret": env["YOUTUBE_CLIENT_SECRET"], "refresh_token": env["YOUTUBE_REFRESH_TOKEN"]}


def access_token(creds: dict, *, opener=urllib.request.urlopen) -> str:
    body = urllib.parse.urlencode({**creds, "grant_type": "refresh_token"}).encode()
    with _request(opener, urllib.request.Request(TOKEN_URL, data=body, method="POST")) as resp:
        token = json.load(resp).get("access_token")
    if not token:
        raise YouTubeError("Google returned no access token")
    return token


def metadata(title: str, description: str = "", tags: list[str] | None = None, *, made_for_kids: bool = False) -> dict:
    """The `videos.insert` body: always private, and the made-for-kids declaration YouTube requires, stated, not defaulted by Google."""
    if not title.strip():
        raise YouTubeError("a title is required")
    return {
        "snippet": {"title": title.strip()[:MAX_TITLE], "description": description[:MAX_DESCRIPTION], "tags": tags or [], "categoryId": "22"},
        "status": {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": made_for_kids, "embeddable": True},
    }


def upload(video: Path, meta: dict, creds: dict, *, opener=urllib.request.urlopen) -> dict:
    """Upload `video` with `meta` (from :func:`metadata`). Returns {id, url, privacy}. Refuses anything not private."""
    if meta.get("status", {}).get("privacyStatus") != PRIVACY:
        raise YouTubeError("this uploader only makes private videos")
    if not video.is_file():
        raise YouTubeError(f"no such file {video}")
    token = access_token(creds, opener=opener)
    size = video.stat().st_size
    start = urllib.request.Request(
        UPLOAD_URL,
        data=json.dumps(meta).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
    )
    with _request(opener, start) as resp:
        session = resp.headers.get("Location")
    if not session:
        raise YouTubeError("YouTube gave no upload session")
    put = urllib.request.Request(session, data=video.read_bytes(), method="PUT", headers={"Content-Type": "video/mp4", "Content-Length": str(size)})
    with _request(opener, put) as resp:
        done = json.load(resp)
    vid = done.get("id")
    if not vid:
        raise YouTubeError(f"the upload finished without a video id: {done}")
    return {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "privacy": done.get("status", {}).get("privacyStatus", PRIVACY)}


def check(creds: dict, *, opener=urllib.request.urlopen) -> dict:
    """Try the credentials without uploading: refresh the token, then (if the scope allows) name the channel."""
    token = access_token(creds, opener=opener)
    try:
        with _request(opener, urllib.request.Request(CHANNELS_URL, headers={"Authorization": f"Bearer {token}"})) as resp:
            items = json.load(resp).get("items") or []
        return {"token": "refreshed", "channel": items[0]["snippet"]["title"] if items else None}
    except YouTubeError as e:
        return {"token": "refreshed", "channel": None, "note": f"couldn't read the channel (an upload-only scope can't): {e}"}
