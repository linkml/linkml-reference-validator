# JATS regression fixture

`PMC5593426.xml` retains Table 1, article identifiers/title and the original
permissions from the Europe PMC response for PMID:28530713 / PMC5593426,
downloaded 2026-09-15 from:
https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5593426/fullTextXML

Full downloaded response SHA-256:
`f9512138d416f28467b81373fd1157766c868ca90bbf6129933ea3b968912ae7`

The article is *BACH2 immunodeficiency illustrates an association between
super-enhancers and haploinsufficiency*, DOI:10.1038/ni.3753.
Table 1 contains the immunoglobulin findings reported in issue #68. Its source
`table-wrap` (T1), including caption, rows and notes, is preserved inside a
minimal article with the original `floats-group` placement. BeautifulSoup's XML
serializer normalized markup; table text and attributes were not edited.
Article prose, other figures, references and supplementary material are omitted.

The original permissions remain in the excerpt. Only the relevant table and
provenance metadata are retained for regression testing; the complete manuscript
is not included and the excerpt is not relicensed.
