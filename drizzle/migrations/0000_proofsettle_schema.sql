CREATE TYPE public.org_type AS ENUM ('buyer','supplier');
CREATE TYPE public.user_role AS ENUM ('buyer','supplier','reviewer');
CREATE TYPE public.shipment_status AS ENUM ('draft','agreed','in_transit','inspection','proposed','accepted','disputed','resolved');
CREATE TYPE public.evidence_type AS ENUM ('dispatch','receipt');
CREATE TYPE public.review_status AS ENUM ('auto_accepted','needs_review','human_corrected');
CREATE TYPE public.adjustment_status AS ENUM ('proposed','accepted','disputed');
CREATE TYPE public.decision_type AS ENUM ('accept','dispute');

CREATE TABLE public.organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  org_type public.org_type NOT NULL
);

CREATE TABLE public.profiles (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  name text,
  organization_id uuid REFERENCES public.organizations(id) ON DELETE SET NULL,
  role public.user_role
);

CREATE TABLE public.shipments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  buyer_org_id uuid NOT NULL REFERENCES public.organizations(id),
  supplier_org_id uuid NOT NULL REFERENCES public.organizations(id),
  po_number text NOT NULL,
  item_description text NOT NULL,
  quantity integer NOT NULL CHECK (quantity > 0),
  invoice_amount numeric(14,2) NOT NULL CHECK (invoice_amount >= 0),
  status public.shipment_status NOT NULL DEFAULT 'draft',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.agreements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_id uuid NOT NULL REFERENCES public.shipments(id) ON DELETE CASCADE,
  terms_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  terms_hash text,
  buyer_approved boolean NOT NULL DEFAULT false,
  supplier_approved boolean NOT NULL DEFAULT false,
  buyer_approved_at timestamptz,
  supplier_approved_at timestamptz
);

CREATE TABLE public.evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_id uuid NOT NULL REFERENCES public.shipments(id) ON DELETE CASCADE,
  evidence_type public.evidence_type NOT NULL,
  file_path text NOT NULL,
  sha256_client text,
  sha256_server text,
  uploaded_by uuid REFERENCES public.profiles(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.inspections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_id uuid NOT NULL REFERENCES public.evidence(id) ON DELETE CASCADE,
  findings_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  confidence numeric(5,4) CHECK (confidence BETWEEN 0 AND 1),
  review_status public.review_status NOT NULL DEFAULT 'needs_review'
);

CREATE TABLE public.adjustments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_id uuid NOT NULL REFERENCES public.shipments(id) ON DELETE CASCADE,
  rule_id text NOT NULL,
  proposed_amount numeric(14,2) NOT NULL,
  explanation text,
  status public.adjustment_status NOT NULL DEFAULT 'proposed'
);

CREATE TABLE public.decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  adjustment_id uuid NOT NULL REFERENCES public.adjustments(id) ON DELETE CASCADE,
  actor_id uuid NOT NULL REFERENCES public.profiles(id),
  decision public.decision_type NOT NULL,
  reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (decision <> 'dispute' OR coalesce(length(trim(reason)),0) > 0)
);

CREATE TABLE public.audit_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_id uuid NOT NULL REFERENCES public.shipments(id) ON DELETE CASCADE,
  event_type text NOT NULL,
  payload_hash text NOT NULL,
  prev_hash text,
  tx_hash text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON public.shipments(buyer_org_id);
CREATE INDEX ON public.shipments(supplier_org_id);
CREATE INDEX ON public.agreements(shipment_id);
CREATE INDEX ON public.evidence(shipment_id);
CREATE INDEX ON public.inspections(evidence_id);
CREATE INDEX ON public.adjustments(shipment_id);
CREATE INDEX ON public.decisions(adjustment_id);
CREATE INDEX ON public.audit_events(shipment_id, created_at);

-- Grants
GRANT SELECT ON public.organizations TO authenticated;
GRANT SELECT, INSERT ON public.profiles TO authenticated;
GRANT UPDATE (name) ON public.profiles TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.shipments TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.agreements TO authenticated;
GRANT SELECT, INSERT ON public.evidence TO authenticated;
GRANT SELECT ON public.inspections TO authenticated;
GRANT SELECT ON public.adjustments TO authenticated;
GRANT SELECT, INSERT ON public.decisions TO authenticated;
GRANT SELECT, INSERT ON public.audit_events TO authenticated;
GRANT ALL ON public.organizations, public.profiles, public.shipments, public.agreements, public.evidence, public.inspections, public.adjustments, public.decisions, public.audit_events TO service_role;

-- Helpers (security definer to avoid RLS recursion)
CREATE OR REPLACE FUNCTION public.my_org_id() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT organization_id FROM public.profiles WHERE id = auth.uid()
$$;
CREATE OR REPLACE FUNCTION public.is_reviewer() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.profiles WHERE id = auth.uid() AND role = 'reviewer')
$$;
CREATE OR REPLACE FUNCTION public.can_access_shipment(_shipment_id uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT public.is_reviewer() OR EXISTS (
    SELECT 1 FROM public.shipments s
    WHERE s.id = _shipment_id AND public.my_org_id() IN (s.buyer_org_id, s.supplier_org_id))
$$;

ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shipments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agreements ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inspections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.adjustments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "orgs readable by signed-in users" ON public.organizations FOR SELECT TO authenticated USING (true);

CREATE POLICY "read own profile or same org" ON public.profiles FOR SELECT TO authenticated
  USING (id = auth.uid() OR organization_id = public.my_org_id() OR public.is_reviewer());
CREATE POLICY "insert own profile without role" ON public.profiles FOR INSERT TO authenticated
  WITH CHECK (id = auth.uid() AND role IS NULL AND organization_id IS NULL);
CREATE POLICY "update own profile" ON public.profiles FOR UPDATE TO authenticated
  USING (id = auth.uid()) WITH CHECK (id = auth.uid());

CREATE POLICY "parties read shipments" ON public.shipments FOR SELECT TO authenticated
  USING (public.is_reviewer() OR public.my_org_id() IN (buyer_org_id, supplier_org_id));
CREATE POLICY "buyer creates shipments" ON public.shipments FOR INSERT TO authenticated
  WITH CHECK (buyer_org_id = public.my_org_id());
CREATE POLICY "parties update shipments" ON public.shipments FOR UPDATE TO authenticated
  USING (public.my_org_id() IN (buyer_org_id, supplier_org_id))
  WITH CHECK (public.my_org_id() IN (buyer_org_id, supplier_org_id));

CREATE POLICY "parties read agreements" ON public.agreements FOR SELECT TO authenticated USING (public.can_access_shipment(shipment_id));
CREATE POLICY "parties write agreements" ON public.agreements FOR INSERT TO authenticated WITH CHECK (public.can_access_shipment(shipment_id) AND NOT public.is_reviewer());
CREATE POLICY "parties update agreements" ON public.agreements FOR UPDATE TO authenticated USING (public.can_access_shipment(shipment_id) AND NOT public.is_reviewer());

CREATE POLICY "parties read evidence" ON public.evidence FOR SELECT TO authenticated USING (public.can_access_shipment(shipment_id));
CREATE POLICY "parties upload evidence" ON public.evidence FOR INSERT TO authenticated
  WITH CHECK (uploaded_by = auth.uid() AND public.can_access_shipment(shipment_id) AND NOT public.is_reviewer());

CREATE POLICY "parties read inspections" ON public.inspections FOR SELECT TO authenticated
  USING (EXISTS (SELECT 1 FROM public.evidence e WHERE e.id = evidence_id AND public.can_access_shipment(e.shipment_id)));

CREATE POLICY "parties read adjustments" ON public.adjustments FOR SELECT TO authenticated USING (public.can_access_shipment(shipment_id));

CREATE POLICY "parties read decisions" ON public.decisions FOR SELECT TO authenticated
  USING (EXISTS (SELECT 1 FROM public.adjustments a WHERE a.id = adjustment_id AND public.can_access_shipment(a.shipment_id)));
CREATE POLICY "supplier records decision" ON public.decisions FOR INSERT TO authenticated
  WITH CHECK (actor_id = auth.uid() AND EXISTS (
    SELECT 1 FROM public.adjustments a JOIN public.shipments s ON s.id = a.shipment_id
    WHERE a.id = adjustment_id AND s.supplier_org_id = public.my_org_id()));

CREATE POLICY "parties read audit" ON public.audit_events FOR SELECT TO authenticated USING (public.can_access_shipment(shipment_id));
CREATE POLICY "parties append audit" ON public.audit_events FOR INSERT TO authenticated WITH CHECK (public.can_access_shipment(shipment_id));

-- Auto-create profile on signup
CREATE OR REPLACE FUNCTION public.handle_new_user() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  INSERT INTO public.profiles (id, name) VALUES (NEW.id, coalesce(NEW.raw_user_meta_data->>'name', NEW.email));
  RETURN NEW;
END $$;
CREATE TRIGGER on_auth_user_created AFTER INSERT ON auth.users FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();