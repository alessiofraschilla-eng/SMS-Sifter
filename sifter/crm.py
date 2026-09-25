"""Push ranked leads to a CRM.

* export_csv   - works with any CRM's import (REsimpli, Podio, GoHighLevel, HubSpot...).
* GoHighLevelSync - for each lead in a GoHighLevel sub-account:
    - upserts the contact by phone and fills two custom fields,
      "SMS Lead Score" (number) and "SMS Last Reply" (created if missing),
      so a Smart List sorted by SMS Lead Score is hottest to coldest;
    - tags it sms-hot / sms-warm / sms-cold / sms-dead / sms-dnc (old sms-* tags removed);
    - opt-outs get Do Not Disturb turned on;
    - puts an opportunity in the pipeline named by GHL_PIPELINE (default
      "SMS Leads") in the stage whose name matches the tier (Hot, Warm, Cold, Dead;
      DNC goes to Dead as lost). Create that pipeline in GHL first.
  Needs a Private Integration token (Settings > Private Integrations) with
  contacts, opportunities and locations/customFields read+write scopes, and
  the sub-account's Location ID.
"""
from __future__ import annotations

import csv
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CSV_FIELDS = ["rank", "tier", "score", "phone", "last_reply", "reasons", "replies", "last_reply_at"]


def export_csv(leads: list[dict], path: str | Path) -> Path:
    path = Path(path)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for i, lead in enumerate(leads, 1):
            w.writerow({**lead, "rank": i})
    return path


class GoHighLevelSync:
    BASE = "https://services.leadconnectorhq.com"
    API_VERSION = "2021-07-28"
    FIELDS = {"score": ("SMS Lead Score", "NUMERICAL"), "reply": ("SMS Last Reply", "LARGE_TEXT")}
    TAGS = {t: f"sms-{t.lower()}" for t in ("HOT", "WARM", "COLD", "DEAD", "DNC")}

    def __init__(self, token: str, location_id: str, pipeline_name: str = "SMS Leads",
                 api_version: str | None = None):
        self.token = token
        self.location_id = location_id
        self.pipeline_name = pipeline_name
        self.api_version = api_version or self.API_VERSION
        self.field_ids: dict[str, str] = {}
        self.pipeline_id: str | None = None
        self.stage_ids: dict[str, str] = {}

    def _call(self, method: str, path: str, body: dict | None = None, query: dict | None = None) -> dict:
        url = self.BASE + path + ("?" + urllib.parse.urlencode(query) if query else "")
        req = urllib.request.Request(
            url, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Version": self.api_version,
                     "Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}

    def setup(self) -> list[str]:
        """Find/create custom fields and look up the pipeline. Returns warnings."""
        warnings = []
        path = f"/locations/{self.location_id}/customFields"
        existing = {f["name"].lower(): f["id"] for f in self._call("GET", path, query={"model": "contact"}).get("customFields", [])}
        for key, (name, dtype) in self.FIELDS.items():
            fid = existing.get(name.lower())
            if not fid:
                fid = self._call("POST", path, {"name": name, "dataType": dtype, "model": "contact"})["customField"]["id"]
            self.field_ids[key] = fid
        pipelines = self._call("GET", "/opportunities/pipelines", query={"locationId": self.location_id}).get("pipelines", [])
        match = next((p for p in pipelines if p["name"].strip().lower() == self.pipeline_name.lower()), None)
        if not match:
            warnings.append(f'No pipeline named "{self.pipeline_name}"; contacts synced without opportunities.')
        else:
            self.pipeline_id = match["id"]
            self.stage_ids = {s["name"].strip().upper(): s["id"] for s in match.get("stages", [])}
            missing = [t.title() for t in ("HOT", "WARM", "COLD", "DEAD") if t not in self.stage_ids]
            if missing:
                warnings.append(f"Pipeline is missing stages: {', '.join(missing)}.")
        return warnings

    def upsert_contact(self, lead: dict) -> str:
        body = {
            "locationId": self.location_id,
            "phone": lead["phone"],
            "source": "SMS Sifter",
            "customFields": [
                {"id": self.field_ids["score"], "field_value": lead["score"]},
                {"id": self.field_ids["reply"], "field_value": lead["last_reply"][:2000]},
            ],
        }
        if lead["tier"] == "DNC":
            body["dnd"] = True
        return self._call("POST", "/contacts/upsert", body)["contact"]["id"]

    def set_tier_tag(self, contact_id: str, tier: str) -> None:
        stale = [t for k, t in self.TAGS.items() if k != tier]
        self._call("DELETE", f"/contacts/{contact_id}/tags", {"tags": stale})
        self._call("POST", f"/contacts/{contact_id}/tags", {"tags": [self.TAGS[tier]]})

    def place_opportunity(self, contact_id: str, lead: dict) -> None:
        stage = self.stage_ids.get("DEAD" if lead["tier"] == "DNC" else lead["tier"])
        if not (self.pipeline_id and stage):
            return
        status = "lost" if lead["tier"] in ("DNC", "DEAD") else "open"
        found = self._call("GET", "/opportunities/search", query={
            "location_id": self.location_id, "pipeline_id": self.pipeline_id, "contact_id": contact_id,
        }).get("opportunities", [])
        if found:
            self._call("PUT", f"/opportunities/{found[0]['id']}", {"pipelineStageId": stage, "status": status})
        else:
            self._call("POST", "/opportunities/", {
                "locationId": self.location_id, "pipelineId": self.pipeline_id, "pipelineStageId": stage,
                "contactId": contact_id, "status": status, "name": f"SMS lead {lead['phone']}",
            })

    def sync(self, leads: list[dict]) -> tuple[int, list[str]]:
        warnings = self.setup()
        for lead in leads:
            contact_id = self.upsert_contact(lead)
            self.set_tier_tag(contact_id, lead["tier"])
            self.place_opportunity(contact_id, lead)
        return len(leads), warnings
