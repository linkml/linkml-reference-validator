# Using Local Files and URLs as References

In addition to PubMed IDs and DOIs, the validator supports local files and web URLs as reference sources. This is useful when your supporting text comes from internal documentation, research notes, or web pages.

## Local File References

Use the `file:` prefix to reference local files:

```bash
linkml-reference-validator validate text \
  "JAK1 binds to the receptor complex" \
  file:./research/jak-signaling-notes.md
```

### Supported File Types

- **Markdown** (`.md`) - Title extracted from first `# heading`
- **Plain text** (`.txt`) - Content used as-is
- **HTML** (`.html`) - Content preserved including HTML entities

### Path Resolution

**Absolute paths** always work:

```bash
file:/Users/me/research/notes.md
```

**Relative paths** are resolved in order:

1. If `reference_base_dir` is configured, paths resolve relative to it
2. Otherwise, paths resolve relative to the current working directory

Note: cached references use the resolved absolute path in the reference ID, so
the cache file name reflects the full path.

### Configuring a Base Directory

Set a base directory for all relative file references:

```python
from linkml_reference_validator.models import ReferenceValidationConfig
from pathlib import Path

config = ReferenceValidationConfig(
    reference_base_dir=Path("./references"),
)
```

Then `file:notes.md` resolves to `./references/notes.md`.

### Example: Validating Against Research Notes

Create a research file:

```markdown
# JAK-STAT Signaling Pathway

JAK1 binds to the receptor complex and initiates downstream signaling.
This leads to STAT phosphorylation and nuclear translocation.
```

Validate:

```bash
linkml-reference-validator validate text \
  "JAK1 binds to the receptor complex" \
  file:./jak-signaling.md
```

## URL References

Use the `url:` prefix to reference web pages (the prefix is optional for bare
HTTP/HTTPS URLs and will be normalized to `url:` internally):

```bash
linkml-reference-validator validate text \
  "Climate change affects biodiversity" \
  url:https://example.org/climate-report.html
```

### Caching

URLs are cached the same way as PMID and DOI references:

- First fetch downloads and caches the content
- Subsequent validations use the cached version
- Use `linkml-reference-validator cache reference url:https://... --force` to re-fetch

### Title Extraction

For HTML pages, the title is the `citation_title` meta tag when present, then the `<title>` tag. For PDFs, the validator tries a publisher landing page's `citation_title` and then the PDF's embedded title. When neither is found, and for other content types, the URL itself is used as the title. See [Validating URLs](validate-urls.md#titles).

### Example: Validating Against a Web Page

```bash
# First validation fetches and caches
linkml-reference-validator validate text \
  "The quick brown fox jumps over the lazy dog" \
  url:https://example.com/pangram-examples.html

# Subsequent validations use cache
linkml-reference-validator validate text \
  "A quick brown fox" \
  url:https://example.com/pangram-examples.html
```

## Diagrams as References (SVG)

A `file:` reference can point at an `.svg` figure, such as a pathway diagram.
The quote is then matched against the text the figure **renders**, not its
markup:

```bash
linkml-reference-validator validate text \
  "loss of PTEN activates AKT" \
  file:./figures/pathway.svg
```

- Each `<text>` element is one label. A label split over several `<tspan>`
  lines can be quoted across the break.
- A quote must fall within one label. A figure with a `PTEN` label and a
  separate `activates AKT` label does not support `"PTEN activates AKT"`,
  however close together they sit: neither label says it. To cite both, quote
  them as separate parts, `"PTEN ... activates AKT"`.
- HTML labels inside `<foreignObject>`, which is how drawio's **Export as SVG**
  writes them, are read too.
- Text the reader cannot see is never quotable. That covers `<desc>`, `<title>`,
  `<metadata>`, comments, attribute values (`id`, `fill`, `class`, ...),
  `<defs>`/`<symbol>` content that no `<use>` draws, and text hidden by
  `display:none`, `visibility:hidden`, zero `opacity`, `fill="none"` or a zero
  `font-size`, whether set on the element, inherited from a group, or set by a
  `<style>` rule.
- If the extractor cannot tell what the figure renders, the reference is
  `unavailable` rather than read as raw markup. That happens when a `<style>`
  rule hides or shows text through a selector other than a type, class or id
  selector (`g > text`, `:first-child`, `@media`), when visibility depends on
  `var()` or `calc()`, when a stylesheet is imported or linked, when the SVG
  contains a `<script>` or animates visibility, or when something changes the
  characters drawn: CSS `content`, a string `list-style-type` or `quotes`,
  `-webkit-text-security`, a `unicode-bidi` override, `<bdo>`, or a bidi
  control character in the text.

**Edges.** A connector between two labelled nodes also gives an edge line,
`"<source> <edge label> <target>"`, so a relational quote such as
`"PTEN inhibits AKT"` can be checked. The connector is an element (usually a
`<g>` holding the line and its label) whose `data-source` and `data-target`
attributes name the two nodes' ids:

```xml
<defs><marker id="arrow"><path d="M0 0 L10 5 L0 10 z"/></marker></defs>
<g id="pten"><rect x="0" y="0" width="60" height="30"/><text x="10" y="20">PTEN</text></g>
<g id="akt"><rect x="200" y="0" width="60" height="30"/><text x="210" y="20">AKT</text></g>
<g data-source="pten" data-target="akt">
  <path d="M60 15 L200 15" stroke="black" marker-end="url(#arrow)"/>
  <text x="110" y="10">inhibits</text>
</g>
```

The attributes are not drawn, so they are only believed when the drawing
agrees: the connector's stroked path must join the two nodes' shapes, one end
on each (transforms applied, with a little slack for an arrowhead), and the
connector, its label and both nodes and their labels must all be visible.

Arrowheads drawn as markers give the direction:

- **One arrowhead** (a `marker-start` or `marker-end`, set on the path or
  inherited) points at the node at that end, and the line reads from the other
  node to it. This holds even when it's the reverse of `data-source` →
  `data-target`: the drawing wins, as in drawio.
- **Arrowheads at both ends** make the line quotable both ways.
- **No arrowhead** (a plain line, or a marker that draws nothing) reads in the
  attributes' order, `data-source` first. This is a known limitation: nothing
  drawn gives that order, so swapping the two attributes reverses the line
  for the same picture.
- **An arrowhead drawn as a separate shape** gives no edge line: which way
  such a shape points can't be read, and the attributes' order could
  contradict it. This is any other `<polygon>`, `<polyline>`, `<path>` or
  `<line>` in the connector, wherever it sits; any `<use>` or `<image>`; and a
  `<rect>`, `<circle>` or `<ellipse>` at an end of the line or on a node. A
  `<rect>`, `<circle>` or `<ellipse>` in mid-line, such as a label's
  background, is not taken for an arrowhead.
- **Arrowheads at a bent line's inner vertices** (`marker-mid`, or the
  `marker` shorthand) give no edge line, since each may point either way.

A marker counts as an arrowhead when it names a `<marker>` in the figure that
draws something: a shape that paints, at a size above zero. When that can't be
told from the markup (a `var()` value, or a `<use>`, text or image inside the
marker), the connector gives no edge line, since neither direction is safe. The
marker's `orient` is not read: a marker drawn at a fixed angle is taken to
point along the path. A node is the shapes it draws inside the
element its id names; its text, and shapes that are hidden or paint nothing,
do not count towards its box. Geometry the extractor cannot place from
attributes gives no edge line either: CSS `transform` or other CSS geometry,
`clip-path`, `mask` or `filter`, or an animation that moves shapes. A node drawn only through `<use>`, inside a
nested `<svg>`, or sized in `%` or `em` gives no edge line.

Known limits: a label drawn as several `<text>` elements, one per line, is
read as several labels, so quote its lines with `...` between them. Text
clipped by `clip-path` or `mask`, placed outside the
`viewBox`, scaled to nothing, covered by another shape, drawn in the
background colour, or cut short by CSS `text-overflow` or `-webkit-line-clamp`
is still read. Text converted to outlines is not text and
cannot be quoted.

## Diagrams as References (drawio)

A `file:` reference can also point at a native drawio diagram, `.drawio` or
`.drawio.xml`, compressed or not. It is read the same way as an SVG: one label
per drawn cell, quotes held to one label, and an edge line
`"<source> <edge label> <target>"` for each drawn edge between two labelled
cells. In drawio an edge's source and target are what it is drawn between, so
no geometry check is needed; its line and both cells' labels must still be
visible. The arrows give the direction, as for SVG: an edge drawn pointing
back at its source reads target first, one with arrows at both ends reads both
ways, and one with no arrow reads source first. Only markers that point count
as arrows: arrowheads (`classic`, `block`, `open`, `async` and their thin or
double forms) and the inhibition T-bar `baseDash`. An oval, diamond, dash or
ER symbol at an end is not an arrow. A marker drawio doesn't list as either
gives no edge line. Every page of the file is read.

A `.drawio.svg` file (drawio's editable SVG export) is read as an SVG: its
labels are quotable, but it carries no `data-source`/`data-target`, so it
gives no edge lines. Point at the `.drawio` source to quote its edges.

Not read: cells marked invisible, in a hidden layer, or inside a collapsed
group; labels switched off (`noLabel`) or drawn with zero `opacity`,
`textOpacity` or `fontSize`, or with no `fontColor`; layer and page names,
tooltips, styles and other attributes. HTML labels follow the same visibility
rules as SVG `<foreignObject>` labels. A label computed from placeholders
(`placeholders="1"`), or HTML that cannot be read statically, makes the
reference `unavailable`.

## Using in Data Files

Both file and URL references work in LinkML data files:

```yaml
# data.yaml
- id: local-evidence
  supporting_text: JAK1 binds to the receptor complex
  reference: file:./research/jak-notes.md

- id: web-evidence
  supporting_text: Climate impacts are accelerating
  reference: url:https://example.org/climate-report.html
```

## Reference Type Summary

| Prefix | Example | Source |
|--------|---------|--------|
| `PMID:` | `PMID:16888623` | PubMed via NCBI Entrez |
| `DOI:` | `DOI:10.1038/nature12373` | Crossref API |
| `file:` | `file:./notes.md` | Local filesystem |
| `url:` | `url:https://example.com` | Web (HTTP/HTTPS) |

## Best Practices

### For Local Files

- Keep reference files in a dedicated directory
- Use `reference_base_dir` for consistent path resolution
- Use markdown for structured content with clear headings

### For URLs

- Prefer stable URLs (avoid query parameters that change)
- Be aware that web content may change (cache helps with reproducibility)
- Consider downloading important pages as local files for long-term stability

## Limitations

- **Local files are read as text**, apart from `.svg` figures (see above).
  An `.html` file is matched against its raw markup.
- **Local PDF files**: Not yet supported as `file:` references. PDFs fetched by `url:` are supported.
- **Authentication**: URLs requiring login are not supported
- **Dynamic content**: JavaScript-rendered pages may not work
