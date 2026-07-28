import { useState } from "react";
import { api } from "../api/client";

/** 1–5 conversation rating → Langfuse session score. */
export default function SessionRating({ sessionId }: { sessionId: string }) {
  const [open, setOpen] = useState(false);
  const [hover, setHover] = useState(0);
  const [saved, setSaved] = useState(0);
  const [comment, setComment] = useState("");

  async function send(rating: number) {
    setSaved(rating);
    await api(`/api/v1/chat/sessions/${sessionId}/score`, {
      method: "POST",
      body: { rating, comment: comment || null },
    });
    setOpen(false);
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="rounded-lg px-2 py-1 text-[12px] text-mut transition-colors hover:bg-hover hover:text-fg"
      >
        {saved ? `Avaliada ${"★".repeat(saved)}` : "Avaliar conversa"}
      </button>
      {open && (
        <div className="absolute right-0 top-8 z-10 w-60 rounded-xl border border-line bg-raised p-3 shadow-xl">
          <div className="mb-2 flex justify-center gap-1">
            {[1, 2, 3, 4, 5].map((star) => (
              <button
                key={star}
                onMouseEnter={() => setHover(star)}
                onMouseLeave={() => setHover(0)}
                onClick={() => void send(star)}
                className={`text-xl transition-colors ${
                  star <= (hover || saved) ? "text-warn" : "text-line"
                }`}
              >
                ★
              </button>
            ))}
          </div>
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Comentário (opcional)"
            className="w-full rounded-lg border border-line bg-ink px-2 py-1.5 text-[12px] text-fg placeholder-faint outline-none"
          />
        </div>
      )}
    </div>
  );
}
