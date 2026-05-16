"""Tests for tools/text_chunker.py — pure text chunking logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from tools.text_chunker import (
    estimate_tokens,
    split_frontmatter,
    chunk_text,
    Chunk,
    DEFAULT_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    MIN_CHUNK_SIZE,
)


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_single_word(self):
        assert estimate_tokens("hello") == 1

    def test_multiple_words(self):
        assert estimate_tokens("one two three four five") == 5

    def test_multiline(self):
        assert estimate_tokens("hello\nworld\ntest") == 3


class TestSplitFrontmatter:
    def test_no_frontmatter(self):
        fm, body = split_frontmatter("Just some text.")
        assert fm is None
        assert body == "Just some text."

    def test_empty_string(self):
        fm, body = split_frontmatter("")
        assert fm is None
        assert body == ""

    def test_with_frontmatter(self):
        text = "---\nname: test\nversion: 1.0\n---\n\n# Body here"
        fm, body = split_frontmatter(text)
        assert fm is not None
        assert "name: test" in fm
        assert "Body here" in body

    def test_frontmatter_without_closing(self):
        text = "---\nname: test\nNo closing delimiter"
        fm, body = split_frontmatter(text)
        assert fm is None
        assert "name: test" in body

    def test_none_input(self):
        fm, body = split_frontmatter(None)
        assert fm is None
        assert body == ""


class TestChunkText:
    def test_empty_text(self):
        assert chunk_text("") == []

    def test_whitespace_only(self):
        assert chunk_text("   \n\n  ") == []

    def test_short_text_single_chunk(self):
        chunks = chunk_text("This is a short text.")
        assert len(chunks) == 1
        assert chunks[0].content == "This is a short text."
        assert chunks[0].index == 0
        assert chunks[0].is_frontmatter is False

    def test_frontmatter_separate(self):
        text = "---\nname: skill\n---\n\nBody content here."
        chunks = chunk_text(text, separate_frontmatter=True)
        assert len(chunks) >= 2
        assert chunks[0].is_frontmatter is True
        assert "name: skill" in chunks[0].content
        assert chunks[1].is_frontmatter is False

    def test_frontmatter_not_separated(self):
        text = "---\nname: skill\n---\n\nBody content."
        chunks = chunk_text(text, separate_frontmatter=False)
        assert all(not c.is_frontmatter for c in chunks)

    def test_long_text_splits(self):
        sentences = "This is a sentence. " * 200
        chunks = chunk_text(sentences, chunk_size=100)
        assert len(chunks) > 1
        total_tokens = sum(c.token_count for c in chunks)
        assert total_tokens >= 800

    def test_chunk_indices_sequential(self):
        words = " ".join(["word"] * 800)
        chunks = chunk_text(words, chunk_size=100)
        for i, chunk in enumerate(chunks):
            assert chunk.index == i

    def test_chunk_size_respected(self):
        words = "Sentence one. " * 200
        chunks = chunk_text(words, chunk_size=50)
        for c in chunks:
            assert c.token_count <= MAX_CHUNK_SIZE

    def test_overlap_produces_more_chunks(self):
        words = " ".join(["word"] * 600)
        no_overlap = chunk_text(words, chunk_size=100, overlap=0)
        with_overlap = chunk_text(words, chunk_size=100, overlap=30)
        assert len(with_overlap) >= len(no_overlap)

    def test_paragraphs_split_at_boundaries(self):
        para = "Word " * 80
        text = f"{para}\n\n{para}\n\n{para}"
        chunks = chunk_text(text, chunk_size=100)
        assert len(chunks) >= 2


class TestChunkDataclass:
    def test_to_dict(self):
        c = Chunk(index=0, content="hello", token_count=1, is_frontmatter=False)
        d = c.to_dict()
        assert d["index"] == 0
        assert d["content"] == "hello"
        assert d["token_count"] == 1
        assert d["is_frontmatter"] is False

    def test_defaults(self):
        c = Chunk(index=1, content="x", token_count=1)
        assert c.is_frontmatter is False
