-- Run once in Supabase SQL Editor with your two real emails.
insert into public.team_members (email, name) values
  (lower('YOUR_EMAIL@gmail.com'), 'Alessio'),
  (lower('PARTNER_EMAIL@gmail.com'), 'Partner');
