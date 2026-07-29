import { useState } from "react";

const URL_RE = /https?:\/\/[^\s<>"')\]]+/g;
const BULLET_RE = /^([-*•↳]|\d+[.)])\s+/;
const SOURCES_HEADER_RE = /^\s*\**(fontes( consultadas)?|refer[êe]ncias|sources)\b/i;
const SUGGESTIONS_HEADER_RE =
  /^\s*\**(follow-?ups?|pr[oó]ximos passos|perguntas relacionadas|sugest[õo]es|voc[êe] (tamb[ée]m )?pode(ria)? perguntar)\b/i;
/** A short standalone bold line ("**Próximos passos**") — treated as a generic section boundary. */
const GENERIC_HEADING_RE = /^\*\*[^*]{2,60}\*\*:?\s*$/;

function isBoundary(line: string): boolean {
  return (
    SOURCES_HEADER_RE.test(line) ||
    SUGGESTIONS_HEADER_RE.test(line) ||
    GENERIC_HEADING_RE.test(line)
  );
}

/** Strip punctuation that trails a URL in prose ("...taxas/." → "...taxas/"). */
function cleanUrl(raw: string): string {
  return raw.replace(/[.,;:!?]+$/, "");
}

function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/**
 * Collect the bullet-list items that follow a section header, stopping at
 * whichever comes first: end of text, a blank line not followed by another
 * bullet, or the start of a new section header. Returns null when the lines
 * right after the header don't form a list at all (false-positive header
 * match, e.g. the word "fontes" used mid-sentence).
 */
function consumeListBlock(
  lines: string[],
  startIdx: number,
): { items: string[]; endIdx: number } | null {
  const items: string[] = [];
  let i = startIdx;
  while (i < lines.length) {
    const t = lines[i].trim();
    if (t === "") {
      let j = i + 1;
      while (j < lines.length && lines[j].trim() === "") j++;
      if (items.length > 0 && (j >= lines.length || !BULLET_RE.test(lines[j].trim()))) {
        break;
      }
      i = j;
      continue;
    }
    if (items.length > 0 && isBoundary(t)) break;
    if (BULLET_RE.test(t)) {
      items.push(t.replace(BULLET_RE, ""));
      i++;
    } else if (items.length > 0) {
      items[items.length - 1] += " " + t;
      i++;
    } else {
      return null;
    }
  }
  return items.length > 0 ? { items, endIdx: i } : null;
}

/** Find and remove the last list block whose header matches `headerRe`, if any. */
function extractTrailingBlock(
  lines: string[],
  headerRe: RegExp,
): { lines: string[]; items: string[] | null; heading?: string } {
  let idx = -1;
  for (let i = lines.length - 1; i >= 0; i--) {
    if (headerRe.test(lines[i].trim())) {
      idx = i;
      break;
    }
  }
  if (idx === -1) return { lines, items: null };
  const block = consumeListBlock(lines, idx + 1);
  if (!block) return { lines, items: null };
  return {
    lines: lines.slice(0, idx).concat(lines.slice(block.endIdx)),
    items: block.items,
    heading: lines[idx].trim().replace(/\*/g, ""),
  };
}

interface ParsedSource {
  url?: string;
  label: string;
}

interface ParsedContent {
  body: string;
  sources: ParsedSource[];
  suggestions: string[];
}

/**
 * Split trailing "Fontes consultadas" and "Follow-ups"/"Próximos passos"
 * blocks off the message body. Whichever section sits later in the text is
 * extracted first so its boundary can't swallow the earlier section.
 */
function parseMessage(content: string): ParsedContent {
  let lines = content.split("\n");
  let sourcesIdx = -1;
  let suggestionsIdx = -1;
  for (let i = lines.length - 1; i >= 0; i--) {
    if (sourcesIdx === -1 && SOURCES_HEADER_RE.test(lines[i].trim())) sourcesIdx = i;
    if (suggestionsIdx === -1 && SUGGESTIONS_HEADER_RE.test(lines[i].trim())) {
      suggestionsIdx = i;
    }
  }

  let sourceItems: string[] | null = null;
  let suggestionItems: string[] | null = null;
  const order =
    suggestionsIdx > sourcesIdx
      ? ([SUGGESTIONS_HEADER_RE, SOURCES_HEADER_RE] as const)
      : ([SOURCES_HEADER_RE, SUGGESTIONS_HEADER_RE] as const);
  for (const headerRe of order) {
    const result = extractTrailingBlock(lines, headerRe);
    lines = result.lines;
    if (headerRe === SOURCES_HEADER_RE) sourceItems = result.items;
    else suggestionItems = result.items;
  }

  const sources: ParsedSource[] = [];
  for (const item of sourceItems ?? []) {
    const urls = (item.match(URL_RE) ?? []).map(cleanUrl);
    const label = item
      .split(/https?:\/\//)[0]
      .replace(/[\s:;,\-–—(]+$/, "")
      .trim();
    if (urls.length === 0) {
      sources.push({ label: item });
    } else {
      urls.forEach((url, i) =>
        sources.push({ url, label: i === 0 ? label : domainOf(url) }),
      );
    }
  }

  return {
    body: lines.join("\n").trimEnd(),
    sources,
    suggestions: suggestionItems ?? [],
  };
}

/** Render text with bare URLs as clickable links. */
function Linkified({ text }: { text: string }) {
  const parts = text.split(URL_RE);
  const urls = text.match(URL_RE) ?? [];
  return (
    <>
      {parts.map((part, i) => (
        <span key={i}>
          {part}
          {i < urls.length && (
            <a
              href={cleanUrl(urls[i])}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all text-clay underline decoration-clay/40 underline-offset-2 hover:decoration-clay"
            >
              {cleanUrl(urls[i])}
            </a>
          )}
        </span>
      ))}
    </>
  );
}

function SourceChip({ source }: { source: ParsedSource }) {
  const [iconFailed, setIconFailed] = useState(false);
  const domain = source.url ? domainOf(source.url) : null;
  const text = source.label || domain || "";

  const inner = (
    <>
      {domain && !iconFailed ? (
        <img
          src={`https://www.google.com/s2/favicons?domain=${domain}&sz=32`}
          alt=""
          className="h-3.5 w-3.5 shrink-0 rounded-sm"
          onError={() => setIconFailed(true)}
        />
      ) : (
        <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm bg-hover text-[9px] uppercase text-faint">
          {(domain ?? text).charAt(0)}
        </span>
      )}
      <span className="truncate">{text}</span>
      {domain && source.label && (
        <span className="shrink-0 text-faint">{domain}</span>
      )}
    </>
  );

  const className =
    "flex max-w-[260px] items-center gap-1.5 rounded-full border border-line bg-surface px-2.5 py-1 text-[12px] text-mut";

  if (!source.url) {
    return (
      <span className={className} title={source.label}>
        {inner}
      </span>
    );
  }
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className={`${className} transition-colors hover:border-faint hover:bg-hover hover:text-fg`}
      title={`${source.label} — ${source.url}`}
    >
      {inner}
    </a>
  );
}

/** Assistant message body: linkified prose, source chips, and follow-up suggestion buttons. */
export default function MessageBody({
  content,
  caret = false,
  onSuggestionClick,
  disabled = false,
}: {
  content: string;
  caret?: boolean;
  /** When provided, suggestion buttons are clickable and send the picked text as a new message. */
  onSuggestionClick?: (text: string) => void;
  disabled?: boolean;
}) {
  const { body, sources, suggestions } = parseMessage(content);
  return (
    <>
      <div
        className={`whitespace-pre-wrap text-[15px] leading-7 text-fg${caret ? " caret" : ""}`}
      >
        <Linkified text={body} />
      </div>
      {sources.length > 0 && (
        <div className="mt-3">
          <div className="mb-1.5 font-monoui text-[11px] uppercase tracking-wider text-faint">
            Fontes · {sources.length}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {sources.map((source, i) => (
              <SourceChip key={i} source={source} />
            ))}
          </div>
        </div>
      )}
      {suggestions.length > 0 && (
        <div className="mt-3">
          <div className="mb-1.5 font-monoui text-[11px] uppercase tracking-wider text-faint">
            Perguntas relacionadas
          </div>
          <div className="flex flex-wrap gap-2">
            {suggestions.map((suggestion, i) => (
              <button
                key={i}
                type="button"
                disabled={!onSuggestionClick || disabled}
                onClick={() => onSuggestionClick?.(suggestion)}
                className="rounded-full border border-line px-3.5 py-1.5 text-left text-[13px] text-mut transition-colors hover:border-faint hover:text-fg disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-line disabled:hover:text-mut"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
