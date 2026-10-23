"""Publisher and site rules, kept in one place.

These are the rules that change when a publisher changes its pages: where a
PDF's landing page lives, which containers hold an article body, how PMC words
a placeholder notice, what an authoring tool stamps in place of a PDF title.
Each rule sits beside its examples, which are what it must match, and its
counterexamples, which are what it must not. The tests read both from here and
from nowhere else, so updating a rule is one edit in one file.

To add a rule, add it and at least one example. ``tests/test_rules.py`` fails
for a rule that has no example, and checks every example and counterexample
against the code that uses the rule.

Generic format rules (which HTML elements are never content, which attributes
survive sanitizing) are not publisher rules and stay with their extractors.

Examples:
    >>> sorted(LANDING_PAGE_RULES)
    ['J-STAGE']
    >>> PMC_ARTICLE_BODY_CLASSES[0]
    'main-article-body'
    >>> bool(BOT_CHALLENGE_TITLE.match("Checking your browser - reCAPTCHA"))
    True
"""

import html
import re
from typing import Optional

# --- PDF landing pages -----------------------------------------------------

#: Publishers that serve a PDF at one URL and its metadata page at a
#: predictable sibling, as ``name -> (pattern, replacement)`` for ``re.sub``
#: on the PDF URL. The landing page is consulted only for its
#: ``citation_title`` meta tag.
LANDING_PAGE_RULES: dict[str, tuple[str, str]] = {
    # .../<article>/_pdf[/-char/ja] -> .../<article>/_article[/-char/ja]
    "J-STAGE": (
        r"^(https?://www\.jstage\.jst\.go\.jp/article/.+)/_pdf(/.*)?$",
        r"\1/_article\2",
    ),
}

#: ``name -> ((pdf_url, landing_url), ...)``.
LANDING_PAGE_EXAMPLES: dict[str, tuple[tuple[str, str], ...]] = {
    "J-STAGE": (
        (
            "https://www.jstage.jst.go.jp/article/jvms/64/1/64_1_1/_pdf/-char/ja",
            "https://www.jstage.jst.go.jp/article/jvms/64/1/64_1_1/_article/-char/ja",
        ),
        (
            "https://www.jstage.jst.go.jp/article/jvms/64/1/64_1_1/_pdf",
            "https://www.jstage.jst.go.jp/article/jvms/64/1/64_1_1/_article",
        ),
    ),
}

#: PDF URLs no rule may map to a landing page.
LANDING_PAGE_COUNTEREXAMPLES: tuple[str, ...] = (
    "https://example.org/files/paper.pdf",
    # Another host must never be rewritten, even with J-STAGE's path shape.
    "https://evil.example.org/article/jvms/64/1/64_1_1/_pdf",
)

# --- Placeholder PDF titles ------------------------------------------------

#: What authoring tools stamp into a PDF's ``/Title`` in place of a real one.
#: A filename counts only when bare (no spaces), so a real title ending in
#: ".pdf" is kept.
PDF_PLACEHOLDER_TITLE = re.compile(
    r"^(untitled(\s+document)?"
    r"|microsoft (word|powerpoint) - .*"
    r"|\S+\.(pdf|docx?|rtf|odt|tex|indd))$",
    re.IGNORECASE,
)

#: Titles that are placeholders and must be rejected.
PDF_PLACEHOLDER_TITLE_EXAMPLES: tuple[str, ...] = (
    "untitled",
    "Untitled",
    "Untitled Document",
    "Microsoft Word - draft_v3.doc",
    "Microsoft Word - 64_1_1.doc",
    "paper.pdf",
    "manuscript.docx",
)

#: Real titles that must be kept, including ones that look like placeholders.
PDF_PLACEHOLDER_TITLE_COUNTEREXAMPLES: tuple[str, ...] = (
    "Canine Distemper in Dogs",
    "Converting LaTeX Manuscripts to report.pdf",
    "Why we stopped using .docx",
)

# --- Bot-challenge interstitials -------------------------------------------

#: ``<title>`` of the page a host serves in place of the document when it
#: challenges a client it takes for a bot. NCBI serves "Checking your browser -
#: reCAPTCHA" for Bookshelf and PMC pages on an HTTP 200, so no status check
#: sees it, and ``url:`` used to cache it as the reference (#117). Only whole
#: titles match: a paper may well be called "Access denied: ...", and one
#: about reCAPTCHA is still a paper.
BOT_CHALLENGE_TITLE = re.compile(
    r"^(checking your browser( before accessing\b.*)?(\s*[-|]\s*recaptcha)?"
    r"|just a moment(\.{3}|\u2026)?(\s*\|\s*cloudflare)?"
    r"|attention required(!(\s*\|\s*cloudflare)?|\s*\|\s*cloudflare)"
    r"|access denied)$",
    re.IGNORECASE,
)


def is_bot_challenge_title(title: Optional[str]) -> bool:
    """Report whether a title is a bot-challenge page's, per ``BOT_CHALLENGE_TITLE``.

    Entities are decoded and whitespace collapsed first, so ``&nbsp;`` and line
    breaks inside a ``<title>`` do not hide a match.

    Examples:
        >>> is_bot_challenge_title("Checking your browser - reCAPTCHA")
        True
        >>> is_bot_challenge_title("  Just a moment...  ")
        True
        >>> is_bot_challenge_title("MELAS - GeneReviews - NCBI Bookshelf")
        False
        >>> is_bot_challenge_title(None)
        False
    """
    if not title:
        return False
    return BOT_CHALLENGE_TITLE.match(" ".join(html.unescape(title).split())) is not None


#: Titles that are challenge pages and must be declined.
BOT_CHALLENGE_TITLE_EXAMPLES: tuple[str, ...] = (
    "Checking your browser - reCAPTCHA",  # NCBI Bookshelf and PMC
    "checking your browser",
    "Checking your browser before accessing pmc.ncbi.nlm.nih.gov",
    "Just a moment...",  # Cloudflare
    "Just a moment\u2026",
    "Just a moment... | Cloudflare",
    "Attention Required! | Cloudflare",
    "Attention Required!",
    "Access Denied",  # Akamai
)

#: Real titles that must be kept, including ones that share the words.
BOT_CHALLENGE_TITLE_COUNTEREXAMPLES: tuple[str, ...] = (
    "MELAS - GeneReviews\u00ae - NCBI Bookshelf",
    "Access denied: barriers to specialist care in rural areas",
    "Usability of reCAPTCHA for older adults",
    "Just a moment of inattention: driver distraction and crash risk",
    "Checking your browser history for signs of compromise",
    "Attention required: a review of sustained attention in ADHD",
)

# --- Article body containers in HTML full text -----------------------------

#: CSS selectors for explicit article-body containers. Generic layout IDs such
#: as ``#body`` are not evidence that a page contains an article.
ARTICLE_BODY_SELECTORS: tuple[str, ...] = (
    '[itemprop="articleBody"]',
    ".article-text",
    "#artText",
    ".article-body",
    ".article__body",
    ".c-article-body",
)

#: ``selector -> markup it must find``.
ARTICLE_BODY_EXAMPLES: dict[str, str] = {
    '[itemprop="articleBody"]': '<div itemprop="articleBody">{body}</div>',
    ".article-text": '<div class="article-text">{body}</div>',
    "#artText": '<div id="artText">{body}</div>',
    ".article-body": '<div class="article-body">{body}</div>',
    ".article__body": '<div class="article__body">{body}</div>',
    ".c-article-body": '<div class="c-article-body">{body}</div>',
}

#: Markup no selector may take for an article body.
ARTICLE_BODY_COUNTEREXAMPLES: tuple[str, ...] = (
    '<div id="body">{body}</div>',
    '<div class="page-body">{body}</div>',
)

# --- PMC article containers ------------------------------------------------

#: Classes of PMC's article-body element. PMC moved its article from
#: ``div.article-body``/``div.tsec`` to ``section.main-article-body``, and the
#: fallback declined every article until this list caught up
#: (monarch-initiative/dismech#12672). Deliberately not ``body``, which PMC
#: pairs with ``main-article-body`` on the same element. Matching it alone
#: would match every page's ``<body>``, and the structural test is the only
#: thing standing between this fetch and caching a bot-check interstitial
#: served on an HTTP 200.
#:
#: Order is a priority order, not an alphabetical one: the first match wins,
#: so the current wrapper is tried before the legacy ones. It matters for a
#: legacy page carrying several ``tsec`` sections, where only the first is
#: returned. The previous code behaved the same way, so this is a known limit
#: rather than a regression, but reordering the tuple would change which
#: section that is.
PMC_ARTICLE_BODY_CLASSES: tuple[str, ...] = ("main-article-body", "article-body", "tsec")

#: ``class -> markup it must find``. ``{body}`` stands for real article prose.
PMC_ARTICLE_BODY_EXAMPLES: dict[str, tuple[str, ...]] = {
    "main-article-body": (
        '<section class="body main-article-body">{body}</section>',  # current PMC
        '<section class="main-article-body">{body}</section>',  # without "body"
    ),
    "article-body": ('<div class="article-body">{body}</div>',),  # legacy
    "tsec": ('<div class="tsec">{body}</div>',),  # legacy
}

#: Pages that carry no article and must be declined.
PMC_ARTICLE_BODY_COUNTEREXAMPLES: tuple[str, ...] = (
    "<html><body><p>Checking your browser before accessing.</p></body></html>",
    "<html><body><nav><a href='/'>Home</a></nav></body></html>",
    "<html><body><div class='usa-banner'>An official website</div></body></html>",
    # <body> is on every page, so class="body" alone must not count.
    "<html><body>{body}</body></html>",
    # PMC's challenge page carries a classed <body>. None of its classes may
    # overlap the list, or a bot-check page is cached as full text.
    '<html><body class="usa-page bot-check">'
    "<h1>Checking your browser before accessing</h1>"
    "<p>Enable JavaScript and cookies to continue.</p>"
    "</body></html>",
)

# --- PMC placeholder notices -----------------------------------------------

#: Phrases appearing in the placeholder documents PMC serves in place of an
#: article whose full text it cannot supply. Deliberately broad, because the
#: length gate in :mod:`linkml_reference_validator.etl.extract.xml`
#: (``MAX_STUB_NOTICE_CHARS``), not the wording, is what keeps matching safe.
#: PMC phrases these notices several ways ("access to this article is
#: restricted", "full text is restricted", ...), and an exhaustive list would
#: trade the old false positives for false negatives.
STUB_NOTICE_PHRASES: tuple[str, ...] = (
    "restricted",
    "does not allow downloading",
    "cannot be obtained",
    "not available from pmc",
)

#: ``phrase -> notices it must catch``.
STUB_NOTICE_EXAMPLES: dict[str, tuple[str, ...]] = {
    "restricted": (
        "Access to the full text is restricted by the publisher.",
        # Wordings an exhaustive phrase list would miss; the length gate is
        # what lets a broad "restricted" catch them safely.
        "Access to this article is restricted.",
        "Full text is restricted.",
    ),
    "does not allow downloading": (
        "The publisher of this article does not allow downloading of the full "
        "text in XML form from PMC.",
    ),
    "cannot be obtained": ("The full text of this article cannot be obtained from PMC.",),
    "not available from pmc": ("This article is not available from PMC.",),
}
