import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { AgentRead, ToolInfo } from "../api/types";

interface AgentForm {
  id?: string;
  name: string;
  slug: string;
  description: string;
  instructions: string;
  model: string;
  kind: "router" | "specialist";
  expose_as_tool: boolean;
  enabled: boolean;
  tools: string[];
}

const EMPTY: AgentForm = {
  name: "",
  slug: "",
  description: "",
  instructions: "",
  model: "",
  kind: "specialist",
  expose_as_tool: true,
  enabled: true,
  tools: [],
};

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentRead[]>([]);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [form, setForm] = useState<AgentForm | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setAgents(await api<AgentRead[]>("/api/v1/agents"));
    setTools(await api<ToolInfo[]>("/api/v1/tools"));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function edit(agent: AgentRead) {
    setForm({
      id: agent.id,
      name: agent.name,
      slug: agent.slug,
      description: agent.description,
      instructions: agent.instructions,
      model: agent.model ?? "",
      kind: agent.kind,
      expose_as_tool: agent.expose_as_tool,
      enabled: agent.enabled,
      tools: agent.tools,
    });
    setError(null);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!form) return;
    setError(null);
    const body = { ...form, model: form.model || null };
    try {
      if (form.id) {
        const { id, slug: _slug, ...update } = body;
        await api(`/api/v1/agents/${id}`, { method: "PATCH", body: update });
      } else {
        await api("/api/v1/agents", { method: "POST", body });
      }
      setForm(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao salvar");
    }
  }

  async function remove(agent: AgentRead) {
    if (!confirm(`Excluir o agente "${agent.name}"?`)) return;
    try {
      await api(`/api/v1/agents/${agent.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Falha ao excluir");
    }
  }

  function toggleTool(name: string) {
    if (!form) return;
    setForm({
      ...form,
      tools: form.tools.includes(name)
        ? form.tools.filter((t) => t !== name)
        : [...form.tools, name],
    });
  }

  return (
    <div className="mx-auto max-w-5xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Agentes</h1>
          <p className="text-sm text-faint">
            Agentes são registros de banco — crie, edite e conecte tools sem tocar em código.
          </p>
        </div>
        <button
          onClick={() => {
            setForm({ ...EMPTY });
            setError(null);
          }}
          className="rounded-lg bg-clay px-4 py-2 text-sm font-medium hover:opacity-90"
        >
          + Novo agente
        </button>
      </div>

      <div className="flex flex-col gap-3">
        {agents.map((agent) => (
          <div
            key={agent.id}
            className="flex w-full min-w-0 items-start justify-between overflow-hidden rounded-xl border border-line bg-surface p-4"
          >
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 truncate font-medium">{agent.name}</span>
                <span className="rounded bg-raised px-2 py-0.5 text-[10px] uppercase text-mut">
                  {agent.kind}
                </span>
                {agent.is_system && (
                  <span className="rounded bg-warn/15 px-2 py-0.5 text-[10px] uppercase text-warn">
                    sistema
                  </span>
                )}
                {!agent.enabled && (
                  <span className="rounded bg-clay-soft px-2 py-0.5 text-[10px] uppercase text-clay">
                    desativado
                  </span>
                )}
              </div>
              <p className="mt-1 truncate text-sm text-faint">{agent.description}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {agent.tools.map((tool) => (
                  <span
                    key={tool}
                    className="max-w-full truncate rounded bg-ok/15 px-2 py-0.5 text-[11px] text-ok"
                  >
                    🔧 {tool}
                  </span>
                ))}
              </div>
            </div>
            <div className="ml-4 flex shrink-0 gap-2">
              <button
                onClick={() => edit(agent)}
                className="rounded-lg bg-raised px-3 py-1.5 text-sm hover:bg-hover"
              >
                Editar
              </button>
              {!agent.is_system && (
                <button
                  onClick={() => void remove(agent)}
                  className="rounded-lg bg-clay-soft px-3 py-1.5 text-sm text-clay hover:opacity-90"
                >
                  Excluir
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {form && (
        <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/60 p-4">
          <form
            onSubmit={save}
            className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-line bg-surface p-6"
          >
            <h2 className="mb-4 text-lg font-semibold">
              {form.id ? "Editar agente" : "Novo agente"}
            </h2>
            {error && (
              <div className="mb-3 rounded-lg bg-clay-soft px-3 py-2 text-sm text-clay">
                {error}
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <label className="text-sm">
                <span className="text-mut">Nome</span>
                <input
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2"
                />
              </label>
              <label className="text-sm">
                <span className="text-mut">Slug {form.id && "(fixo)"}</span>
                <input
                  required
                  disabled={!!form.id}
                  pattern="[a-z0-9][a-z0-9_-]+"
                  value={form.slug}
                  onChange={(e) => setForm({ ...form, slug: e.target.value })}
                  className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2 disabled:opacity-50"
                />
              </label>
            </div>
            <label className="mt-3 block text-sm">
              <span className="text-mut">Descrição (o roteador usa para decidir delegar)</span>
              <input
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2"
              />
            </label>
            <label className="mt-3 block text-sm">
              <span className="text-mut">Instructions (system prompt)</span>
              <textarea
                required
                rows={8}
                value={form.instructions}
                onChange={(e) => setForm({ ...form, instructions: e.target.value })}
                className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2 font-mono text-xs"
              />
            </label>
            <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
              <label>
                <span className="text-mut">Modelo (vazio = padrão)</span>
                <input
                  value={form.model}
                  placeholder="openai:gpt-5-mini"
                  onChange={(e) => setForm({ ...form, model: e.target.value })}
                  className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2"
                />
              </label>
              <label>
                <span className="text-mut">Tipo</span>
                <select
                  value={form.kind}
                  onChange={(e) =>
                    setForm({ ...form, kind: e.target.value as AgentForm["kind"] })
                  }
                  className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2"
                >
                  <option value="specialist">specialist</option>
                  <option value="router">router</option>
                </select>
              </label>
              <div className="flex flex-col justify-end gap-1">
                <label className="flex items-center gap-2 text-mut">
                  <input
                    type="checkbox"
                    checked={form.enabled}
                    onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                  />
                  Ativo
                </label>
                <label className="flex items-center gap-2 text-mut">
                  <input
                    type="checkbox"
                    checked={form.expose_as_tool}
                    onChange={(e) =>
                      setForm({ ...form, expose_as_tool: e.target.checked })
                    }
                  />
                  Visível ao router
                </label>
              </div>
            </div>
            <div className="mt-4">
              <span className="text-sm text-mut">Tools conectadas</span>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {tools.map((tool) => (
                  <label
                    key={tool.name}
                    className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2 text-xs ${
                      form.tools.includes(tool.name)
                        ? "border-ok/50 bg-ok/10"
                        : "border-line bg-surface"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={form.tools.includes(tool.name)}
                      onChange={() => toggleTool(tool.name)}
                      className="mt-0.5"
                    />
                    <span>
                      <span className="font-medium text-fg">{tool.label}</span>
                      <span className="ml-1 text-faint">({tool.category})</span>
                      <div className="mt-0.5 text-faint">{tool.description}</div>
                    </span>
                  </label>
                ))}
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setForm(null)}
                className="rounded-lg bg-raised px-4 py-2 text-sm hover:bg-hover"
              >
                Cancelar
              </button>
              <button className="rounded-lg bg-clay px-4 py-2 text-sm font-medium hover:opacity-90">
                Salvar
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
