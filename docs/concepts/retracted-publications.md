# Retracted publications

The validator treats publication integrity separately from text matching. A
quotation can occur verbatim in a paper while that paper is no longer suitable
as ordinary scientific evidence.

## PubMed-native status

For PMID references, retraction status comes from the same PubMed XML response
used for the abstract, keywords, and publication types. Refreshing a PMID does
not call a separate retraction service.

When PubMed identifies the affected article as `Retracted Publication`, the
primary cache file records:

```yaml
publication_types:
- Journal Article
- Retracted Publication
publication_status: retracted
retraction_notice_ids:
- PMID:987654
```

`Retraction Notice` identifies the notice about another paper; it does not mark
the notice itself as a retracted publication. Notice links are taken from
PubMed's `RetractionIn` relationships.

## Validation policy

A retracted publication cannot support ordinary evidence. Validation therefore
returns an error even if the supporting text is found, while retaining the text
match in the result for diagnosis. Existing cache files that contain the
`Retracted Publication` publication type are protected before they are
refreshed to include the explicit status field.

Force refresh remains a deterministic pull from the primary provider: it
replaces `PMID_nnn.md` with PubMed's current metadata. Future independent
integrity sources, such as Retraction Watch, can use optional provider sidecars
without changing the primary cache-file model.
