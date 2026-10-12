import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";
import { me, type User } from "../api/auth";
import { tokens } from "../api/client";

interface AuthCtx { user: User | null; loading: boolean; logout: () => void; refetch: () => void }
const Ctx = createContext<AuthCtx>(null!);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["me"], queryFn: me, enabled: !!tokens.access, retry: false });
  const logout = () => { tokens.clear(); qc.clear(); window.location.assign("/login"); };
  return (
    <Ctx.Provider value={{ user: q.data ?? null, loading: !!tokens.access && q.isLoading, logout, refetch: () => void q.refetch() }}>
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);
