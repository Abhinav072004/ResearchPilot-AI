# Threat model and privacy

| Boundary | Threat | Required control |
| --- | --- | --- |
| Browser → gateway | Session theft, request forgery, hostile rendering | TLS, opaque expiring sessions, HttpOnly and SameSite cookies, origin checks and escaped rendering |
| API → data | Cross-tenant ID access | Project membership on each lookup and mutation, opaque identifiers, authorization tests and tenant-scoped backups |
| Upload → parser | Malformed files, malware, resource exhaustion | Quarantine, malware scan, signatures, size and runtime limits, isolated parser and no public object access |
| App → upstream | Unsafe URL fetching or data leakage | Fixed provider destinations, no arbitrary redirects, bounded requests, no automatic publication or fetching of arbitrary links |
| Evidence → model | Indirect instructions in scholarly text | Structural data boundaries, tool-free reranking, validated ID outputs, explicit network/model opt-in and trusted-code routing |
| Model → report | Fabricated claims or citations | Resolve immutable stored passage IDs, require supporting text and withhold unverified claims |
| Operations | Secret leakage or data loss | Scoped credentials, encrypted storage, redacted logs, retention rules and tested restore |

Private uploads require permission from the user. Keep confidential projects on local processing unless a permitted external provider is explicitly approved. Store security events without prompts, raw document text, session tokens or passwords. Separate operational metrics from research content. Deployment operators must verify scan behavior and retention policies before handling sensitive documents.


## Licensed imports and OCR

The importer addresses fixed Europe PMC API endpoints, disables redirects, bounds response size and time, and checks both the metadata search match and the DOI embedded in the article. Eligible JATS documents declare CC BY or CC0 in their article-level licence. The application preserves authorship metadata, source URL and licence with the evidence. Imported originals stay private to the project and go through the same scanner as uploads.

OCR runs Tesseract on bounded grayscale renderings when a PDF page has images without a native text layer. The worker records the original page number, coordinates, extraction engine and average word confidence. Page count, pixel count, per-page time and overall OCR time are limited. OCR confidence is distinct from the accuracy of a scientific claim.
