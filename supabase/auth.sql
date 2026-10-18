-- ProofSettle account privacy for public.profiles only.
--
-- Run this in the Supabase SQL editor. The app cannot apply it: this repo has no
-- service-role key and no database password.
--
-- Until this runs, the publishable key and the anon key can read every profile
-- (name, email, role). That is how one user can see other users' accounts.
--
-- This enables row level security on public.profiles only. It does not enable
-- RLS on shipments, agreements, evidence, or any other table. Those stay as they
-- are. RLS here is not forced, so the SQL editor still sees every profile.
-- PostgREST, using a signed-in user's token, sees only that user's row.

grant usage on schema public to anon, authenticated;
revoke all on table public.profiles from anon;
grant select, insert, update on table public.profiles to authenticated;

alter table public.profiles enable row level security;

drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own
  on public.profiles
  for select
  to authenticated
  using (id = auth.uid());

drop policy if exists profiles_insert_own on public.profiles;
create policy profiles_insert_own
  on public.profiles
  for insert
  to authenticated
  with check (id = auth.uid());

create or replace function public.current_profile_role()
returns text
language sql
stable
security definer
set search_path = public
as $$
  select role::text from public.profiles where id = auth.uid();
$$;

revoke all on function public.current_profile_role() from public, anon;
grant execute on function public.current_profile_role() to authenticated;

drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own
  on public.profiles
  for update
  to authenticated
  using (id = auth.uid())
  with check (
    id = auth.uid()
    and role::text = public.current_profile_role()
  );
