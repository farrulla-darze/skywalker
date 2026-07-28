import type { ReactNode } from "react";
import { NavLink, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { SessionsProvider, useSessions } from "../context/SessionsContext";

const NAV = [
  { to: "/agents", label: "Agentes" },
  { to: "/integrations", label: "Integrações" },
  { to: "/evaluation", label: "Avaliação" },
];

function Sidebar() {
  const { user, logout } = useAuth();
  const { sessions } = useSessions();
  const navigate = useNavigate();
  const { sessionId } = useParams();

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-line bg-surface">
      <div className="px-4 pt-5 pb-3">
        <button
          onClick={() => navigate("/")}
          className="text-[15px] font-semibold tracking-tight text-fg"
        >
          Skywalker
        </button>
      </div>

      <div className="px-3">
        <button
          onClick={() => navigate("/")}
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-fg hover:bg-hover"
        >
          <span className="text-clay">＋</span> Nova conversa
        </button>
        <nav className="mt-1 flex flex-col">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive ? "bg-raised text-fg" : "text-mut hover:bg-hover hover:text-fg"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="mt-5 flex min-h-0 flex-1 flex-col px-3">
        <div className="px-3 pb-2 text-[11px] font-medium uppercase tracking-wider text-faint">
          Histórico
        </div>
        <div className="flex-1 overflow-y-auto pb-2">
          {sessions.length === 0 && (
            <p className="px-3 text-[13px] text-faint">
              Suas conversas aparecem aqui.
            </p>
          )}
          {sessions.map((session) => (
            <button
              key={session.id}
              onClick={() => navigate(`/c/${session.id}`)}
              title={session.title}
              className={`block w-full truncate rounded-lg px-3 py-1.5 text-left text-[13px] transition-colors ${
                session.id === sessionId
                  ? "bg-raised text-fg"
                  : "text-mut hover:bg-hover hover:text-fg"
              }`}
            >
              {session.handoff_state !== "bot" && (
                <span className="mr-1 text-ok">●</span>
              )}
              {session.title}
            </button>
          ))}
        </div>
      </div>

      <div className="border-t border-line px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-[13px] text-fg">{user?.full_name}</div>
            <div className="truncate text-[11px] text-faint">{user?.email}</div>
          </div>
          <button
            onClick={() => void logout()}
            title="Sair"
            className="shrink-0 rounded-lg px-2 py-1 text-[13px] text-mut hover:bg-hover hover:text-fg"
          >
            Sair
          </button>
        </div>
      </div>
    </aside>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <SessionsProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-auto">{children}</main>
      </div>
    </SessionsProvider>
  );
}
