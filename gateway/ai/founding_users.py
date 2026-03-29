"""Founding User tracker — manages the 25 founding user slots.

Monitors Supabase for new signups, sends welcome emails,
tracks slots remaining, and manages the 12-month term.
"""
import json
import smtplib
import imaplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime, timezone

SECRETS_DIR = Path.home() / ".delimit" / "secrets"
FOUNDING_USERS_FILE = Path.home() / ".delimit" / "founding_users.json"
MAX_FOUNDING_USERS = 25
SMTP_HOST = "mail.spacemail.com"
SMTP_PORT = 465
IMAP_HOST = "mail.spacemail.com"
EMAIL = "pro@delimit.ai"


def _load_creds():
    """Load email credentials."""
    return {"email": EMAIL, "password": "***REDACTED***"}


def _load_founding_users() -> dict:
    """Load founding users registry."""
    if FOUNDING_USERS_FILE.exists():
        return json.loads(FOUNDING_USERS_FILE.read_text())
    return {"users": [], "created_at": datetime.now(timezone.utc).isoformat()}


def _save_founding_users(data: dict):
    """Save founding users registry."""
    FOUNDING_USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    FOUNDING_USERS_FILE.write_text(json.dumps(data, indent=2))


def get_status() -> dict:
    """Get founding user program status."""
    data = _load_founding_users()
    users = data.get("users", [])
    return {
        "total_slots": MAX_FOUNDING_USERS,
        "claimed": len(users),
        "remaining": MAX_FOUNDING_USERS - len(users),
        "users": [{"email": u["email"], "name": u.get("name", ""), "joined": u["joined_at"]} for u in users],
    }


def register_founding_user(email: str, name: str = "", github_username: str = "") -> dict:
    """Register a new founding user."""
    data = _load_founding_users()
    users = data.get("users", [])

    if len(users) >= MAX_FOUNDING_USERS:
        return {"error": "All 25 founding user spots are claimed.", "remaining": 0}

    if any(u["email"] == email for u in users):
        return {"error": "Already registered as a founding user.", "email": email}

    user = {
        "email": email,
        "name": name,
        "github_username": github_username,
        "joined_at": datetime.now(timezone.utc).isoformat(),
        "term_months": 12,
        "status": "active",
    }
    users.append(user)
    data["users"] = users
    _save_founding_users(data)

    # Send welcome email
    try:
        _send_welcome_email(email, name)
    except Exception:
        pass  # Don't fail registration if email fails

    return {
        "registered": True,
        "email": email,
        "slot": len(users),
        "remaining": MAX_FOUNDING_USERS - len(users),
    }


def _send_welcome_email(to_email: str, name: str = ""):
    """Send welcome email to new founding user."""
    creds = _load_creds()
    greeting = f"Hi {name}," if name else "Hi,"

    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto; background: #0a0a1a; color: #e5e7eb; padding: 40px; border-radius: 12px;">
        <div style="text-align: center; margin-bottom: 32px;">
            <span style="font-size: 32px; font-weight: 800; background: linear-gradient(135deg, #3b82f6, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                &lt;/&gt; Delimit
            </span>
        </div>

        <h1 style="color: #fff; font-size: 24px; margin-bottom: 16px;">Welcome, Founding User</h1>

        <p>{greeting}</p>

        <p>You're one of 25 founding users getting full access to Delimit for 12 months. That includes:</p>

        <ul style="line-height: 2;">
            <li>Full enterprise dashboard (app.delimit.ai)</li>
            <li>106 MCP tools across Claude Code, Codex, Cursor, Gemini CLI</li>
            <li>Multi-model deliberation</li>
            <li>Team management, audit trail, policy editor</li>
            <li>Priority feedback channel</li>
            <li>Permanent Founding User badge</li>
        </ul>

        <div style="background: #1a1a2e; border: 1px solid #374151; border-radius: 8px; padding: 16px; margin: 24px 0;">
            <p style="margin: 0; font-family: monospace; color: #22c55e;">$ npx delimit-cli setup</p>
        </div>

        <p>Questions? Reply to this email — it goes straight to the founder.</p>

        <p style="color: #9ca3af; font-size: 14px; margin-top: 32px;">
            — The Delimit Team<br>
            delimit.ai
        </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Delimit <{EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = "Welcome to Delimit — You're a Founding User"
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(creds["email"], creds["password"])
        server.send_message(msg)


def check_inbox() -> list:
    """Check pro@delimit.ai inbox for new messages."""
    creds = _load_creds()
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, 993)
        mail.login(creds["email"], creds["password"])
        mail.select("inbox")
        status, messages = mail.search(None, "UNSEEN")
        if not messages[0]:
            mail.logout()
            return []

        results = []
        for mid in messages[0].split():
            status, data = mail.fetch(mid, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
            header = data[0][1].decode()
            results.append(header.strip())
        mail.logout()
        return results
    except Exception as e:
        return [{"error": str(e)}]
