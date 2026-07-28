import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api/client";
import type { EvalRun, GoldenItem } from "../api/types";

const CATEGORIES = [
  "fees",
  "product_howto",
  "account_issue",
  "general_web",
  "out_of_scope",
  "adversarial",
  "multi_turn",
];

export default function EvaluationPage() {
  const [items, setItems] = useState<GoldenItem[]>([]);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [tab, setTab] = useState<"dataset" | "runs">("dataset");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runName, setRunName] = useState("");
  const [busy, setBusy] = useState(false);

  const [newItem, setNewItem] = useState({
    question: "",
    category: "product_howto",
    expected_answer: "",
    gold_source_urls: "",
  });

  const load = useCallback(async () => {
    setItems(await api<GoldenItem[]>("/api/v1/evaluation/golden-items"));
    setRuns(await api<EvalRun[]>("/api/v1/evaluation/runs"));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function addItem(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api("/api/v1/evaluation/golden-items", {
        method: "POST",
        body: {
          question: newItem.question,
          category: newItem.category,
          expected_answer: newItem.expected_answer,
          gold_source_urls: newItem.gold_source_urls
            .split(/[\n,]/)
            .map((u) => u.trim())
            .filter(Boolean),
        },
      });
      setAdding(false);
      setNewItem({ question: "", category: "product_howto", expected_answer: "", gold_source_urls: "" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao salvar item");
    }
  }

  async function startRun(layer: "retrieval" | "full") {
    setError(null);
    setBusy(true);
    try {
      await api("/api/v1/evaluation/runs", {
        method: "POST",
        body: {
          name: runName || `${layer}-${new Date().toISOString().slice(0, 16)}`,
          layer,
        },
      });
      setRunName("");
      setTab("runs");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao rodar avaliação");
    } finally {
      setBusy(false);
    }
  }

  async function syncLangfuseDataset() {
    setError(null);
    setBusy(true);
    try {
      const result = await api<{ dataset: string; items_synced: number }>(
        "/api/v1/evaluation/langfuse/sync-dataset",
        { method: "POST" },
      );
      alert(`Dataset '${result.dataset}' sincronizado: ${result.items_synced} itens.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao sincronizar dataset");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Avaliação</h1>
          <p className="text-sm text-faint">
            Golden dataset + runs versionados. Retrieval é determinístico
            (recall@k, MRR); o experimento RAGAS roda no dataset do Langfuse
            com faithfulness e answer relevancy.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            value={runName}
            onChange={(e) => setRunName(e.target.value)}
            placeholder="nome do run (ex.: baseline)"
            className="rounded-lg border border-line bg-raised px-3 py-1.5 text-sm"
          />
          <button
            disabled={busy}
            onClick={() => void startRun("retrieval")}
            className="rounded-lg bg-ok px-4 py-1.5 text-sm font-medium text-ink hover:opacity-90 disabled:opacity-40"
          >
            {busy ? "Rodando…" : "Retrieval eval"}
          </button>
          <button
            disabled={busy}
            onClick={() => void startRun("full")}
            title="RAG ponta a ponta + RAGAS no Langfuse (demora alguns minutos)"
            className="rounded-lg bg-clay px-4 py-1.5 text-sm font-medium text-ink hover:opacity-90 disabled:opacity-40"
          >
            {busy ? "Rodando…" : "Experimento RAGAS"}
          </button>
          <button
            disabled={busy}
            onClick={() => void syncLangfuseDataset()}
            title="Envia o golden dataset para o Langfuse (getnet-qa-v1)"
            className="rounded-lg bg-raised px-3 py-1.5 text-sm text-mut hover:bg-hover"
          >
            Sync → Langfuse
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-clay-soft px-3 py-2 text-sm text-clay">
          {error}
        </div>
      )}

      <div className="mb-4 flex gap-2 border-b border-line">
        {(["dataset", "runs"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm ${
              tab === t
                ? "border-b-2 border-clay text-clay"
                : "text-faint hover:text-fg"
            }`}
          >
            {t === "dataset" ? `Golden Dataset (${items.length})` : `Runs (${runs.length})`}
          </button>
        ))}
      </div>

      {tab === "dataset" && (
        <div>
          <button
            onClick={() => setAdding(!adding)}
            className="mb-3 rounded-lg bg-clay px-3 py-1.5 text-sm hover:opacity-90"
          >
            + Adicionar item
          </button>
          {adding && (
            <form
              onSubmit={addItem}
              className="mb-4 rounded-xl border border-line bg-surface p-4"
            >
              <div className="grid gap-3 md:grid-cols-2">
                <label className="text-sm md:col-span-2">
                  <span className="text-mut">Pergunta</span>
                  <input
                    required
                    value={newItem.question}
                    onChange={(e) => setNewItem({ ...newItem, question: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2"
                  />
                </label>
                <label className="text-sm">
                  <span className="text-mut">Categoria</span>
                  <select
                    value={newItem.category}
                    onChange={(e) => setNewItem({ ...newItem, category: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2"
                  >
                    {CATEGORIES.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                </label>
                <label className="text-sm">
                  <span className="text-mut">Gold URLs (uma por linha)</span>
                  <textarea
                    rows={2}
                    value={newItem.gold_source_urls}
                    onChange={(e) =>
                      setNewItem({ ...newItem, gold_source_urls: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2 text-xs"
                  />
                </label>
                <label className="text-sm md:col-span-2">
                  <span className="text-mut">Resposta esperada (referência)</span>
                  <textarea
                    rows={2}
                    value={newItem.expected_answer}
                    onChange={(e) =>
                      setNewItem({ ...newItem, expected_answer: e.target.value })
                    }
                    className="mt-1 w-full rounded-lg border border-line bg-raised px-3 py-2"
                  />
                </label>
              </div>
              <button className="mt-3 rounded-lg bg-clay px-4 py-1.5 text-sm hover:opacity-90">
                Salvar item
              </button>
            </form>
          )}
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface text-xs uppercase text-faint">
                <tr>
                  <th className="px-3 py-2">Pergunta</th>
                  <th className="px-3 py-2">Categoria</th>
                  <th className="px-3 py-2">Origem</th>
                  <th className="px-3 py-2">Gold URLs</th>
                  <th className="px-3 py-2">Rota esperada</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {items.map((item) => (
                  <tr key={item.id} className="hover:bg-surface">
                    <td className="max-w-md truncate px-3 py-2">{item.question}</td>
                    <td className="px-3 py-2">
                      <span className="rounded bg-raised px-2 py-0.5 text-xs">
                        {item.category}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-faint">{item.provenance}</td>
                    <td className="px-3 py-2 text-xs text-faint">
                      {item.gold_source_urls.length || "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-faint">
                      {item.expected_route ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-faint">
            💡 Respostas com 👎 no chat podem ser promovidas a itens golden — o
            ciclo produção → dataset → regressão.
          </p>
        </div>
      )}

      {tab === "runs" && (
        <div className="grid gap-3">
          {runs.length === 0 && (
            <div className="rounded-xl border border-line p-8 text-center text-faint">
              Nenhum run ainda. Rode a primeira avaliação para criar o baseline.
            </div>
          )}
          {runs.map((run) => (
            <div
              key={run.id}
              className="rounded-xl border border-line bg-surface p-4"
            >
              <div className="flex items-center gap-2">
                <span className="font-medium">{run.name}</span>
                <span className="rounded bg-raised px-2 py-0.5 text-[10px] uppercase text-mut">
                  {run.layer}
                </span>
                <span
                  className={`rounded px-2 py-0.5 text-[10px] uppercase ${
                    run.status === "completed"
                      ? "bg-ok/15 text-ok"
                      : "bg-clay-soft text-clay"
                  }`}
                >
                  {run.status}
                </span>
                <span className="ml-auto text-xs text-faint">
                  {new Date(run.created_at).toLocaleString()}
                </span>
              </div>
              {run.error && (
                <div className="mt-2 text-sm text-clay">{run.error}</div>
              )}
              {Object.keys(run.metrics).length > 0 && (
                <div className="mt-3 flex flex-wrap gap-3">
                  {Object.entries(run.metrics).map(([key, value]) => (
                    <div
                      key={key}
                      className="rounded-lg bg-raised px-3 py-2 text-center"
                    >
                      <div className="text-lg font-semibold text-clay">
                        {typeof value === "number" && value <= 1
                          ? (value * 100).toFixed(1) + "%"
                          : value}
                      </div>
                      <div className="text-[10px] uppercase text-faint">{key}</div>
                    </div>
                  ))}
                </div>
              )}
              <div className="mt-2 text-xs text-faint">
                config: {JSON.stringify(run.config)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
