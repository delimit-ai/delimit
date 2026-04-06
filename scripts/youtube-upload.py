#!/usr/bin/env python3
"""Upload an MP4 video to YouTube as a Short (unlisted by default).

Usage:
    python3 youtube-upload.py <mp4_path> [--title TITLE] [--description DESC] [--privacy PRIVACY]

Reads OAuth credentials from:
    /root/.delimit/secrets/youtube-oauth-client.json  (client_id, client_secret)
    /root/.delimit/secrets/youtube-tokens.json         (refresh_token, access_token)

Tokens are refreshed automatically when expired.
"""

import argparse
import json
import os
import sys

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKENS_PATH = "/root/.delimit/secrets/youtube-tokens.json"
CLIENT_PATH = "/root/.delimit/secrets/youtube-oauth-client.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def load_credentials():
    """Build OAuth2 credentials from stored tokens + client secrets."""
    with open(TOKENS_PATH) as f:
        tokens = json.load(f)
    with open(CLIENT_PATH) as f:
        client_raw = json.load(f)

    # Handle both wrapped {"installed": {...}} and flat formats.
    client = client_raw.get("installed") or client_raw.get("web") or client_raw

    creds = Credentials(
        token=tokens.get("access_token"),
        refresh_token=tokens["refresh_token"],
        token_uri=client.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client["client_id"],
        client_secret=client["client_secret"],
        scopes=SCOPES,
    )

    # Force a refresh so we always have a valid access token.
    if creds.expired or not creds.token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        # Persist the refreshed token for future use.
        tokens["access_token"] = creds.token
        with open(TOKENS_PATH, "w") as f:
            json.dump(tokens, f)
        print("[youtube-upload] Access token refreshed.", file=sys.stderr)

    return creds


def upload(mp4_path, title, description, privacy="unlisted"):
    """Upload mp4_path to YouTube and return the video URL."""
    if not os.path.isfile(mp4_path):
        print(f"Error: file not found: {mp4_path}", file=sys.stderr)
        sys.exit(1)

    creds = load_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    # Ensure #Shorts tag is in the description for YouTube Shorts detection.
    if "#Shorts" not in description:
        description = f"{description}\n\n#Shorts"

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["delimit", "api-governance", "developer-tools", "shorts"],
            "categoryId": "28",  # Science & Technology
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        mp4_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10 MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    print(f"[youtube-upload] Uploading {mp4_path} ...", file=sys.stderr)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"[youtube-upload] {pct}% uploaded", file=sys.stderr)

    video_id = response["id"]
    url = f"https://youtu.be/{video_id}"
    print(f"[youtube-upload] Upload complete.", file=sys.stderr)
    print(f"[youtube-upload] Video URL: {url}", file=sys.stderr)
    # Print bare URL to stdout for scripting.
    print(url)
    return url


def main():
    parser = argparse.ArgumentParser(description="Upload MP4 to YouTube")
    parser.add_argument("mp4_path", help="Path to the MP4 file")
    parser.add_argument("--title", default="Delimit Demo", help="Video title")
    parser.add_argument(
        "--description",
        default="API governance in action with Delimit CLI.",
        help="Video description",
    )
    parser.add_argument(
        "--privacy",
        default="unlisted",
        choices=["public", "unlisted", "private"],
        help="Privacy status (default: unlisted)",
    )
    args = parser.parse_args()
    upload(args.mp4_path, args.title, args.description, args.privacy)


if __name__ == "__main__":
    main()
