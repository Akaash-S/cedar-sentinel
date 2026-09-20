<!-- Intended repo path: docs/attribution.md -->
# Attribution Log

Required by the First Commit rules: *"Anything you didn't write needs a credit and a
licence that permits the use."* Add a row the first time any open-source library,
template, boilerplate, or public API is introduced — not retroactively.

| Asset / Library | Source (URL) | License | Where used | Date added |
|---|---|---|---|---|
| Inter | https://fonts.google.com/specimen/Inter | SIL Open Font License 1.1 | dashboard/index.html | 2026-09-19 |
| JetBrains Mono | https://fonts.google.com/specimen/JetBrains+Mono | SIL Open Font License 1.1 | dashboard/index.html | 2026-09-19 |
| Plus Jakarta Sans | https://fonts.google.com/specimen/Plus+Jakarta+Sans | SIL Open Font License 1.1 | dashboard/index.html | 2026-09-19 |
| Material Symbols / Lucide Vector Icons | https://fonts.google.com/icons / https://lucide.dev | Apache-2.0 / MIT | dashboard/index.html (inline SVG sprite) | 2026-09-19 |

---

## Notes

- Standard package-manager dependencies (`boto3`, `aws-sdk-go-v2`, base Go/Python standard
  library) don't need an individual row unless the license is non-standard — over-inclusion
  is safer than omission if unsure.
- Anything copy-pasted from a tutorial, Stack Overflow, or AI-generated boilerplate that
  traces to a specific external source still gets a row.
- Cedar or Terraform snippets adapted from AWS's own docs are worth noting too, even though
  low-risk — precision costs nothing here.
