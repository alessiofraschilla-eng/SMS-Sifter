"""Read Google Voice text messages out of Gmail.

Google Voice has no public API, but it can email every incoming text to the
Google account (Voice settings > Messages > "Forward messages to email").
Those notification emails look like:

    From:    "(555) 123-4567" <15551234567.19995550000.abc@txt.voice.google.com>
    Subject: New text message from (555) 123-4567
    Body:    <the text>  ...  "To respond to this text message, reply to this email..."

We poll Gmail over IMAP (Gmail app password) and turn each email into an
InboundText.
"""
from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime

GV_SENDER_DOMAIN = "txt.voice.google.com"
PHONE_RE = re.compile(r"\+?1?\s*\(?(\d{3})\)?[\s.-]*(\d{3})[\s.-]*(\d{4})")
# Everything after one of these markers is Google's boilerplate footer.
FOOTER_MARKERS = (
    "To respond to this text message",
    "YOUR ACCOUNT",
    "HELP CENTER",
    "Google LLC",
    "You received this message because",
)


@dataclass
class InboundText:
    phone: str          # normalized +1XXXXXXXXXX
    body: str
    received_at: datetime
    message_id: str     # email Message-ID, used to skip duplicates


def normalize_phone(raw: str) -> str | None:
    m = PHONE_RE.search(raw or "")
    return f"+1{m.group(1)}{m.group(2)}{m.group(3)}" if m else None


def _decode(value: str | None) -> str:
    return str(make_header(decode_header(value))) if value else ""


def _plain_text(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                return re.sub(r"<[^>]+>", " ", html)
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


def clean_body(text: str) -> str:
    cut = len(text)
    for marker in FOOTER_MARKERS:
        i = text.find(marker)
        if i != -1:
            cut = min(cut, i)
    text = text[:cut]
    # Drop quoted history from threads ("On ... wrote:" / "> ...").
    text = re.split(r"\n\s*On .+wrote:", text)[0]
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def parse_gv_email(raw: bytes) -> InboundText | None:
    """Parse one raw email; returns None if it is not a Google Voice text."""
    msg = email.message_from_bytes(raw)
    sender = _decode(msg.get("From"))
    subject = _decode(msg.get("Subject"))
    if GV_SENDER_DOMAIN not in sender.lower() and "new text message" not in subject.lower():
        return None
    phone = normalize_phone(subject) or normalize_phone(sender)
    if not phone:
        # Sender address encodes the number: 1<their number>.1<your GV number>...
        m = re.search(r"<1?(\d{10})\.", sender)
        phone = f"+1{m.group(1)}" if m else None
    if not phone:
        return None
    try:
        received = parsedate_to_datetime(msg.get("Date"))
    except (TypeError, ValueError):
        received = datetime.now(timezone.utc)
    body = clean_body(_plain_text(msg))
    if not body:
        return None
    return InboundText(phone=phone, body=body, received_at=received,
                       message_id=msg.get("Message-ID") or f"{phone}-{received.isoformat()}")


def fetch_from_gmail(user: str, app_password: str, since_days: int = 7,
                     host: str = "imap.gmail.com") -> list[InboundText]:
    """Pull Google Voice text notifications from the last `since_days` days."""
    since = datetime.now(timezone.utc).timestamp() - since_days * 86400
    since_str = datetime.fromtimestamp(since, timezone.utc).strftime("%d-%b-%Y")
    out: list[InboundText] = []
    with imaplib.IMAP4_SSL(host) as imap:
        imap.login(user, app_password)
        imap.select('"[Gmail]/All Mail"', readonly=True)
        status, data = imap.search(None, "SINCE", since_str, "FROM", f'"{GV_SENDER_DOMAIN}"')
        if status != "OK":
            return out
        for num in data[0].split():
            status, parts = imap.fetch(num, "(RFC822)")
            if status == "OK" and parts and isinstance(parts[0], tuple):
                parsed = parse_gv_email(parts[0][1])
                if parsed:
                    out.append(parsed)
    return out
