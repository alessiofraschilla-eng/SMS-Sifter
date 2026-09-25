# SMS Sifter

Reads seller replies from Google Voice, grades each lead, and ranks them hottest to coldest in a private dashboard (and GoHighLevel).

```
Google Voice ─> Gmail ─> ingest worker (every 10 min) ─> Supabase ─> private dashboard (you + partner)
                                                     └─> GoHighLevel (optional)
```

## Private dashboard (Supabase)

What's in it: ranked lead list with tier counts, filters (Active / tier / Mine), search, and a lead panel with the full text conversation, why it was graded that way, status (New → Contacted → Appointment → Offer made → Under contract → Closed), owner, tier override, asking price, and shared notes. Updates live when new texts land. Keyboard: `j`/`k` move, `/` search, `Esc` close. Works on phones.

How it stays private:
- Sign-in is by emailed link, and only accounts you invited can get one.
- Every table has row level security: only emails in `team_members` can read or edit anything. A stranger who signs in sees an empty screen; logged-out requests are refused. (`supabase/tests/rls_test.sql` proves this.)
- Grades and texts can only be written by the worker's server key, never from the browser.

Setup, once:
1. Database: the project `ceiydekyhloxjwijotcz` already has `supabase/migrations/001` and `002` applied. For a new project, run those two files in **SQL Editor** in order. Then add the two of you with `supabase/add_team.sql` (edit the emails first).
2. **Authentication → Sign In / Providers**: turn **off** "Allow new users to sign up". **Authentication → Users → Invite user** for both emails. **Authentication → URL Configuration**: set Site URL to your dashboard address.
3. Dashboard: in `web/`, copy `.env.example` to `.env` with your project URL and anon key (Project Settings → API), then `npm install && npm run build`. Host `web/dist` on Vercel or Netlify (free), or run `npm run dev` locally. `VITE_DEMO=1` previews with sample data.
4. Worker: put this folder in a private GitHub repo and add the secrets listed in `.github/workflows/ingest.yml` (`SUPABASE_SERVICE_ROLE_KEY` is the service_role key, keep it secret). It runs every 10 minutes. Or run `python3 -m sifter run` anywhere with the same environment variables.

## Tiers

| Tier | Score | Meaning | Example |
|---|---|---|---|
| HOT | 75–100 | Wants to sell, asks for an offer or price, wants more info, asks for a call | "Sure, make me an offer" |
| WARM | 50–74 | Open but unsure, or selling later | "Maybe, depends on the price" |
| COLD | 25–49 | Vague or just curious who you are | "Who is this?" |
| DEAD | 0–24 | Firm no or hostile | "Not interested" |
| DNC | 0 | Asked to stop, wrong number, doesn't own it. Never text again. | "STOP" |

A lead's grade comes from their **latest** reply ("maybe" then "yes, call me" becomes HOT). An opt-out is permanent.

Two graders: keyword rules (free, instant, always on) and Claude (reads the reply in context; turns on when `ANTHROPIC_API_KEY` is set, falls back to the rules on any error). Opt-outs are always decided by the rules.

## Try it

```
python3 -m sifter demo                 # grades samples/, prints the ranking, writes ranked_leads.csv
python3 -m sifter grade "yes how much would you pay"
python3 -m unittest tests/test_sifter.py
```

Without Supabase settings, the worker keeps leads in a local `leads.db` file and writes `ranked_leads.csv`.

## Hook it to your Google Voice

1. Google Voice → Settings → Messages → turn on **Forward messages to email**.
2. Google Account → Security → turn on 2-Step Verification → create an **App password** for Mail.
3. Run:
   ```
   GMAIL_USER=you@gmail.com GMAIL_APP_PASSWORD=xxxx python3 -m sifter run --days 7
   ```
   Re-running is safe: already-graded texts are skipped. Schedule it every few minutes (cron, or a hosted job).
4. GoHighLevel (see below): add `GHL_TOKEN=... GHL_LOCATION_ID=...` to the command.
5. Optional: `ANTHROPIC_API_KEY=...` and `pip install anthropic` to grade with Claude.

## GoHighLevel setup

1. In the sub-account, create a pipeline named **SMS Leads** with stages **Hot, Warm, Cold, Dead** (another name works if you set `GHL_PIPELINE`).
2. Settings → Private Integrations → create a token with scopes for contacts, opportunities and custom fields (read + write). Copy the token and the sub-account's **Location ID** (Settings → Business Profile).
3. Each run, for every lead the sync:
   - upserts the contact by phone, fills **SMS Lead Score** and **SMS Last Reply** (custom fields, created automatically the first time);
   - tags it `sms-hot`, `sms-warm`, `sms-cold`, `sms-dead` or `sms-dnc` (the old `sms-*` tag is removed);
   - turns on Do Not Disturb for opt-outs;
   - moves its opportunity to the matching stage (opt-outs go to Dead as lost), never duplicating it.
4. Hottest to coldest: open the **SMS Leads** pipeline board, or make a Contacts Smart List filtered to tag `sms-*` and sorted by **SMS Lead Score**, descending.

If GoHighLevel rejects the API version, set `GHL_API_VERSION` (default `2021-07-28`).

## Known limits

- Google Voice has no official API. Email forwarding is the supported, ToS-safe way to read texts, but it is receive-only and depends on Google's email format. If volume grows, porting the number to Twilio gives a real webhook and sending API; only `gv_ingest.py` would change.
- The access rules are tested on local Postgres with Supabase's auth stubbed; the dashboard is tested in demo mode. Neither has run on a live Supabase project yet.
- The GoHighLevel sync is tested against a mock of their API, not a live account yet. The Claude grader has not been run live either.
