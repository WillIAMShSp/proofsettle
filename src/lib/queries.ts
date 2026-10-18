// TanStack Query hooks over the API. Queries run only in the browser once a role is known:
// on the server (SSR) and before login there is no role, so `enabled` is false.

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import {
  ApiError,
  USE_MOCK,
  httpApi,
  type Api,
  type Role,
  type ShipmentDetail,
  type ShipmentSummary,
} from "./api";
import { mockApi } from "./mock-api";
import { useStore } from "./store";

export { USE_MOCK };
export const api: Api = USE_MOCK ? mockApi : httpApi;

// Which shipments the API returns depends on the signed-in account, and a detail's `actions`
// on its role, so both are part of the keys: one account's data is never shown to another.
type Account = string | null;
export const keys = {
  list: (account: Account) => ["shipments", account] as const,
  detail: (id: string, account: Account, role: Role | null) =>
    ["shipment", id, account, role] as const,
};

function useAccount() {
  const { user, role } = useStore();
  return { account: user?.id ?? null, role };
}

export function useShipments() {
  const { account, role } = useAccount();
  return useQuery({
    queryKey: keys.list(account),
    queryFn: api.listShipments,
    enabled: role !== null,
  });
}

export function useShipment(id: string) {
  const { account, role } = useAccount();
  return useQuery({
    queryKey: keys.detail(id, account, role),
    queryFn: () => api.getShipment(id),
    enabled: role !== null,
    retry: (count, error) => count < 2 && !(error instanceof ApiError && error.status === 404),
    // The backend anchors on Solana after it answers; poll until nothing is pending.
    refetchInterval: (q) =>
      q.state.data?.events.some((e) => e.chainStatus === "pending") ? 2000 : false,
  });
}

const toSummary = ({
  id,
  title,
  buyer,
  supplier,
  amount,
  status,
  recipientEmail,
}: ShipmentDetail): ShipmentSummary => ({
  id,
  title,
  buyer,
  supplier,
  amount,
  status,
  recipientEmail,
});

/** Put a write's returned detail into the cache instead of refetching. */
function applyDetail(qc: QueryClient, detail: ShipmentDetail, account: Account, role: Role | null) {
  qc.setQueryData(keys.detail(detail.id, account, role), detail);
  qc.setQueryData<ShipmentSummary[]>(keys.list(account), (list) =>
    list?.map((s) => (s.id === detail.id ? toSummary(detail) : s)),
  );
  // Cached copies for other accounts or roles are stale; refetch them when next shown.
  qc.invalidateQueries({
    queryKey: ["shipment", detail.id],
    predicate: (q) => q.queryKey[2] !== account || q.queryKey[3] !== role,
  });
}

/**
 * A write that returns the updated shipment detail. Pass the call to `mutate`, e.g.
 * `write.mutate(() => api.accept(id))`; a failure is in `write.error`.
 */
export function useShipmentWrite() {
  const qc = useQueryClient();
  const { account, role } = useAccount();
  return useMutation({
    mutationFn: (call: () => Promise<ShipmentDetail>) => call(),
    onSuccess: (detail) => applyDetail(qc, detail, account, role),
  });
}

/** Buyer only. The new shipment goes into the detail cache and the list is refetched. */
export function useCreateShipment() {
  const qc = useQueryClient();
  const { account, role } = useAccount();
  return useMutation({
    mutationFn: api.createShipment,
    onSuccess: (detail) => {
      qc.setQueryData(keys.detail(detail.id, account, role), detail);
      void qc.invalidateQueries({ queryKey: ["shipments"] });
    },
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
