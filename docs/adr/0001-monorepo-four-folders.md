# ADR 0001 - Monorepo with four product folders

**Status**: accepted

We keep one repository with frontend/, backend/, database/, ml/ as peer folders. Alternatives: polyrepo (rejected: SMB-scale team, atomic cross-cutting changes are common) or src/ nesting (rejected: the four folders ARE the mental model and map 1:1 to containers). Consequence: docker build context is the repo root; FILE-MAP.md is the navigation contract.
