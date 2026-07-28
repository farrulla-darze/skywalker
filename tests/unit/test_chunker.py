"""Unit tests: markdown chunker — header context and overlap behavior."""

from app.modules.knowledge.chunker import MarkdownChunker

DOC = """# Maquininha Smart

Intro text about the product.

## Taxas

Débito: 1,49%. Crédito à vista: 3,15%.

## Recursos

Aceita Pix e cartões por aproximação.
"""


def test_header_context_is_prepended_to_embedded_text():
    chunks = MarkdownChunker(chunk_size=200, chunk_overlap=0).chunk(DOC, "https://x.io/m")
    fees = next(c for c in chunks if "1,49%" in c.body)
    assert "Maquininha Smart > Taxas" in fees.header_context
    # The fix: header context must be inside the text that gets embedded
    assert fees.text.startswith("Maquininha Smart > Taxas")


def test_overlap_does_not_cross_section_boundaries():
    long_section = "# A\n\n" + ("word " * 300) + "\n\n# B\n\nshort b content"
    chunks = MarkdownChunker(chunk_size=400, chunk_overlap=100).chunk(long_section, "u")
    b_chunks = [c for c in chunks if c.header_context == "B"]
    assert b_chunks, "expected a chunk under header B"
    # Section B's chunk must not contain overlap bleed from section A
    assert "word word" not in b_chunks[0].body


def test_oversized_section_is_split_with_overlap_within_section():
    text = "# H\n\n" + "\n\n".join(f"paragraph {i} " + "x" * 80 for i in range(10))
    chunks = MarkdownChunker(chunk_size=300, chunk_overlap=50).chunk(text, "u")
    h_chunks = [c for c in chunks if c.header_context == "H"]
    assert len(h_chunks) > 1
    # Second chunk starts with overlap from the first (same section)
    assert h_chunks[1].body[:20] in h_chunks[0].body + h_chunks[1].body


def test_no_headers_yields_single_context_free_chunks():
    chunks = MarkdownChunker(chunk_size=1000, chunk_overlap=0).chunk("just plain text", "u")
    assert len(chunks) == 1
    assert chunks[0].header_context == ""
    assert chunks[0].text == "just plain text"


def test_chunk_indexes_are_sequential():
    chunks = MarkdownChunker(chunk_size=120, chunk_overlap=10).chunk(DOC, "u")
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
