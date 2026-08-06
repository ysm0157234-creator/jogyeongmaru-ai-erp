# v20.1 actual-project-stable

- Fixed `RequiredFileMissingError` import compatibility that prevented Render startup.
- Kept the modular workflow, image, Drive, document, and package services.
- Added PostgreSQL NUL-byte sanitization for report and AI-draft writes.
- Preserved 2025 → 2024 → 2023 scoped Drive lookup only.
- Preserved HWPX + DOCX fallback and optional image/document placeholders.
