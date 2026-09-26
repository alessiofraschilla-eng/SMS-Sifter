-- Delete button: leads are hidden, not erased, so the texts stay on file and the
-- worker doesn't re-import them. If the person texts again after the delete, the lead comes back.
alter table public.leads add column deleted_at timestamptz;
grant update (deleted_at) on public.leads to authenticated;

create or replace function public.apply_message_grade() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  latest record;
  opted_out boolean;
begin
  -- A new reply after a delete brings the lead back.
  update public.leads set deleted_at = null
   where id = new.lead_id and deleted_at is not null and new.direction = 'in' and new.sent_at > deleted_at;
  select m.* into latest from public.messages m
   where m.lead_id = new.lead_id and m.direction = 'in' and m.tier is not null
   order by m.sent_at desc, m.created_at desc limit 1;
  if not found then
    return new;
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
revoke execute on function public.apply_message_grade() from public, anon, authenticated;

drop view public.ranked_leads;
create view public.ranked_leads with (security_invoker = true) as
select l.*,
       coalesce(l.tier_override, l.tier) as effective_tier,
       case when coalesce(l.tier_override, l.tier) = 'DNC' then 0 else l.score end as effective_score
from public.leads l
where l.deleted_at is null
order by (coalesce(l.tier_override, l.tier) = 'DNC'),
         array_position(array['HOT','WARM','COLD','DEAD','DNC']::public.lead_tier[], coalesce(l.tier_override, l.tier)),
         l.score desc, l.last_reply_at desc nulls last;
revoke all on public.ranked_leads from anon, authenticated;
grant select on public.ranked_leads to authenticated;
