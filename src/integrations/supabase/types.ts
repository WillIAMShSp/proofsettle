export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.18"
  }
  public: {
    Tables: {
      adjustments: {
        Row: {
          explanation: string | null
          id: string
          proposed_amount: number
          rule_id: string
          shipment_id: string
          status: Database["public"]["Enums"]["adjustment_status"]
        }
        Insert: {
          explanation?: string | null
          id?: string
          proposed_amount: number
          rule_id: string
          shipment_id: string
          status?: Database["public"]["Enums"]["adjustment_status"]
        }
        Update: {
          explanation?: string | null
          id?: string
          proposed_amount?: number
          rule_id?: string
          shipment_id?: string
          status?: Database["public"]["Enums"]["adjustment_status"]
        }
        Relationships: [
          {
            foreignKeyName: "adjustments_shipment_id_fkey"
            columns: ["shipment_id"]
            isOneToOne: false
            referencedRelation: "shipments"
            referencedColumns: ["id"]
          },
        ]
      }
      agreements: {
        Row: {
          buyer_approved: boolean
          buyer_approved_at: string | null
          id: string
          shipment_id: string
          supplier_approved: boolean
          supplier_approved_at: string | null
          terms_hash: string | null
          terms_json: Json
        }
        Insert: {
          buyer_approved?: boolean
          buyer_approved_at?: string | null
          id?: string
          shipment_id: string
          supplier_approved?: boolean
          supplier_approved_at?: string | null
          terms_hash?: string | null
          terms_json?: Json
        }
        Update: {
          buyer_approved?: boolean
          buyer_approved_at?: string | null
          id?: string
          shipment_id?: string
          supplier_approved?: boolean
          supplier_approved_at?: string | null
          terms_hash?: string | null
          terms_json?: Json
        }
        Relationships: [
          {
            foreignKeyName: "agreements_shipment_id_fkey"
            columns: ["shipment_id"]
            isOneToOne: false
            referencedRelation: "shipments"
            referencedColumns: ["id"]
          },
        ]
      }
      audit_events: {
        Row: {
          created_at: string
          event_type: string
          id: string
          payload_hash: string
          prev_hash: string | null
          shipment_id: string
          tx_hash: string | null
        }
        Insert: {
          created_at?: string
          event_type: string
          id?: string
          payload_hash: string
          prev_hash?: string | null
          shipment_id: string
          tx_hash?: string | null
        }
        Update: {
          created_at?: string
          event_type?: string
          id?: string
          payload_hash?: string
          prev_hash?: string | null
          shipment_id?: string
          tx_hash?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "audit_events_shipment_id_fkey"
            columns: ["shipment_id"]
            isOneToOne: false
            referencedRelation: "shipments"
            referencedColumns: ["id"]
          },
        ]
      }
      decisions: {
        Row: {
          actor_id: string
          adjustment_id: string
          created_at: string
          decision: Database["public"]["Enums"]["decision_type"]
          id: string
          reason: string | null
        }
        Insert: {
          actor_id: string
          adjustment_id: string
          created_at?: string
          decision: Database["public"]["Enums"]["decision_type"]
          id?: string
          reason?: string | null
        }
        Update: {
          actor_id?: string
          adjustment_id?: string
          created_at?: string
          decision?: Database["public"]["Enums"]["decision_type"]
          id?: string
          reason?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "decisions_actor_id_fkey"
            columns: ["actor_id"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "decisions_adjustment_id_fkey"
            columns: ["adjustment_id"]
            isOneToOne: false
            referencedRelation: "adjustments"
            referencedColumns: ["id"]
          },
        ]
      }
      evidence: {
        Row: {
          created_at: string
          evidence_type: Database["public"]["Enums"]["evidence_type"]
          file_path: string
          id: string
          sha256_client: string | null
          sha256_server: string | null
          shipment_id: string
          uploaded_by: string | null
        }
        Insert: {
          created_at?: string
          evidence_type: Database["public"]["Enums"]["evidence_type"]
          file_path: string
          id?: string
          sha256_client?: string | null
          sha256_server?: string | null
          shipment_id: string
          uploaded_by?: string | null
        }
        Update: {
          created_at?: string
          evidence_type?: Database["public"]["Enums"]["evidence_type"]
          file_path?: string
          id?: string
          sha256_client?: string | null
          sha256_server?: string | null
          shipment_id?: string
          uploaded_by?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "evidence_shipment_id_fkey"
            columns: ["shipment_id"]
            isOneToOne: false
            referencedRelation: "shipments"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "evidence_uploaded_by_fkey"
            columns: ["uploaded_by"]
            isOneToOne: false
            referencedRelation: "profiles"
            referencedColumns: ["id"]
          },
        ]
      }
      inspections: {
        Row: {
          confidence: number | null
          evidence_id: string
          findings_json: Json
          id: string
          review_status: Database["public"]["Enums"]["review_status"]
        }
        Insert: {
          confidence?: number | null
          evidence_id: string
          findings_json?: Json
          id?: string
          review_status?: Database["public"]["Enums"]["review_status"]
        }
        Update: {
          confidence?: number | null
          evidence_id?: string
          findings_json?: Json
          id?: string
          review_status?: Database["public"]["Enums"]["review_status"]
        }
        Relationships: [
          {
            foreignKeyName: "inspections_evidence_id_fkey"
            columns: ["evidence_id"]
            isOneToOne: false
            referencedRelation: "evidence"
            referencedColumns: ["id"]
          },
        ]
      }
      organizations: {
        Row: {
          id: string
          name: string
          org_type: Database["public"]["Enums"]["org_type"]
        }
        Insert: {
          id?: string
          name: string
          org_type: Database["public"]["Enums"]["org_type"]
        }
        Update: {
          id?: string
          name?: string
          org_type?: Database["public"]["Enums"]["org_type"]
        }
        Relationships: []
      }
      profiles: {
        Row: {
          id: string
          name: string | null
          organization_id: string | null
          role: Database["public"]["Enums"]["user_role"] | null
        }
        Insert: {
          id: string
          name?: string | null
          organization_id?: string | null
          role?: Database["public"]["Enums"]["user_role"] | null
        }
        Update: {
          id?: string
          name?: string | null
          organization_id?: string | null
          role?: Database["public"]["Enums"]["user_role"] | null
        }
        Relationships: [
          {
            foreignKeyName: "profiles_organization_id_fkey"
            columns: ["organization_id"]
            isOneToOne: false
            referencedRelation: "organizations"
            referencedColumns: ["id"]
          },
        ]
      }
      shipments: {
        Row: {
          buyer_org_id: string
          created_at: string
          id: string
          invoice_amount: number
          item_description: string
          po_number: string
          quantity: number
          status: Database["public"]["Enums"]["shipment_status"]
          supplier_org_id: string
        }
        Insert: {
          buyer_org_id: string
          created_at?: string
          id?: string
          invoice_amount: number
          item_description: string
          po_number: string
          quantity: number
          status?: Database["public"]["Enums"]["shipment_status"]
          supplier_org_id: string
        }
        Update: {
          buyer_org_id?: string
          created_at?: string
          id?: string
          invoice_amount?: number
          item_description?: string
          po_number?: string
          quantity?: number
          status?: Database["public"]["Enums"]["shipment_status"]
          supplier_org_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "shipments_buyer_org_id_fkey"
            columns: ["buyer_org_id"]
            isOneToOne: false
            referencedRelation: "organizations"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "shipments_supplier_org_id_fkey"
            columns: ["supplier_org_id"]
            isOneToOne: false
            referencedRelation: "organizations"
            referencedColumns: ["id"]
          },
        ]
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      can_access_shipment: { Args: { _shipment_id: string }; Returns: boolean }
      is_reviewer: { Args: never; Returns: boolean }
      my_org_id: { Args: never; Returns: string }
    }
    Enums: {
      adjustment_status: "proposed" | "accepted" | "disputed"
      decision_type: "accept" | "dispute"
      evidence_type: "dispatch" | "receipt"
      org_type: "buyer" | "supplier"
      review_status: "auto_accepted" | "needs_review" | "human_corrected"
      shipment_status:
        | "draft"
        | "agreed"
        | "in_transit"
        | "inspection"
        | "proposed"
        | "accepted"
        | "disputed"
        | "resolved"
      user_role: "buyer" | "supplier" | "reviewer"
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends (DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never) = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends (PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never) = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {
      adjustment_status: ["proposed", "accepted", "disputed"],
      decision_type: ["accept", "dispute"],
      evidence_type: ["dispatch", "receipt"],
      org_type: ["buyer", "supplier"],
      review_status: ["auto_accepted", "needs_review", "human_corrected"],
      shipment_status: [
        "draft",
        "agreed",
        "in_transit",
        "inspection",
        "proposed",
        "accepted",
        "disputed",
        "resolved",
      ],
      user_role: ["buyer", "supplier", "reviewer"],
    },
  },
} as const
