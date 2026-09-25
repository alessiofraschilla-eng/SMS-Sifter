"""Lead book in Supabase, same interface as store.LeadStore.

Uses the PostgREST API with the service_role key (server-side only, bypasses
row level security). The database trigger rolls each graded message up into
the lead's tier and score, so this only inserts rows.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .gv_ingest import InboundText
from .grader import Grade


class SupabaseStore:
    def __init__(self, url: str, service_key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    def _call(self, method: str, path: str, query: dict | None = None, body=None,
              prefer: str | None = None):
        url = f"{self.base}/{path}" + ("?" + urllib.parse.urlencode(query) if query else "")
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(url, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None

    def seen(self, message_id: str) -> bool:
        rows = self._call("GET", "messages", {"select": "id", "source_message_id": f"eq.{message_id}"})
        return bool(rows)

    def _lead_id(self, phone: str) -> str | None:
        rows = self._call("GET", "leads", {"select": "id", "phone": f"eq.{phone}"})
        return rows[0]["id"] if rows else None

    def history(self, phone: str) -> list[str]:
        lead_id = self._lead_id(phone)
        if not lead_id:
            return []
        rows = self._call("GET", "messages", {"select": "body", "lead_id": f"eq.{lead_id}",
                                              "direction": "eq.in", "order": "sent_at.asc"})
        return [r["body"] for r in rows]

    def add(self, text: InboundText, grade: Grade) -> None:
        lead = self._call("POST", "leads", {"on_conflict": "phone"}, [{"phone": text.phone}],
                          prefer="resolution=merge-duplicates,return=representation")
        self._call("POST", "messages", {"on_conflict": "source_message_id"}, [{
            "lead_id": lead[0]["id"],
            "direction": "in",
            "body": text.body,
            "sent_at": text.received_at.isoformat(),
            "source_message_id": text.message_id,
            "score": grade.score,
            "tier": grade.tier,
            "reasons": grade.reasons,
            "grader": grade.grader,
        }], prefer="resolution=ignore-duplicates")

    def ranked_leads(self) -> list[dict]:
        rows = self._call("GET", "ranked_leads", {
            "select": "phone,effective_tier,effective_score,last_reply,last_reply_at,reply_count"})
        return [{"phone": r["phone"], "tier": r["effective_tier"], "score": r["effective_score"],
                 "last_reply": r["last_reply"] or "", "last_reply_at": r["last_reply_at"],
                 "replies": r["reply_count"], "reasons": ""} for r in rows]
