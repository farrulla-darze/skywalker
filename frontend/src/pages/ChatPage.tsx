import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, apiStream } from "../api/client";
import type { ChatMessageRead, ChatSessionRead, StepRecord } from "../api/types";
import ChatInput from "../components/ChatInput";
import MessageBody from "../components/MessageBody";
import MessageActions from "../components/MessageActions";
import SessionRating from "../components/SessionRating";
import ToolRail, { type LiveStep } from "../components/ToolRail";
import { useAuth } from "../context/AuthContext";
import { useSessions } from "../context/SessionsContext";

const SUGGESTIONS = [
  "Qual a diferença entre a Get Clássica e a Get Smart?",
  "Como funciona a antecipação de recebíveis?",
  "Em quantas parcelas posso dividir uma venda no crediário?",
];

interface StreamingState {
  steps: LiveStep[];
  text: string;
}

/** A step that fires while an `agent:` delegate step is still running belongs to it. */
function isSubStep(tool: string, steps: LiveStep[]): boolean {
  return (
    !tool.startsWith("agent:") &&
    steps.some((st) => st.running && st.tool.startsWith("agent:"))
  );
}

export default function ChatPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { sessions, refresh } = useSessions();
  const [messages, setMessages] = useState<ChatMessageRead[]>([]);
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const active = sessions.find((s) => s.id === sessionId);
  // While a send() is in flight, the sessionId effect must not refetch —
  // its GET races the POST and would wipe the optimistic user bubble.
  const sendingRef = useRef(false);

  const loadMessages = useCallback(async (id: string) => {
    setMessages(await api<ChatMessageRead[]>(`/api/v1/chat/sessions/${id}/messages`));
  }, []);

  useEffect(() => {
    if (sendingRef.current) return;
    if (sessionId) void loadMessages(sessionId);
    else setMessages([]);
  }, [sessionId, loadMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  async function send(text: string) {
    sendingRef.current = true;
    let id = sessionId;
    if (!id) {
      const session = await api<ChatSessionRead>("/api/v1/chat/sessions", {
        method: "POST",
        body: {},
      });
      id = session.id;
      navigate(`/c/${id}`, { replace: true });
      void refresh();
    }

    // optimistic user bubble
    setMessages((prev) => [
      ...prev,
      {
        id: `tmp-${Date.now()}`,
        session_id: id!,
        role: "user",
        content: text,
        steps: null,
        usage: null,
        trace_id: null,
        created_at: new Date().toISOString(),
        feedback: null,
      },
    ]);
    setStreaming({ steps: [], text: "" });

    try {
      for await (const event of apiStream(
        `/api/v1/chat/sessions/${id}/messages/stream`,
        { content: text },
      )) {
        if (event.type === "step_started") {
          setStreaming((s) =>
            s && {
              ...s,
              steps: [
                ...s.steps,
                {
                  tool: event.tool as string,
                  args: event.args as Record<string, unknown> | null,
                  running: true,
                  nested: isSubStep(event.tool as string, s.steps),
                },
              ],
            },
          );
        } else if (event.type === "step_finished") {
          setStreaming((s) => {
            if (!s) return s;
            const steps = [...s.steps];
            const idx = steps.findLastIndex(
              (st) => st.tool === (event.tool as string) && st.running,
            );
            const finished: LiveStep = {
              tool: event.tool as string,
              args: (event.args as Record<string, unknown>) ?? null,
              result_preview: event.result_preview as string,
              duration_ms: event.duration_ms as number,
              nested_steps: (event.nested_steps as StepRecord[]) ?? null,
              running: false,
              nested:
                idx >= 0
                  ? steps[idx].nested
                  : isSubStep(event.tool as string, steps),
            };
            if (idx >= 0) steps[idx] = finished;
            else steps.push(finished);
            return { ...s, steps };
          });
        } else if (event.type === "token") {
          setStreaming((s) => s && { ...s, text: s.text + (event.delta as string) });
        } else if (event.type === "revised") {
          setStreaming((s) => s && { ...s, text: event.content as string });
        } else if (event.type === "done" || event.type === "error") {
          setStreaming(null);
          await loadMessages(id!);
          void refresh(); // title / handoff badge may have changed
        }
      }
    } catch {
      setStreaming(null);
      await loadMessages(id!);
    } finally {
      sendingRef.current = false;
    }
  }

  const firstName = user?.full_name?.split(" ")[0] ?? "";
  const isEmpty = !sessionId && messages.length === 0;

  if (isEmpty) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-6">
        <div className="w-full max-w-2xl">
          <p className="mb-1 text-center text-[13px] font-medium uppercase tracking-widest text-faint">
            Suporte Getnet
          </p>
          <h1 className="mb-8 text-center font-serifd text-[34px] italic leading-tight text-fg">
            Como posso ajudar{firstName ? `, ${firstName}` : ""}?
          </h1>
          <ChatInput onSend={(t) => void send(t)} autoFocus />
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                onClick={() => void send(suggestion)}
                className="rounded-full border border-line px-3.5 py-1.5 text-[13px] text-mut transition-colors hover:border-faint hover:text-fg"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-line px-6 py-2.5">
        <div className="min-w-0">
          <span className="truncate text-[13px] text-mut">{active?.title ?? ""}</span>
          {active && active.handoff_state !== "bot" && (
            <span className="ml-2 rounded-full bg-ok/15 px-2 py-0.5 text-[11px] text-ok">
              atendimento humano
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {active && (
            <span className="font-monoui text-[11px] text-faint">
              {(active.input_tokens + active.output_tokens).toLocaleString()} tokens
            </span>
          )}
          {sessionId && <SessionRating sessionId={sessionId} />}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-2xl flex-col gap-5 px-6 py-8">
          {messages.map((message) => (
            <MessageRow
              key={message.id}
              message={message}
              onChanged={() => sessionId && void loadMessages(sessionId)}
              onSuggestionClick={(text) => void send(text)}
              suggestionsDisabled={streaming !== null}
            />
          ))}

          {streaming && (
            <div>
              <ToolRail
                steps={streaming.steps}
                running={streaming.text === ""}
              />
              {streaming.text && (
                <MessageBody content={streaming.text} caret />
              )}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="px-6 pb-5 pt-1">
        <ChatInput onSend={(t) => void send(t)} disabled={streaming !== null} />
      </div>
    </div>
  );
}

function MessageRow({
  message,
  onChanged,
  onSuggestionClick,
  suggestionsDisabled,
}: {
  message: ChatMessageRead;
  onChanged: () => void;
  onSuggestionClick: (text: string) => void;
  suggestionsDisabled: boolean;
}) {
  if (message.role === "user") {
    return (
      <div className="self-end">
        <div className="max-w-lg whitespace-pre-wrap rounded-2xl bg-raised px-4 py-2.5 text-[15px] leading-6 text-fg">
          {message.content}
        </div>
      </div>
    );
  }

  if (message.role === "system") {
    return (
      <div className="self-center rounded-full bg-surface px-4 py-1 text-[12px] text-faint">
        {message.content}
      </div>
    );
  }

  const isHuman = message.role === "human_agent";
  const steps: LiveStep[] = (message.steps ?? []).map((s) => ({ ...s, running: false }));
  const totalMs = steps.reduce((acc, s) => acc + (s.duration_ms ?? 0), 0);

  return (
    <div>
      {isHuman && (
        <div className="mb-1 text-[11px] font-medium uppercase tracking-wider text-ok">
          Atendente humano
        </div>
      )}
      <ToolRail steps={steps} running={false} totalMs={totalMs || undefined} />
      <MessageBody
        content={message.content}
        onSuggestionClick={onSuggestionClick}
        disabled={suggestionsDisabled}
      />
      {!isHuman && <MessageActions message={message} onChanged={onChanged} />}
    </div>
  );
}
