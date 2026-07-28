import { useState } from "react";
import type { StepRecord } from "../api/types";

export interface LiveStep {
  tool: string;
  args?: Record<string, unknown> | null;
  result_preview?: string;
  duration_ms?: number;
  running: boolean;
  nested_steps?: StepRecord[] | null;
}

function stepLabel(tool: string): string {
  if (tool.startsWith("agent:")) return `consultando ${tool.slice(6)}`;
  if (tool.startsWith("guardrail:")) return `verificação de segurança`;
  const labels: Record<string, string> = {
    rag_search: "buscando na base de conhecimento",
    graph_search: "consultando o grafo de fatos",
    web_search: "pesquisando na web",
    get_customer_overview: "consultando dados da conta",
    get_recent_operations: "consultando operações recentes",
    get_active_incidents: "verificando incidentes ativos",
    consult_human: "consultando especialista humano",
    release_transfer: "liberando transferência",
    set_transfers_enabled: "atualizando status de transferências",
    set_product_enabled: "atualizando produtos da conta",
  };
  return labels[tool] ?? tool;
}

function StepDetail({ step, depth = 0 }: { step: LiveStep | StepRecord; depth?: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginLeft: depth * 14 }}>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-baseline gap-2 rounded px-1 py-0.5 text-left font-monoui text-[12px] text-mut hover:bg-hover"
      >
        <span className="text-faint">{open ? "−" : "+"}</span>
        <span>{step.tool}</span>
        {step.duration_ms !== undefined && (
          <span className="ml-auto text-faint">{step.duration_ms}ms</span>
        )}
      </button>
      {open && (
        <div className="ml-4 border-l border-line pl-3 pt-1">
          {step.args && Object.keys(step.args).length > 0 && (
            <pre className="mb-1 overflow-x-auto whitespace-pre-wrap break-all font-monoui text-[11px] text-faint">
              {JSON.stringify(step.args, null, 2)}
            </pre>
          )}
          {step.result_preview && (
            <pre className="overflow-x-auto whitespace-pre-wrap break-all font-monoui text-[11px] leading-relaxed text-mut">
              {step.result_preview}
            </pre>
          )}
          {step.nested_steps?.map((nested, i) => (
            <StepDetail key={i} step={nested} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Live rail while the agent works; collapses to a one-line summary after. */
export default function ToolRail({
  steps,
  running,
  totalMs,
}: {
  steps: LiveStep[];
  running: boolean;
  totalMs?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  if (steps.length === 0 && !running) return null;

  if (running) {
    return (
      <div className="my-2 border-l-2 border-line pl-3">
        {steps.map((step, i) => (
          <div
            key={i}
            className="step-in flex items-baseline gap-2 py-0.5 font-monoui text-[12px]"
          >
            <span className={step.running ? "dot-live text-clay" : "text-ok"}>
              {step.running ? "●" : "✓"}
            </span>
            <span className={step.running ? "text-fg" : "text-mut"}>
              {stepLabel(step.tool)}
            </span>
            {!step.running && step.duration_ms !== undefined && (
              <span className="text-faint">{(step.duration_ms / 1000).toFixed(1)}s</span>
            )}
          </div>
        ))}
        {steps.length === 0 && (
          <div className="flex items-baseline gap-2 py-0.5 font-monoui text-[12px]">
            <span className="dot-live text-clay">●</span>
            <span className="text-mut">pensando</span>
          </div>
        )}
      </div>
    );
  }

  const shown = steps.filter((s) => !s.tool.startsWith("guardrail:"));
  if (shown.length === 0) return null;

  return (
    <div className="my-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="font-monoui text-[12px] text-faint transition-colors hover:text-mut"
      >
        {expanded ? "− " : "+ "}
        {shown.length} etapa{shown.length > 1 ? "s" : ""}
        {totalMs !== undefined && ` · ${(totalMs / 1000).toFixed(1)}s`}
      </button>
      {expanded && (
        <div className="mt-1 border-l-2 border-line pl-3">
          {steps.map((step, i) => (
            <StepDetail key={i} step={step} />
          ))}
        </div>
      )}
    </div>
  );
}
