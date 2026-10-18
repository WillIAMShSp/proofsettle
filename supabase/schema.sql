-- =========================================================================
-- PROOFSETTLE: Supabase Database Schema & Seed Data
-- HackGB 2026 | Industrial / FinTech Track
-- Product Tagline: Payments backed by agreed evidence.
-- =========================================================================

-- 1. EXTENSIONS & ENUMS
create extension if not exists "uuid-ossp";

do $$ begin
  create type user_role as enum ('Buyer', 'Supplier', 'Auditor', 'Reviewer');
exception
  when duplicate_object then null;
end $$;

-- Existing databases created the enum without Reviewer. The API accepts this value.
alter type user_role add value if not exists 'Reviewer';

do $$ begin
  create type shipment_status as enum (
    'Draft', 
    'Agreed', 
    'In Transit', 
    'Inspection', 
    'Proposed', 
    'Accepted', 
    'Disputed', 
    'Resolved'
  );
exception
  when duplicate_object then null;
end $$;

do $$ begin
  create type evidence_type as enum ('dispatch', 'receipt', 'invoice', 'po');
exception
  when duplicate_object then null;
end $$;

do $$ begin
  create type decision_choice as enum ('Accepted', 'Disputed');
exception
  when duplicate_object then null;
end $$;

-- 2. ORGANIZATIONS & PROFILES
create table if not exists public.organizations (
  id uuid primary key default uuid_generate_v4(),
  name text not null,
  org_type text not null check (org_type in ('buyer', 'supplier')),
  created_at timestamptz default now()
);

create table if not exists public.profiles (
  id uuid primary key default uuid_generate_v4(),
  organization_id uuid references public.organizations(id) on delete set null,
  name text not null,
  email text unique,
  role user_role not null default 'Buyer',
  created_at timestamptz default now()
);

-- Login policies are not applied here. supabase/auth.sql enables row level
-- security on public.profiles only. Leave the other public tables without RLS.

-- 3. SHIPMENTS
create table if not exists public.shipments (
  id text primary key, -- e.g. 'PS-1042'
  title text not null,
  buyer_id uuid references public.organizations(id),
  supplier_id uuid references public.organizations(id),
  invoice_amount numeric(12, 2) not null,
  status shipment_status not null default 'Draft',
  dispute_reason text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- 4. AGREEMENTS
create table if not exists public.agreements (
  id uuid primary key default uuid_generate_v4(),
  shipment_id text not null references public.shipments(id) on delete cascade,
  goods_description text not null,
  unit_count integer not null,
  credit_per_defect numeric(10, 2) not null default 100.00,
  min_confidence_threshold numeric(4, 2) default 0.85,
  terms_json jsonb not null default '{}'::jsonb,
  terms_hash text not null,
  buyer_approved boolean default false,
  supplier_approved boolean default false,
  buyer_approved_at timestamptz,
  supplier_approved_at timestamptz,
  created_at timestamptz default now()
);

-- 5. EVIDENCE (Dispatch & Receipt photos)
create table if not exists public.evidence (
  id uuid primary key default uuid_generate_v4(),
  shipment_id text not null references public.shipments(id) on delete cascade,
  evidence_type evidence_type not null,
  file_name text not null,
  file_url text not null,
  sha256 text not null,
  uploaded_by uuid references public.profiles(id),
  created_at timestamptz default now()
);

-- 6. INSPECTIONS (AI damage findings)
create table if not exists public.inspections (
  id uuid primary key default uuid_generate_v4(),
  shipment_id text not null references public.shipments(id) on delete cascade,
  evidence_id uuid references public.evidence(id) on delete cascade,
  item_label text not null, -- e.g. "Component #017"
  issue text not null,      -- e.g. "Bent flange"
  confidence numeric(4, 2) not null, -- e.g. 0.94
  confirmed boolean not null default false, -- >= 0.85 passes auto-flag
  review_status text default 'auto_flagged' check (review_status in ('auto_flagged', 'needs_review', 'human_verified', 'rejected')),
  created_at timestamptz default now()
);

-- 7. ADJUSTMENTS (Deterministic calculation)
create table if not exists public.adjustments (
  id uuid primary key default uuid_generate_v4(),
  shipment_id text not null references public.shipments(id) on delete cascade,
  rule_id text not null default 'CREDIT_PER_DEFECT',
  defects_count integer not null,
  rate_per_defect numeric(10, 2) not null,
  proposed_amount numeric(12, 2) not null,
  explanation text not null,
  status text not null default 'Pending' check (status in ('Pending', 'Accepted', 'Disputed')),
  created_at timestamptz default now()
);

-- 8. DECISIONS (Supplier Acceptance / Dispute)
create table if not exists public.decisions (
  id uuid primary key default uuid_generate_v4(),
  adjustment_id uuid not null references public.adjustments(id) on delete cascade,
  actor_id uuid references public.profiles(id),
  decision decision_choice not null,
  reason text,
  created_at timestamptz default now()
);

-- 9. AUDIT EVENTS (Tamper-evident verification log)
create table if not exists public.audit_events (
  id uuid primary key default uuid_generate_v4(),
  shipment_id text not null references public.shipments(id) on delete cascade,
  actor text not null,
  event_text text not null,
  payload_hash text not null,
  tx_hash text,
  created_at timestamptz default now()
);

-- 10. REALTIME PUBLICATION
alter publication supabase_realtime add table shipments;
alter publication supabase_realtime add table audit_events;
alter publication supabase_realtime add table decisions;

-- =========================================================================
-- SEED DATA (Demo Scenario from PRD Section 13)
-- =========================================================================

-- Organizations
insert into public.organizations (id, name, org_type) values
  ('11111111-1111-1111-1111-111111111111', 'Northgate Assembly Ltd', 'buyer'),
  ('22222222-2222-2222-2222-222222222222', 'Ferro Precision Works', 'supplier'),
  ('33333333-3333-3333-3333-333333333333', 'Kestrel Fluid Systems', 'supplier')
on conflict (id) do nothing;

-- Demo Users
insert into public.profiles (id, organization_id, name, email, role) values
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '11111111-1111-1111-1111-111111111111', 'Alex Vance (Procurement)', 'buyer@northgate.com', 'Buyer'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', '22222222-2222-2222-2222-222222222222', 'Elena Rostova (Operations)', 'supplier@ferro.com', 'Supplier')
on conflict (id) do nothing;

-- Shipments
insert into public.shipments (id, title, buyer_id, supplier_id, invoice_amount, status) values
  ('PS-1042', '100 metal components', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 10000.00, 'Proposed'),
  ('PS-1038', '40 hydraulic valves', '11111111-1111-1111-1111-111111111111', '33333333-3333-3333-3333-333333333333', 6400.00, 'In Transit'),
  ('PS-1031', '250 steel brackets', '11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 3750.00, 'Resolved')
on conflict (id) do nothing;

-- Agreement for PS-1042
insert into public.agreements (
  shipment_id, goods_description, unit_count, credit_per_defect, 
  min_confidence_threshold, terms_hash, buyer_approved, supplier_approved
) values (
  'PS-1042', 
  '100 machined metal components', 
  100, 
  100.00, 
  0.85, 
  '8fa9c4e201b1a3d4f826374092b3c1d98e723490123847a98bcdef0123456789',
  true, 
  true
);

-- Inspection findings
insert into public.inspections (shipment_id, item_label, issue, confidence, confirmed, review_status) values
  ('PS-1042', 'Component #017', 'Bent flange', 0.94, true, 'auto_flagged'),
  ('PS-1042', 'Component #042', 'Surface crack near bore', 0.91, true, 'auto_flagged'),
  ('PS-1042', 'Component #078', 'Deep scratch on mating face', 0.88, true, 'auto_flagged'),
  ('PS-1042', 'Component #063', 'Possible discoloration', 0.52, false, 'needs_review');

-- Proposed Adjustment
insert into public.adjustments (shipment_id, rule_id, defects_count, rate_per_defect, proposed_amount, explanation, status) values
  ('PS-1042', 'CREDIT_PER_DEFECT', 3, 100.00, 300.00, '3 confirmed defects × $100 = $300 deduction from invoice $10,000', 'Pending');

-- Audit events with SHA-256 hashes
insert into public.audit_events (shipment_id, actor, event_text, payload_hash) values
  ('PS-1042', 'Buyer', 'Agreement drafted: 100 components, $10,000', '9f83c2672ea4e1836932463e264639e4a3b7238484e5699c277258380cf089d7'),
  ('PS-1042', 'Supplier', 'Agreement approved by both parties', '4e07408562bedb8b60ce05c1decfe3ad16b72230967de01f640b7e4729b49fce'),
  ('PS-1042', 'Supplier', 'Dispatch photos uploaded (4)', '4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a'),
  ('PS-1042', 'System', 'Shipment marked In Transit', 'ef2d127de37b942baad06145e54b0c619a1f22327b2ebbcfbec78f5564afe39d'),
  ('PS-1042', 'Buyer', 'Receipt photos uploaded (4)', '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918'),
  ('PS-1042', 'AI', 'Inspection complete: 3 defects flagged', 'a883dafc480d466ee04e0d6da986bd78eb1fdd2178d04693723da3a8f95d42f4'),
  ('PS-1042', 'System', 'Adjustment proposed from agreement rule: $300', '9834876dcfb05cb167a5c24953eba58c4ac89b1adf57f28f2f9d09af107ee9f0');
