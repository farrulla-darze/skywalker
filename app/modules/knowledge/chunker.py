"""Markdown-aware chunker.

Fixes over the v1 implementation:
- ``header_context`` is *prepended to the embedded text* (it used to be
  metadata-only, which threw away the strongest retrieval signal).
- Overlap never crosses section boundaries (it used to bleed content from an
  unrelated header into the next chunk).
"""

import re
from dataclasses import dataclass, field


@dataclass
class Chunk:
    """A single chunk of text ready for embedding."""

    text: str  # header context + body — this is what gets embedded
    body: str  # body without the header prefix (for display)
    chunk_index: int
    source_url: str
    header_context: str = ""
    metadata: dict = field(default_factory=dict)


class MarkdownChunker:
    """Splits markdown content into header-aware chunks with intra-section overlap."""

    def __init__(self, chunk_size: int = 1024, chunk_overlap: int = 150) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, content: str, source_url: str) -> list[Chunk]:
        sections = self._split_by_headers(content)
        chunks: list[Chunk] = []
        index = 0

        for section in sections:
            section_text = section["text"].strip()
            if not section_text:
                continue
            header_ctx = section["header_context"]

            parts = (
                [section_text]
                if len(section_text) <= self.chunk_size
                else self._split_section(section_text)
            )

            # Overlap only within the same section
            for i, part in enumerate(parts):
                body = part
                if i > 0 and self.chunk_overlap > 0:
                    overlap = parts[i - 1][-self.chunk_overlap :]
                    body = overlap + "\n" + part

                text = f"{header_ctx}\n\n{body}" if header_ctx else body
                chunks.append(
                    Chunk(
                        text=text,
                        body=body,
                        chunk_index=index,
                        source_url=source_url,
                        header_context=header_ctx,
                    )
                )
                index += 1

        return chunks

    def _split_by_headers(self, content: str) -> list[dict]:
        """Split markdown by header hierarchy, tracking full header context."""
        header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        sections: list[dict] = []
        header_stack: list[tuple[int, str]] = []  # (level, title)
        last_end = 0

        for match in header_pattern.finditer(content):
            text_before = content[last_end : match.start()]
            if text_before.strip():
                ctx = " > ".join(title for _, title in header_stack)
                sections.append({"text": text_before, "header_context": ctx})

            level = len(match.group(1))
            title = match.group(2).strip()
            # Pop headers at same or deeper level, then push
            header_stack = [(lv, t) for lv, t in header_stack if lv < level]
            header_stack.append((level, title))
            last_end = match.end()

        remaining = content[last_end:]
        if remaining.strip():
            ctx = " > ".join(title for _, title in header_stack)
            sections.append({"text": remaining, "header_context": ctx})

        if not sections:
            sections.append({"text": content, "header_context": ""})
        return sections

    def _split_section(self, text: str) -> list[str]:
        """Split an oversized section by paragraphs, then sentences, then words."""
        paragraphs = re.split(r"\n\n+", text)
        if len(paragraphs) > 1:
            return self._merge_parts(paragraphs)

        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) > 1:
            return self._merge_parts(sentences)

        parts: list[str] = []
        while len(text) > self.chunk_size:
            split_at = text.rfind(" ", 0, self.chunk_size)
            if split_at <= 0:
                split_at = self.chunk_size
            parts.append(text[:split_at])
            text = text[split_at:].lstrip()
        if text:
            parts.append(text)
        return parts

    def _merge_parts(self, parts: list[str]) -> list[str]:
        merged: list[str] = []
        current = ""
        for part in parts:
            candidate = f"{current}\n\n{part}".strip() if current else part
            if len(candidate) <= self.chunk_size:
                current = candidate
            else:
                if current:
                    merged.append(current)
                if len(part) > self.chunk_size:
                    merged.extend(self._split_section(part))
                    current = ""
                else:
                    current = part
        if current:
            merged.append(current)
        return merged
