-- SMS Sifter: private lead dashboard for a two-person wholesaling team.
--
-- Access model
--   * Only emails listed in public.team_members can read or change anything
--     (row level security on every table). Anyone else who somehow signs in sees nothing.
--   * The ingest worker uses the service_role key, which bypasses RLS; never ship it to the browser.
--   * Also turn OFF "Allow new users to sign up" in Supabase Auth settings and invite the two of you.

-- Who is allowed in. Add both of you after running this file:
--   insert into public.team_members (email, name) values ('you@x.com','Alessio'), ('partner@x.com','Partner');
create table public.team_members (
  email      text primary key check (email = lower(email)),
  name       text not null,
  created_at timestamptz not null default now()
);

create or replace function public.is_team_member() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.team_members
    where email = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;

create type public.lead_tier as enum ('HOT', 'WARM', 'COLD', 'DEAD', 'DNC');
create type public.lead_status as enum
  ('new', 'contacted', 'appointment', 'offer_made', 'under_contract', 'closed', 'dead');

create table public.leads (
  id              uuid primary key default gen_random_uuid(),
  phone           text not null unique,
  name            text,
  property_address text,
  -- Set by the grader from the latest reply (see trigger below).
  tier            public.lead_tier not null default 'COLD',
  score           int not null default 0 check (score between 0 and 100),
  last_reply      text,
  last_reply_at   timestamptz,
  reply_count     int not null default 0,
  -- Set by you in the dashboard.
  tier_override   public.lead_tier,
  status          public.lead_status not null default 'new',
  assigned_to     text references public.team_members(email) on delete set null,
  asking_price    numeric(12,2),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table public.messages (
  id                uuid primary key default gen_random_uuid(),
  lead_id           uuid not null references public.leads(id) on delete cascade,
  direction         text not null default 'in' check (direction in ('in', 'out')),
  body              text not null,
  sent_at           timestamptz not null,
  source_message_id text unique,          -- Gmail Message-ID; stops double-grading
  score             int check (score between 0 and 100),
  tier              public.lead_tier,
  reasons           text[] not null default '{}',
  grader            text,
  created_at        timestamptz not null default now()
);
create index messages_lead_sent on public.messages (lead_id, sent_at);

create table public.notes (
  id           uuid primary key default gen_random_uuid(),
  lead_id      uuid not null references public.leads(id) on delete cascade,
  author_email text not null default lower(coalesce(auth.jwt() ->> 'email', 'system')),
  body         text not null check (length(body) > 0),
  created_at   timestamptz not null default now()
);
create index notes_lead on public.notes (lead_id, created_at);

-- Keep the lead's grade in step with its latest inbound reply. An opt-out is permanent.
create or replace function public.apply_message_grade() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  latest record;
  opted_out boolean;
begin
  select m.* into latest from public.messages m
   where m.lead_id = new.lead_id and m.direction = 'in' and m.tier is not null
   order by m.sent_at desc, m.created_at desc limit 1;
  if not found then
    return new;  -- no graded inbound reply yet (e.g. only an outbound text)
  end if;
  select exists (select 1 from public.messages m where m.lead_id = new.lead_id and m.tier = 'DNC')
    into opted_out;
  update public.leads l set
    tier          = case when opted_out then 'DNC' else coalesce(latest.tier, l.tier) end,
    score         = case when opted_out then 0 else coalesce(latest.score, l.score) end,
    last_reply    = coalesce(latest.body, l.last_reply),
    last_reply_at = coalesce(latest.sent_at, l.last_reply_at),
    reply_count   = (select count(*) from public.messages m where m.lead_id = new.lead_id and m.direction = 'in'),
    updated_at    = now()
  where l.id = new.lead_id;
  return new;
end $$;

create trigger messages_apply_grade after insert on public.messages
  for each row execute function public.apply_message_grade();

create or replace function public.touch_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;
create trigger leads_touch before update on public.leads
  for each row execute function public.touch_updated_at();

-- What the dashboard lists: your override wins over the grader, hottest first, opt-outs last.
create view public.ranked_leads with (security_invoker = true) as
select l.*,
       coalesce(l.tier_override, l.tier) as effective_tier,
       case when coalesce(l.tier_override, l.tier) = 'DNC' then 0 else l.score end as effective_score
from public.leads l
order by (coalesce(l.tier_override, l.tier) = 'DNC'),
         array_position(array['HOT','WARM','COLD','DEAD','DNC']::public.lead_tier[], coalesce(l.tier_override, l.tier)),
         l.score desc, l.last_reply_at desc nulls last;

-- Row level security: team members only.
alter table public.team_members enable row level security;
alter table public.leads        enable row level security;
alter table public.messages     enable row level security;
alter table public.notes        enable row level security;

create policy team_read on public.team_members for select to authenticated using (public.is_team_member());

create policy team_all on public.leads for all to authenticated
  using (public.is_team_member()) with check (public.is_team_member());
create policy team_read on public.messages for select to authenticated using (public.is_team_member());
create policy team_read on public.notes for select to authenticated using (public.is_team_member());
create policy team_insert on public.notes for insert to authenticated
  with check (public.is_team_member() and author_email = lower(auth.jwt() ->> 'email'));
create policy own_delete on public.notes for delete to authenticated
  using (public.is_team_member() and author_email = lower(auth.jwt() ->> 'email'));

-- Browser users may only edit the human-owned lead fields; grades come from the worker.
revoke all on public.leads, public.messages, public.notes, public.team_members, public.ranked_leads from anon, authenticated;
grant select on public.team_members, public.leads, public.messages, public.notes, public.ranked_leads to authenticated;
grant update (name, property_address, tier_override, status, assigned_to, asking_price) on public.leads to authenticated;
grant insert (lead_id, body) , delete on public.notes to authenticated;

-- Live updates in the dashboard.
do $$ begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    alter publication supabase_realtime add table public.leads, public.messages, public.notes;
  end if;
end $$;
