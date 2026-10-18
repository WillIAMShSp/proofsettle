import { createClient } from "@supabase/supabase-js";

// Read environment variables using bracket notation to satisfy noPropertyAccessFromIndexSignature
const env = import.meta.env;
const supabaseUrl = (env["VITE_SUPABASE_URL"] as string | undefined) || "";
const supabaseAnonKey =
  (env["VITE_SUPABASE_ANON_KEY"] as string | undefined) ||
  (env["VITE_SUPABASE_PUBLISHABLE_KEY"] as string | undefined) ||
  "";

export const isSupabaseConfigured = Boolean(
  supabaseUrl &&
  supabaseAnonKey &&
  supabaseUrl !== "https://your-project-id.supabase.co" &&
  !supabaseUrl.includes("placeholder")
);

// Fallback dummy client if credentials aren't provided yet so app never crashes
export const supabase = isSupabaseConfigured
  ? createClient(supabaseUrl, supabaseAnonKey)
  : createClient("https://placeholder.supabase.co", "placeholder-key");

/**
 * Deterministic browser-native SHA-256 computation using Web Crypto API.
 * Returns a 64-character lowercase hex string.
 */
export async function computeSHA256(data: string | ArrayBuffer): Promise<string> {
  const buffer = typeof data === "string" ? new TextEncoder().encode(data) : data;
  const hashBuffer = await crypto.subtle.digest("SHA-256", buffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
}

export type DbOrganization = {
  id: string;
  name: string;
  org_type: "buyer" | "supplier";
  created_at?: string | undefined;
};

export type DbAgreement = {
  id: string;
  shipment_id: string;
  goods_description?: string | undefined;
  unit_count?: number | undefined;
  credit_per_defect?: number | undefined;
  min_confidence_threshold?: number | undefined;
  terms_json?: Record<string, unknown> | undefined;
  terms_hash?: string | null | undefined;
  buyer_approved?: boolean | undefined;
  supplier_approved?: boolean | undefined;
  buyer_approved_at?: string | null | undefined;
  supplier_approved_at?: string | null | undefined;
};

export type DbEvidence = {
  id: string;
  shipment_id: string;
  evidence_type: string;
  file_name?: string | undefined;
  file_path?: string | undefined;
  file_url?: string | undefined;
  sha256?: string | undefined;
  sha256_client?: string | null | undefined;
  created_at: string;
};

export type DbInspection = {
  id: string;
  shipment_id?: string | undefined;
  evidence_id?: string | undefined;
  item_label?: string | undefined;
  issue?: string | undefined;
  confidence?: number | null | undefined;
  confirmed?: boolean | undefined;
  review_status?: string | undefined;
};

export type DbAdjustment = {
  id: string;
  shipment_id: string;
  rule_id: string;
  defects_count?: number | undefined;
  rate_per_defect?: number | undefined;
  proposed_amount: number;
  explanation?: string | null | undefined;
  status: "Pending" | "Accepted" | "Disputed" | string;
};

export type DbAuditEvent = {
  id: string;
  shipment_id: string;
  actor?: string | undefined;
  event_text?: string | undefined;
  event_type?: string | undefined;
  payload_hash: string;
  tx_hash?: string | null | undefined;
  created_at: string;
};

export type DbShipmentWithRelations = {
  id: string;
  title?: string | undefined;
  item_description?: string | undefined;
  buyer_id?: string | undefined;
  supplier_id?: string | undefined;
  buyer_org_id?: string | undefined;
  supplier_org_id?: string | undefined;
  invoice_amount: number;
  status: string;
  dispute_reason?: string | null | undefined;
  created_at: string;
  buyer?: DbOrganization | undefined;
  supplier?: DbOrganization | undefined;
  agreements?: DbAgreement[] | undefined;
  evidence?: DbEvidence[] | undefined;
  inspections?: DbInspection[] | undefined;
  adjustments?: DbAdjustment[] | undefined;
  audit_events?: DbAuditEvent[] | undefined;
};

/**
 * Fetch all shipments from Supabase with relational joins
 */
export async function fetchShipments(): Promise<DbShipmentWithRelations[] | null> {
  if (!isSupabaseConfigured) return null;

  try {
    const { data, error } = await supabase
      .from("shipments")
      .select(`
        *,
        agreements(*),
        evidence(*),
        inspections(*),
        adjustments(*),
        audit_events(*)
      `)
      .order("created_at", { ascending: false });

    if (error) {
      console.warn("Supabase fetchShipments warning:", error.message);
      return null;
    }
    return data as DbShipmentWithRelations[];
  } catch (err) {
    console.warn("Supabase fetchShipments caught error:", err);
    return null;
  }
}

/**
 * Submit supplier decision (Accept or Dispute) and log tamper-evident audit event
 */
export async function submitSupplierDecision(
  shipmentId: string,
  decision: "Accepted" | "Disputed",
  reason?: string | undefined,
  actor: string = "Supplier"
): Promise<{ success: boolean; hash: string }> {
  const eventText = decision === "Accepted"
    ? `${actor} accepted adjustment`
    : `${actor} disputed adjustment: ${reason?.trim() || "Unspecified reason"}`;

  const hash = await computeSHA256(eventText);

  if (isSupabaseConfigured) {
    try {
      // 1. Update shipment
      await supabase
        .from("shipments")
        .update({
          status: decision,
          dispute_reason: decision === "Disputed" ? reason : null,
          updated_at: new Date().toISOString(),
        })
        .eq("id", shipmentId);

      // 2. Insert decision record
      const { data: adj } = await supabase
        .from("adjustments")
        .select("id")
        .eq("shipment_id", shipmentId)
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle();

      if (adj?.id) {
        await supabase.from("decisions").insert({
          adjustment_id: adj.id,
          decision,
          reason: reason || null,
        });

        await supabase
          .from("adjustments")
          .update({ status: decision })
          .eq("id", adj.id);
      }

      // 3. Insert audit event with verifiable hash
      await supabase.from("audit_events").insert({
        shipment_id: shipmentId,
        actor,
        event_text: eventText,
        payload_hash: hash,
      });
    } catch (err) {
      console.error("Failed to sync decision to Supabase:", err);
    }
  }

  return { success: true, hash };
}

/**
 * Upload an evidence file to Supabase storage and create an evidence record
 */
export async function uploadEvidenceFile(
  shipmentId: string,
  file: File,
  type: "dispatch" | "receipt"
): Promise<{ fileUrl: string; sha256: string } | null> {
  const buffer = await file.arrayBuffer();
  const sha256 = await computeSHA256(buffer);

  if (!isSupabaseConfigured) {
    // Return a local blob URL for offline/unconfigured demo mode
    return {
      fileUrl: URL.createObjectURL(file),
      sha256,
    };
  }

  try {
    const fileExt = file.name.split(".").pop();
    const filePath = `${shipmentId}/${type}/${Date.now()}-${Math.random().toString(36).slice(2, 7)}.${fileExt}`;

    const { error: uploadError } = await supabase.storage
      .from("evidence")
      .upload(filePath, file);

    if (uploadError) {
      console.warn("Storage upload error:", uploadError.message);
      return { fileUrl: URL.createObjectURL(file), sha256 };
    }

    const { data: urlData } = supabase.storage
      .from("evidence")
      .getPublicUrl(filePath);

    // Save record to DB
    await supabase.from("evidence").insert({
      shipment_id: shipmentId,
      evidence_type: type,
      file_name: file.name,
      file_url: urlData.publicUrl,
      file_path: filePath,
      sha256,
      sha256_client: sha256,
    });

    return { fileUrl: urlData.publicUrl, sha256 };
  } catch (err) {
    console.error("Error uploading evidence:", err);
    return { fileUrl: URL.createObjectURL(file), sha256 };
  }
}
