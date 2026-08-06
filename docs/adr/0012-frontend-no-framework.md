# ADR 0012 - Frontend: framework-free ES files split by feature

**Status**: accepted

A build-free frontend (per-feature JS files, ordered script tags) keeps the edit-one-file promise literal, removes toolchain drift, and loads fast. The seam to React/Vite later: views are already per-file with one state object and one api() client. Chosen consciously over React+Vite at this codebase size; revisit around 3k lines per file.
