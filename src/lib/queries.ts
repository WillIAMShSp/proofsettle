// TanStack Query hooks over the API. Queries run only in the browser once a role is known:
// on the server (SSR) and before login there is no role, so `enabled` is false.

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import {
  ApiError,
  httpApi,
  type Api,
  type Role,
  type ShipmentDetail,
  type ShipmentSummary,
} from "./api";
import { mockApi } from "./mock-api";
import { useStore } from "./store";

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";
export const api: Api = USE_MOCK ? mockApi : httpApi;

// `actions` in a detail depend on the caller's role, so the role is part of its key.
export const keys = {
  list: ["shipments"] as const,
  detail: (id: string, role: Role | null) => ["shipment", id, role] as const,
};

export function useShipments() {
  const { role } = useStore();
  return useQuery({ queryKey: keys.list, queryFn: api.listShipments, enabled: role !== null });
}

export function useShipment(id: string) {
  const { role } = useStore();
  return useQuery({
    queryKey: keys.detail(id, role),
    queryFn: () => api.getShipment(id),
    enabled: role !== null,
    retry: (count, error) => count < 2 && !(error instanceof ApiError && error.status === 404),
  });
}

const toSummary = ({
  id,
  title,
  buyer,
  supplier,
  amount,
  status,
}: ShipmentDetail): ShipmentSummary => ({
  id,
  title,
  buyer,
  supplier,
  amount,
  status,
});

/** Put a write's returned detail into the cache instead of refetching. */
function applyDetail(qc: QueryClient, detail: ShipmentDetail, role: Role | null) {
  qc.setQueryData(keys.detail(detail.id, role), detail);
  qc.setQueryData<ShipmentSummary[]>(keys.list, (list) =>
    list?.map((s) => (s.id === detail.id ? toSummary(detail) : s)),
  );
  // Cached copies for other roles have stale `actions`; refetch them when next shown.
  qc.invalidateQueries({
    queryKey: ["shipment", detail.id],
    predicate: (q) => q.queryKey[2] !== role,
  });
}

/**
 * A write that returns the updated shipment detail. Pass the call to `mutate`, e.g.
 * `write.mutate(() => api.accept(id))`; a failure is in `write.error`.
 */
export function useShipmentWrite() {
  const qc = useQueryClient();
  const { role } = useStore();
  return useMutation({
    mutationFn: (call: () => Promise<ShipmentDetail>) => call(),
    onSuccess: (detail) => applyDetail(qc, detail, role),
  });
}

export function useVerifyAudit(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.verifyAudit(id),
    // Each evidence item's `verified` is stored by the run, so refresh the detail.
    onSuccess: () => qc.invalidateQueries({ queryKey: ["shipment", id] }),
  });
}

export function useDevReset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.devReset,
    onSuccess: () => qc.invalidateQueries(),
  });
}
