"""Pure text matching helpers, independent of reference fetching and configuration."""

import re
from collections.abc import Sequence


def split_supporting_text(
    text: str,
    literal_bracket_patterns: Sequence[str | re.Pattern[str]] = (),
) -> list[str]:
    r"""Split supporting text into independently matched quote parts.

    Replace editorial square brackets with spaces, then split on runs of two
    or more ASCII periods. Collapse whitespace and discard empty parts. A
    single period and the Unicode ellipsis character are not separators.

    Args:
        text: Supporting text to split, without normalization of case or punctuation.
        literal_bracket_patterns: Regexes searched against the content inside
            brackets (excluding the brackets). Any match preserves the complete
            bracketed text. Defaults to no patterns, just like
            ``ReferenceValidationConfig.literal_bracket_patterns``: scientific
            notation is stripped unless explicitly matched. Pass that config
            field directly, or reuse compiled patterns for repeated calls.
            Compiled patterns retain their flags.

    Returns:
        Ordered, nonempty quote parts, or an empty list if no quoted text remains.

    Raises:
        re.error: A supplied regular expression is invalid.

    Bracket matching follows the validator's existing non-nested, single-line
    regex semantics: an opening bracket matches through the next closing
    bracket on the same line. Unmatched brackets remain literal. Separators
    inside preserved brackets still split parts.

    Examples:
        >>> split_supporting_text("protein functions ... in cells")
        ['protein functions', 'in cells']
        >>> split_supporting_text("protein [important] functions")
        ['protein functions']
        >>> split_supporting_text("[editorial note] ...")
        []
        >>> split_supporting_text("[2Fe-2S] [poly(A)+]")
        []
        >>> split_supporting_text("protein [important] binds [2Fe-2S] cluster", [r"\d"])
        ['protein binds [2Fe-2S] cluster']
        >>> split_supporting_text("export of [poly(A)+] RNA [important]", [r"[()+]"])
        ['export of [poly(A)+] RNA']
        >>> patterns = (re.compile(r"\d"), re.compile(r"[()+]"))
        >>> split_supporting_text("[2Fe-2S] ... [poly(A)+]", patterns)
        ['[2Fe-2S]', '[poly(A)+]']
        >>> split_supporting_text("  alpha\n beta .. gamma … delta. ")
        ['alpha beta', 'gamma … delta.']
    """
    regexes = [
        re.compile(pattern) if isinstance(pattern, str) else pattern
        for pattern in literal_bracket_patterns
    ]
    if not regexes:
        text_without_brackets = re.sub(r"\[.*?\]", " ", text)
    else:

        def replace_bracket(match: re.Match[str]) -> str:
            """Preserve configured literal bracket content, strip editorial notes."""
            content = match.group(1)
            if any(regex.search(content) for regex in regexes):
                return match.group(0)
            return " "

        text_without_brackets = re.sub(r"\[(.*?)\]", replace_bracket, text)

    parts = re.split(r"\s*\.{2,}\s*", text_without_brackets)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if p.strip()]
