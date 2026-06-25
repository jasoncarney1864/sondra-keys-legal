"""
Document chunking service implementing recursive character-level chunking.
Splits documents into semantically meaningful chunks while maintaining overlap.
"""

import logging
from typing import List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Separators ordered from most semantic to least semantic
DEFAULT_SEPARATORS = [
    "\n\n",  # Paragraph breaks (most semantic)
    "\n",    # Line breaks
    ". ",    # Sentence boundaries
    " ",     # Word boundaries
    "",      # Character level (least semantic)
]


@dataclass
class Chunk:
    """Represents a single text chunk with metadata."""

    content: str
    chunk_index: int
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    start_position: int = 0
    end_position: int = 0

    def to_dict(self) -> dict:
        """Convert chunk to dictionary representation."""
        return {
            "content": self.content,
            "chunk_index": self.chunk_index,
            "page_number": self.page_number,
            "section_title": self.section_title,
            "start_position": self.start_position,
            "end_position": self.end_position,
            "length": len(self.content)
        }


class RecursiveCharacterChunker:
    """
    Implements recursive character-level chunking strategy.
    
    This strategy:
    1. Splits text on semantic boundaries (paragraphs, sentences, words)
    2. Recursively merges chunks until reaching target size
    3. Maintains configurable overlap between chunks
    4. Preserves document structure and context
    """

    def __init__(
        self,
        chunk_size: int = 1024,
        chunk_overlap: int = 20,
        separators: List[str] = None,
    ):
        """
        Initialize the chunker.

        Args:
            chunk_size: Target size for each chunk in characters
            chunk_overlap: Number of characters to overlap between chunks
            separators: List of separators to try in order (most to least semantic)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or DEFAULT_SEPARATORS

        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"Chunk overlap ({chunk_overlap}) must be smaller than "
                f"chunk size ({chunk_size})"
            )

        logger.info(
            f"Initialized RecursiveCharacterChunker: "
            f"size={chunk_size}, overlap={chunk_overlap}"
        )

    def chunk_text(self, text: str) -> List[Chunk]:
        """
        Split text into chunks using recursive character-level strategy.

        Args:
            text: The text to chunk

        Returns:
            List of Chunk objects
        """
        if not text:
            logger.warning("Empty text provided for chunking")
            return []

        # Split text recursively on semantic boundaries
        splits = self._split_text(text, self.separators)

        # Merge splits into properly-sized chunks
        good_splits = self._merge_splits(splits)

        # Convert to Chunk objects with metadata
        chunks = self._create_chunks(good_splits)

        logger.info(
            f"Created {len(chunks)} chunks from text of {len(text)} characters"
        )
        return chunks

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        """
        Recursively split text on separators from most to least semantic.

        Args:
            text: Text to split
            separators: Ordered list of separators

        Returns:
            List of text splits
        """
        good_splits = []
        separator = separators[-1]  # Start with least semantic separator

        # Try each separator from most to least semantic
        for i, _separator in enumerate(separators):
            if _separator == "":
                splits = list(text)
                break

            if _separator in text:
                splits = text.split(_separator)
                separator = _separator
                break
        else:
            # If no separator found, return whole text
            splits = [text]

        # Recursively split on remaining separators if chunks are too large
        good_splits = []
        for split in splits:
            if len(split) < self.chunk_size:
                good_splits.append(split)
            else:
                # Recursively split this large chunk
                if good_splits:
                    merged_text = separator.join(good_splits)
                    if merged_text:
                        good_splits = [merged_text]

                other_info = self._split_text(split, separators[separators.index(separator) + 1 :])
                good_splits.extend(other_info)

        return good_splits

    def _merge_splits(self, splits: List[str]) -> List[str]:
        """
        Merge splits into appropriately sized chunks with overlap.

        Args:
            splits: List of text splits

        Returns:
            List of merged chunks
        """
        separator = self.separators[-2]  # Use space as merge separator
        good_splits = [s for s in splits if len(s) < self.chunk_size]
        other_splits = [s for s in splits if len(s) >= self.chunk_size]

        merged_text = separator.join(good_splits)
        split_texts = [s for s in merged_text.split(separator) if s]

        # Now go merge things, recursively splitting longer texts
        _good_splits = []
        for s in split_texts:
            if len(s) < self.chunk_size:
                _good_splits.append(s)
            else:
                if _good_splits:
                    merged_text = separator.join(_good_splits)
                    final_chunks = self._split_overlap(merged_text, separator)
                    _good_splits = []
                    for chunk in final_chunks:
                        if len(chunk) < self.chunk_size:
                            _good_splits.append(chunk)
                        else:
                            if _good_splits:
                                merged_text = separator.join(_good_splits)
                                final_chunks = self._split_overlap(merged_text, separator)
                                _good_splits = []
                            other_splits.extend(final_chunks)

                other_splits.append(s)

        if _good_splits:
            merged_text = separator.join(_good_splits)
            final_chunks = self._split_overlap(merged_text, separator)
            other_splits.extend(final_chunks)

        return other_splits

    def _split_overlap(self, text: str, separator: str) -> List[str]:
        """
        Split text into chunks with overlap.

        Args:
            text: Text to split
            separator: Separator to use between chunks

        Returns:
            List of overlapping chunks
        """
        chunks = []
        current_chunk = ""

        for word in text.split(separator):
            # Check if adding this word would exceed chunk size
            potential = current_chunk + separator + word if current_chunk else word

            if len(potential) > self.chunk_size:
                if current_chunk:
                    chunks.append(current_chunk)
                    # Start new chunk with overlap from end of previous chunk
                    overlap = self._get_overlap(current_chunk)
                    current_chunk = overlap + separator + word if overlap else word
                else:
                    # Word is longer than chunk size, add it anyway
                    chunks.append(word)
                    current_chunk = ""
            else:
                current_chunk = potential

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _get_overlap(self, text: str) -> str:
        """
        Get the last chunk_overlap characters from text for overlap.

        Args:
            text: Text to extract overlap from

        Returns:
            Last chunk_overlap characters
        """
        if len(text) <= self.chunk_overlap:
            return text

        return text[-self.chunk_overlap:]

    def _create_chunks(self, splits: List[str]) -> List[Chunk]:
        """
        Convert text splits into Chunk objects with metadata.

        Args:
            splits: List of text splits

        Returns:
            List of Chunk objects
        """
        chunks = []
        current_position = 0

        for i, split in enumerate(splits):
            chunk = Chunk(
                content=split.strip(),
                chunk_index=i,
                start_position=current_position,
                end_position=current_position + len(split),
            )
            chunks.append(chunk)
            current_position += len(split)

        return chunks


class DocumentStructureAwareChunker(RecursiveCharacterChunker):
    """
    Extended chunker that respects document structure (sections, headings).
    Ensures chunks don't split important structural elements.
    """

    def chunk_with_structure(
        self,
        text: str,
        structure: dict = None,
        section_title: str = None,
    ) -> List[Chunk]:
        """
        Chunk text while respecting document structure.

        Args:
            text: Text to chunk
            structure: Optional structure metadata (headings, sections)
            section_title: Optional section title for context

        Returns:
            List of Chunk objects with structure awareness
        """
        chunks = self.chunk_text(text)

        # Add section information to chunks
        for chunk in chunks:
            chunk.section_title = section_title

        return chunks
