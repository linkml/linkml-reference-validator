# HTML full-text regression fixtures

Downloaded 2026-09-14; tests use local HTTP and need no live repository access.
These are extracts of actual served markup, not reconstructions of repository
labels. All visible text, section nesting, headings, links, and inline markup in
the selected regions are retained except the exclusions below.

- `dspace-32894695.html`: `<main>` from
  https://dspace.library.uu.nl/handle/1874/443151, the exact item in issue #65.
  Angular generated attributes/classes, styles, and comments removed. Contains
  the abstract, metadata, and the download link for `m20_1443.pdf`, but no body.
- `iris-19049553.html`: `<main>` from
  https://www.research.unipd.it/handle/11577/2270230, the record implicated in
  monarch-initiative/dismech#7899. Scripts, styles, and comments removed.
- `plos-0000308.html`: `#artText` from
  https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0000308.
  Piwowar, Day, and Fridsma (2007), *Sharing Detailed Research Data Is Associated
  with Increased Citation Rate*, PLOS ONE 2(3): e308, CC BY.
  Figure, table, references containers and comments removed. The downloaded
  markup has duplicate section IDs in abstract/body: tests locate body sections
  by their actual headings. Short/flat-layout tests derive variants from these
  real research paragraphs and retain their inline markup.
