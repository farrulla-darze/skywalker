"""Markdown-aware text chunker for knowledge base content."""

import re
from typing import List
from dataclasses import dataclass, field


@dataclass
class Chunk:
    """A single chunk of text from a markdown document."""

    text: str
    chunk_index: int
    source_file: str
    source_url: str
    start_char: int
    end_char: int
    header_context: str = ""
    metadata: dict = field(default_factory=dict)


class MarkdownChunker:
    """Splits markdown content into overlapping, header-aware chunks."""

    def __init__(
        self,
        chunk_size: int = 2048,
        chunk_overlap: int = 400,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_file(self, file_path: str, source_url: str, content: str) -> List[Chunk]:
        """Chunk a markdown file into overlapping segments.

        Args:
            file_path: Path to the source .md file.
            source_url: Original URL the content was scraped from.
            content: Raw markdown content.

        Returns:
            List of Chunk objects.
        """
        sections = self._split_by_headers(content)
        raw_chunks: List[dict] = []

        for section in sections:
            section_text = section["text"].strip()
            if not section_text:
                continue

            header_ctx = section["header_context"]

            if len(section_text) <= self.chunk_size:
                raw_chunks.append({"text": section_text, "header_context": header_ctx})
            else:
                for part in self._split_section(section_text):
                    raw_chunks.append({"text": part, "header_context": header_ctx})

        # Assemble final chunks with overlap
        chunks: List[Chunk] = []
        char_offset = 0

        for i, raw in enumerate(raw_chunks):
            text = raw["text"]

            # Add overlap from previous chunk
            if i > 0 and self.chunk_overlap > 0:
                prev_text = raw_chunks[i - 1]["text"]
                overlap = prev_text[-self.chunk_overlap :]
                text = overlap + "\n" + text

            chunks.append(
                Chunk(
                    text=text,
                    chunk_index=i,
                    source_file=file_path,
                    source_url=source_url,
                    start_char=char_offset,
                    end_char=char_offset + len(raw["text"]),
                    header_context=raw["header_context"],
                )
            )
            char_offset += len(raw["text"])

        return chunks

    def _split_by_headers(self, content: str) -> List[dict]:
        """Split markdown by header hierarchy, tracking header context."""
        header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        sections: List[dict] = []
        header_stack: List[str] = []
        last_end = 0

        for match in header_pattern.finditer(content):
            # Capture text before this header
            text_before = content[last_end : match.start()]
            if text_before.strip():
                ctx = " > ".join(header_stack) if header_stack else ""
                sections.append({"text": text_before, "header_context": ctx})

            # Update header stack
            level = len(match.group(1))
            title = match.group(2).strip()

            # Pop headers at same or deeper level
            header_stack = [h for i, h in enumerate(header_stack) if i < level - 1]
            header_stack.append(title)

            last_end = match.end()

        # Capture remaining text after last header
        remaining = content[last_end:]
        if remaining.strip():
            ctx = " > ".join(header_stack) if header_stack else ""
            sections.append({"text": remaining, "header_context": ctx})

        # If no headers found, return entire content as single section
        if not sections:
            sections.append({"text": content, "header_context": ""})

        return sections

    def _split_section(self, text: str) -> List[str]:
        """Split a section that exceeds chunk_size into smaller parts."""
        # First try splitting by paragraphs
        paragraphs = re.split(r"\n\n+", text)
        if len(paragraphs) > 1:
            return self._merge_parts(paragraphs)

        # Then by sentences
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) > 1:
            return self._merge_parts(sentences)

        # Last resort: split by character boundary at word breaks
        parts: List[str] = []
        while len(text) > self.chunk_size:
            split_at = text.rfind(" ", 0, self.chunk_size)
            if split_at == -1:
                split_at = self.chunk_size
            parts.append(text[:split_at])
            text = text[split_at:].lstrip()
        if text:
            parts.append(text)
        return parts

    def _merge_parts(self, parts: List[str]) -> List[str]:
        """Merge small parts together until they approach chunk_size."""
        merged: List[str] = []
        current = ""

        for part in parts:
            candidate = (current + "\n\n" + part).strip() if current else part
            if len(candidate) <= self.chunk_size:
                current = candidate
            else:
                if current:
                    merged.append(current)
                # If single part exceeds chunk_size, recursively split
                if len(part) > self.chunk_size:
                    merged.extend(self._split_section(part))
                    current = ""
                else:
                    current = part

        if current:
            merged.append(current)

        return merged
