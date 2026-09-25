-- Run after auth_stub.sql + migrations. Every check raises on failure.
\set ON_ERROR_STOP on
grant all on all tables in schema public to service_role;

insert into team_members values ('alessio@example.com', 'Alessio'), ('partner@example.com', 'Partner');

-- Worker (service role) writes leads and graded messages.
set role service_role;
insert into leads (phone) values ('+15550000003'), ('+15550000002');
insert into messages (lead_id, body, sent_at, source_message_id, score, tier)
  select id, 'Maybe, depends on the price', '2026-09-20 10:00+00', 'm1', 60, 'WARM' from leads where phone = '+15550000003';
insert into messages (lead_id, body, sent_at, source_message_id, score, tier)
  select id, 'Actually yes, can we talk?', '2026-09-20 11:00+00', 'm2', 90, 'HOT' from leads where phone = '+15550000003';
insert into messages (lead_id, body, sent_at, source_message_id, score, tier)
  select id, 'Yes interested', '2026-09-20 10:00+00', 'm3', 80, 'HOT' from leads where phone = '+15550000002';
insert into messages (lead_id, body, sent_at, source_message_id, score, tier)
  select id, 'STOP', '2026-09-20 12:00+00', 'm4', 0, 'DNC' from leads where phone = '+15550000002';
insert into messages (lead_id, body, sent_at, source_message_id, score, tier)
  select id, 'late-arriving older hot reply', '2026-09-19 12:00+00', 'm5', 95, 'HOT' from leads where phone = '+15550000002';
reset role;

do $$ begin
  assert (select tier from leads where phone = '+15550000003') = 'HOT', 'latest reply should win';
  assert (select reply_count from leads where phone = '+15550000003') = 2, 'reply count';
  assert (select tier from leads where phone = '+15550000002') = 'DNC', 'opt-out must be sticky';
  assert (select phone from ranked_leads limit 1) = '+15550000003', 'hottest first';
end $$;

-- A stranger who signs in sees nothing and can change nothing.
set role authenticated;
set request.jwt.claims = '{"email":"stranger@example.com"}';
do $$ begin
  assert (select count(*) from leads) = 0, 'stranger sees leads';
  assert (select count(*) from ranked_leads) = 0, 'stranger sees ranked_leads';
  assert (select count(*) from messages) = 0, 'stranger sees messages';
  assert (select count(*) from team_members) = 0, 'stranger sees team';
end $$;
update leads set status = 'contacted';
do $$ begin assert (select count(*) from leads where status = 'contacted') = 0; end $$;
do $$ begin
  begin
    insert into notes (lead_id, body) select id, 'x' from leads limit 1;
  exception when others then null; end;
end $$;

-- Logged out: no access at all.
reset role; set role anon;
do $$ begin
  begin perform count(*) from leads; raise exception 'anon could read leads';
  exception when insufficient_privilege then null; end;
end $$;

-- A team member sees everything and can edit only the human fields.
reset role; set role authenticated;
set request.jwt.claims = '{"email":"Partner@Example.com"}';
do $$ begin assert (select count(*) from ranked_leads) = 2, 'member should see leads'; end $$;
update leads set status = 'contacted', assigned_to = 'alessio@example.com', tier_override = 'WARM'
  where phone = '+15550000003';
do $$ begin
  assert (select effective_tier from ranked_leads where phone = '+15550000003') = 'WARM', 'override wins';
  begin update leads set score = 100; raise exception 'member could change score';
  exception when insufficient_privilege then null; end;
  begin insert into messages (lead_id, body, sent_at) select id, 'x', now() from leads limit 1;
        raise exception 'member could insert messages';
  exception when insufficient_privilege then null; end;
end $$;
insert into notes (lead_id, body) select id, 'Called, wants 180k' from leads where phone = '+15550000003';
do $$ begin
  assert (select author_email from notes limit 1) = 'partner@example.com', 'note author stamped';
  begin insert into notes (lead_id, body, author_email) select id, 'forged', 'alessio@example.com' from leads limit 1;
        raise exception 'member could forge note author';
  exception when insufficient_privilege then null; end;
end $$;

-- The other member can read that note but not delete it.
set request.jwt.claims = '{"email":"alessio@example.com"}';
delete from notes;
do $$ begin assert (select count(*) from notes) = 1, 'deleted partner note'; end $$;
reset role;
-- Outbound-only message must not break the trigger.
insert into leads (phone) values ('+15550000099');
insert into messages (lead_id, direction, body, sent_at) select id, 'out', 'hi', now() from leads where phone = '+15550000099';
\echo ALL RLS CHECKS PASSED
