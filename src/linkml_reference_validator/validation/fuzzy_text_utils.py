"""Efficient fuzzy text matching utilities for large documents.

This module provides optimized fuzzy text matching using RapidFuzz,
designed for finding approximate matches of supporting text within
large publication documents (10K-100K+ words).

Key features:
- Fast partial matching using RapidFuzz (40% faster than difflib)
- Returns both similarity scores and match locations
- Handles large documents efficiently with smart optimizations
- Falls back gracefully when matches aren't found
- Word overlap validation to prevent false positives

NOTE: These utilities are used ONLY for generating suggestions,
NOT for validation. Validation uses strict substring matching.
"""

import re
from typing import Optional

from rapidfuzz import fuzz

# Common English stopwords to exclude from word overlap checks
STOPWORDS = frozenset([
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "dare",
    "and", "or", "but", "if", "then", "else", "when", "where", "why",
    "how", "what", "which", "who", "whom", "this", "that", "these",
    "those", "am", "to", "of", "in", "for", "on", "with", "at", "by",
    "from", "as", "into", "through", "during", "before", "after",
    "above", "below", "between", "under", "again", "further", "once",
    "here", "there", "all", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "also", "now", "its", "it",
])


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace and lowercase for matching.

    Args:
        text: Text to normalize

    Returns:
        Normalized text with whitespace collapsed and lowercased

    Examples:
        >>> normalize_whitespace("Text  with\\nmultiple   spaces")
        'text with multiple spaces'
        >>> normalize_whitespace("  Leading and trailing  ")
        'leading and trailing'
    """
    return re.sub(r'\s+', ' ', text).strip().lower()


def get_significant_words(text: str) -> set[str]:
    """Extract significant words (excluding stopwords) from text.

    Args:
        text: Text to extract words from

    Returns:
        Set of significant words (lowercase, no stopwords)

    Examples:
        >>> words = get_significant_words("The JAK1 protein is a tyrosine kinase")
        >>> "jak1" in words
        True
        >>> "protein" in words
        True
        >>> "the" in words
        False
        >>> "is" in words
        False
    """
    # Normalize and split into words
    normalized = normalize_whitespace(text)
    # Remove punctuation and split
    words = re.findall(r'\b[a-z0-9]+\b', normalized)
    # Filter out stopwords and very short words
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def calculate_word_overlap(text1: str, text2: str) -> float:
    """Calculate the percentage of significant words from text1 that appear in text2.

    This helps prevent false positive matches where fuzzy string matching
    gives high scores but the texts share few actual content words.

    Args:
        text1: Query text (typically shorter)
        text2: Target text to search within

    Returns:
        Percentage (0-100) of text1's significant words found in text2

    Examples:
        >>> calculate_word_overlap(
        ...     "JAK1 protein is a tyrosine kinase",
        ...     "The JAK1 protein is a tyrosine kinase that activates STAT"
        ... )
        100.0
        >>> overlap = calculate_word_overlap(
        ...     "elevated serum creatinine and albuminuria",
        ...     "Nephronophthisis is an autosomal recessive cystic kidney disease"
        ... )
        >>> overlap < 20  # Very little overlap
        True
    """
    words1 = get_significant_words(text1)
    words2 = get_significant_words(text2)

    if not words1:
        return 0.0

    overlap = words1 & words2
    return (len(overlap) / len(words1)) * 100


def split_into_sentences(text: str, min_length: int = 20) -> list[str]:
    """Split text into sentences for matching.

    Args:
        text: Text to split
        min_length: Minimum sentence length to include

    Returns:
        List of sentences longer than min_length

    Examples:
        >>> sentences = split_into_sentences("This is the first longer sentence. This is the second longer sentence!")
        >>> len(sentences)
        2
        >>> sentences = split_into_sentences("Short. This is a sentence that is longer than twenty characters.")
        >>> len(sentences)
        1
    """
    # Normalize newlines to spaces but preserve paragraph breaks
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"\s+", " ", text)

    # Split on sentence-ending punctuation
    sentences = re.split(r"[.!?]\s+", text)

    # Filter and clean
    return [s.strip() for s in sentences if s.strip() and len(s.strip()) >= min_length]


def find_fuzzy_match_in_text(
    query: str,
    text: str,
    threshold: float = 85.0,
    max_chars: int = 500_000,
    min_word_overlap: float = 50.0,
) -> tuple[bool, float, Optional[str]]:
    """Find fuzzy match of query text in a large document using RapidFuzz.

    This function uses a multi-stage approach for efficiency:
    1. Try exact substring match (fastest)
    2. Try sentence-by-sentence partial matching (fast for most cases)
    3. For very small queries (<5 words), fail fast
    4. Validate word overlap to prevent false positives

    The word overlap check ensures that matches share actual content words,
    not just common short sequences like "is a" or "the".

    Args:
        query: Text to search for (supporting_text from annotation)
        text: Large document to search within (publication content)
        threshold: Minimum similarity score (0-100) to consider a match
        max_chars: Maximum text size to process (safety limit)
        min_word_overlap: Minimum percentage of query's significant words
            that must appear in the match (default 50%)

    Returns:
        Tuple of (found, similarity_score, best_match_text) where:
        - found: True if similarity >= threshold AND word overlap >= min_word_overlap
        - similarity_score: Float 0-100 indicating match quality
        - best_match_text: The best matching text segment or None

    Examples:
        >>> text = "The JAK1 protein is a tyrosine kinase. It phosphorylates STAT proteins."
        >>> found, score, match = find_fuzzy_match_in_text(
        ...     "JAK1 protein is a tyrosine kinase",
        ...     text
        ... )
        >>> found
        True
        >>> score >= 90
        True

        >>> # Test with minor variation - this won't match due to <5 word threshold
        >>> found, score, match = find_fuzzy_match_in_text(
        ...     "JAK1 is tyrosine kinase",
        ...     text
        ... )
        >>> found  # Only 4 words, requires exact match
        False

        >>> # Test with non-matching text
        >>> found, score, match = find_fuzzy_match_in_text(
        ...     "completely different text here",
        ...     text
        ... )
        >>> found
        False

        >>> # Test false positive prevention - unrelated texts should not match
        >>> found, score, match = find_fuzzy_match_in_text(
        ...     "elevated serum creatinine and albuminuria are diagnostic",
        ...     "Nephronophthisis is an autosomal recessive cystic kidney disease"
        ... )
        >>> found  # Should NOT match due to low word overlap
        False
    """
    # Safety check: skip if text is too large
    if len(text) > max_chars:
        return (False, 0.0, None)

    # Normalize both texts
    query_norm = normalize_whitespace(query)
    text_norm = normalize_whitespace(text)

    # Stage 1: Try exact substring match (fastest - O(n))
    if query_norm in text_norm:
        return (True, 100.0, query)

    # Stage 2: Quick check - if query is very short, require exact match
    query_words = query_norm.split()
    if len(query_words) < 5:
        return (False, 0.0, None)

    # Stage 3: Sentence-by-sentence matching using RapidFuzz
    # This is much faster than sliding window for large documents
    sentences = split_into_sentences(text)

    best_score = 0.0
    best_match = None
    best_word_overlap = 0.0

    for sentence in sentences:
        sentence_norm = normalize_whitespace(sentence)
        # Use partial_ratio which finds best matching substring
        # This is optimized in RapidFuzz and much faster than sliding window
        score = fuzz.partial_ratio(query_norm, sentence_norm)

        # Calculate word overlap to prevent false positives
        word_overlap = calculate_word_overlap(query, sentence)

        # Use combined score: fuzzy score weighted by word overlap
        # This penalizes matches that don't share content words
        if word_overlap >= min_word_overlap:
            effective_score = score
        else:
            # Penalize score based on how far below the overlap threshold we are
            overlap_penalty = word_overlap / min_word_overlap
            effective_score = score * overlap_penalty

        if effective_score > best_score:
            best_score = effective_score
            best_match = sentence
            best_word_overlap = word_overlap

        # Early exit if we find an excellent match with good word overlap
        if score >= 95 and word_overlap >= min_word_overlap:
            return (True, score, sentence)

    # Return result based on threshold AND word overlap
    # A match requires both high fuzzy score AND sufficient word overlap
    is_match = best_score >= threshold and best_word_overlap >= min_word_overlap
    return (is_match, best_score, best_match if best_match else None)


def calculate_text_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two text strings using RapidFuzz.

    Uses token_sort_ratio which handles word order differences well.

    Args:
        text1: First text
        text2: Second text

    Returns:
        Similarity score from 0-100

    Examples:
        >>> calculate_text_similarity("the cat sat", "sat the cat")
        100.0
        >>> score = calculate_text_similarity("hello world", "goodbye world")
        >>> 30 < score < 70
        True
    """
    text1_norm = normalize_whitespace(text1)
    text2_norm = normalize_whitespace(text2)

    # token_sort_ratio handles word reordering
    return fuzz.token_sort_ratio(text1_norm, text2_norm)
