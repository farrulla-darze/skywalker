import { useEffect, useRef, useState, type KeyboardEvent } from "react";

const MAX_HEIGHT_PX = 180;

/** Constrained-width composer: grows with content up to a limit, then scrolls inside. */
export default function ChatInput({
  onSend,
  disabled,
  autoFocus,
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
    el.style.overflowY = el.scrollHeight > MAX_HEIGHT_PX ? "auto" : "hidden";
  }, [value]);

  function submit() {
    const text = value.trim();
    if (!text || disabled) return;
    setValue("");
    onSend(text);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl">
      <div className="flex items-end gap-2 rounded-2xl border border-line bg-raised px-4 py-3 transition-colors focus-within:border-faint">
        <textarea
          ref={ref}
          rows={1}
          autoFocus={autoFocus}
          value={value}
          disabled={disabled}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Pergunte algo…"
          className="max-h-[180px] flex-1 resize-none bg-transparent text-[15px] leading-6 text-fg placeholder-faint outline-none disabled:opacity-50"
        />
        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          title="Enviar (Enter)"
          className="mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-clay text-ink transition-opacity hover:opacity-90 disabled:opacity-30"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M12 19V5M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
      <p className="mt-2 text-center text-[11px] text-faint">
        Enter envia · Shift+Enter quebra linha
      </p>
    </div>
  );
}
