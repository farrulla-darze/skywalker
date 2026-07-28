import { useState } from "react";
import { api } from "../api/client";
import type { ChatMessageRead } from "../api/types";

/** Feedback (👍/👎 → Langfuse trace score) + flag for human review (annotation queue). */
export default function MessageActions({
  message,
  onChanged,
}: {
  message: ChatMessageRead;
  onChanged: () => void;
}) {
  const [commenting, setCommenting] = useState(false);
  const [comment, setComment] = useState("");
  const [flagged, setFlagged] = useState(false);
  const current = message.feedback?.rating;

  async function sendFeedback(rating: "up" | "down", withComment?: string) {
    await api(`/api/v1/chat/messages/${message.id}/feedback`, {
      method: "POST",
      body: { rating, comment: withComment || null },
    });
    setCommenting(false);
    setComment("");
    onChanged();
  }

  async function flagForReview() {
    try {
      await api(`/api/v1/chat/messages/${message.id}/review`, {
        method: "POST",
        body: { comment: comment || null },
      });
      setFlagged(true);
    } catch {
      /* review queue unavailable — quietly ignore */
    }
  }

  const buttonClass = (active: boolean) =>
    `rounded px-1.5 py-0.5 text-[13px] transition-colors hover:bg-hover ${
      active ? "text-clay" : "text-faint hover:text-mut"
    }`;

  return (
    <div className="mt-1.5 flex items-center gap-1">
      <button
        title="Resposta útil"
        onClick={() => void sendFeedback("up")}
        className={buttonClass(current === "up")}
      >
        <ThumbIcon up />
      </button>
      <button
        title="Resposta ruim"
        onClick={() => setCommenting(!commenting)}
        className={buttonClass(current === "down")}
      >
        <ThumbIcon />
      </button>
      <button
        title="Marcar para revisão humana"
        onClick={() => void flagForReview()}
        className={buttonClass(flagged)}
      >
        {flagged ? "revisão ✓" : "revisar"}
      </button>
      {message.feedback?.comment && (
        <span className="text-[12px] text-faint">“{message.feedback.comment}”</span>
      )}
      {commenting && (
        <input
          autoFocus
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void sendFeedback("down", comment)}
          placeholder="O que estava errado? Enter envia"
          className="w-64 rounded-lg border border-line bg-raised px-2 py-1 text-[12px] text-fg placeholder-faint outline-none"
        />
      )}
    </div>
  );
}

function ThumbIcon({ up }: { up?: boolean }) {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      style={up ? undefined : { transform: "rotate(180deg)" }}
    >
      <path
        d="M7 10v12M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
