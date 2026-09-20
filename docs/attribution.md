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
| Google Stitch (UI Layout) | https://stitch.withgoogle.com | Proprietary Design Tool (User-Authored Export) | dashboard/index.html (visual mockup reference) | 2026-09-19 |

---

## Notes

- Dashboard layout and visual component structure were originally designed and exported using Google Stitch as a prototype reference, then adapted and rebuilt natively into a single-file static HTML/CSS/JS application (`dashboard/index.html`) with zero external CDN dependencies.
- Standard package-manager dependencies (`boto3`, standard library `http.server`, `urllib`, `unittest`) use their standard permissive OSS licenses.
