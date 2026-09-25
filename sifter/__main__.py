"""SMS Sifter command line.

  python -m sifter demo                      grade the sample texts, print the ranking
  python -m sifter grade "yes how much?"     grade one reply
  python -m sifter run                       pull Google Voice texts from Gmail, grade, export
                                             (needs GMAIL_USER + GMAIL_APP_PASSWORD;
                                              GHL_TOKEN + GHL_LOCATION_ID to sync GoHighLevel;
                                              ANTHROPIC_API_KEY optional)

With SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY set, demo and run write to Supabase
(the dashboard) instead of the local leads.db file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .crm import GoHighLevelSync, export_csv
from .grader import default_grader
from .gv_ingest import InboundText, fetch_from_gmail, parse_gv_email
from .store import LeadStore
from .supabase_store import SupabaseStore

HERE = Path(__file__).resolve().parent.parent


def process(texts: list[InboundText], store) -> int:
    grader = default_grader()
    new = 0
    for t in sorted(texts, key=lambda x: x.received_at):
        if store.seen(t.message_id):
            continue
        store.add(t, grader.grade(t.body, store.history(t.phone)))
        new += 1
    return new


def print_ranking(leads: list[dict]) -> None:
    print(f"{'#':>2}  {'TIER':<5} {'SCORE':>5}  {'PHONE':<13} LAST REPLY")
    for i, l in enumerate(leads, 1):
        print(f"{i:>2}  {l['tier']:<5} {l['score']:>5}  {l['phone']:<13} {l['last_reply'][:60]}")


def load_samples() -> list[InboundText]:
    texts = []
    for eml in sorted((HERE / "samples").glob("*.eml")):
        parsed = parse_gv_email(eml.read_bytes())
        if parsed:
            texts.append(parsed)
    data = json.loads((HERE / "samples" / "replies.json").read_text())
    start = datetime(2026, 9, 20, tzinfo=timezone.utc)
    for i, (phone, body) in enumerate(data):
        texts.append(InboundText(phone, body, start + timedelta(minutes=i), f"sample-{i}"))
    return texts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sifter")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo")
    g = sub.add_parser("grade")
    g.add_argument("text")
    r = sub.add_parser("run")
    r.add_argument("--days", type=int, default=7)
    for p in (sub.choices["demo"], r):
        p.add_argument("--db", default="leads.db")
        p.add_argument("--csv", default="ranked_leads.csv")
    args = ap.parse_args(argv)

    if args.cmd == "grade":
        grade = default_grader().grade(args.text)
        print(f"{grade.tier} {grade.score}  ({', '.join(grade.reasons)}) [{grade.grader}]")
        return 0

    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        store = SupabaseStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    else:
        store = LeadStore(args.db)
    if args.cmd == "demo":
        texts = load_samples()
    else:
        user, pw = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
        if not (user and pw):
            print("Set GMAIL_USER and GMAIL_APP_PASSWORD first.", file=sys.stderr)
            return 2
        texts = fetch_from_gmail(user, pw, args.days)
    new = process(texts, store)
    leads = store.ranked_leads()
    print(f"{new} new replies graded, {len(leads)} leads total\n")
    print_ranking(leads)
    print(f"\nCSV: {export_csv(leads, args.csv)}")
    if os.environ.get("GHL_TOKEN") and os.environ.get("GHL_LOCATION_ID"):
        ghl = GoHighLevelSync(os.environ["GHL_TOKEN"], os.environ["GHL_LOCATION_ID"],
                              os.environ.get("GHL_PIPELINE", "SMS Leads"), os.environ.get("GHL_API_VERSION"))
        count, warnings = ghl.sync(leads)
        print(f"GoHighLevel: {count} contacts synced")
        for w in warnings:
            print(f"  warning: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
