-- Applied after 001: tighten function access (Supabase security advisor clean).
alter function public.touch_updated_at() set search_path = public;
revoke execute on function public.apply_message_grade() from public, anon, authenticated;
revoke execute on function public.touch_updated_at() from public, anon, authenticated;
revoke execute on function public.is_team_member() from public, anon;
grant execute on function public.is_team_member() to authenticated;

-- Keep the membership check out of the public API; RLS policies still use it.
create schema if not exists private;
grant usage on schema private to authenticated;
alter function public.is_team_member() set schema private;
