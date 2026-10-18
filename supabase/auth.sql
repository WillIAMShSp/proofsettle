-- ProofSettle login grants for public.profiles only.
--
-- Run this once in the Supabase SQL editor (project yrliwcjpvzflaotefcrt) after
-- supabase/schema.sql. The app cannot apply it: this repo has no service-role
-- key and no database password.
--
-- What this changes
--   * authenticated users may read, insert, and update only the profile row
--     whose id is auth.uid().
--   * they cannot change role after that row exists.
--   * a new Auth user gets a profile row from sign-up metadata (name, role),
--     including when email confirmation means the browser has no session yet.
--
-- What this does not change
--   * public.shipments, agreements, evidence, inspections, adjustments,
--     decisions, audit_events, and organizations are left alone. Do not enable
--     row level security on those tables as part of login. The Python workflow
--     does not read them, and a policy-less RLS enable would hide every row
--     from anything that still does.
--   * RLS is enabled, not forced. The table owner and the Supabase SQL editor
--     still see every profile. PostgREST, using the signed-in user's token,
--     only sees that user's row. Forcing RLS would also hide rows from a
--     non-superuser database login where auth.uid() is null.
--   * Seed profiles (buyer@northgate.com, supplier@ferro.com) keep their fixed
--     ids. They are not Auth users, so a browser session will not match them.

alter type user_role add value if not exists 'Reviewer';

grant usage on schema public to anon, authenticated;
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

-- security definer so the update check can read the stored role without the
-- policy calling itself. The caller cannot replace the role.
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

-- Copies name and role from raw_user_meta_data. Owned by the migration role
-- (postgres in the SQL editor), so the insert bypasses RLS and runs before
-- the user has a session. Invalid or missing roles become Buyer.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  chosen text;
  display_name text;
begin
  chosen := coalesce(new.raw_user_meta_data ->> 'role', 'Buyer');
  if chosen not in ('Buyer', 'Supplier', 'Reviewer') then
    chosen := 'Buyer';
  end if;
  display_name := coalesce(
    nullif(new.raw_user_meta_data ->> 'name', ''),
    split_part(coalesce(new.email, ''), '@', 1),
    'User'
  );
  begin
    insert into public.profiles (id, name, email, role)
    values (new.id, display_name, new.email, chosen::user_role)
    on conflict (id) do nothing;
  exception
    when unique_violation then
      null;
  end;
  return new;
end;
$$;

revoke all on function public.handle_new_user() from public, anon, authenticated;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row
  execute function public.handle_new_user();
