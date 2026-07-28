import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import type { ChatSessionRead } from "../api/types";

interface SessionsState {
  sessions: ChatSessionRead[];
  refresh: () => Promise<void>;
}

const SessionsContext = createContext<SessionsState | null>(null);

/** Session list shared between the sidebar History and the chat page. */
export function SessionsProvider({ children }: { children: ReactNode }) {
  const [sessions, setSessions] = useState<ChatSessionRead[]>([]);

  const refresh = useCallback(async () => {
    try {
      setSessions(await api<ChatSessionRead[]>("/api/v1/chat/sessions"));
    } catch {
      /* sidebar stays as-is on transient failures */
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <SessionsContext.Provider value={{ sessions, refresh }}>
      {children}
    </SessionsContext.Provider>
  );
}

export function useSessions(): SessionsState {
  const ctx = useContext(SessionsContext);
  if (!ctx) throw new Error("useSessions must be used within SessionsProvider");
  return ctx;
}
