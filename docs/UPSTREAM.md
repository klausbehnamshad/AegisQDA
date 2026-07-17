# Pinned DigQDA upstream

`vendor/digqda/` is a read-only source snapshot of DigQDA commit
`530554451d52dcdaaf62a29d6084b85a481be345` from local branch `main`.
`UPSTREAM.lock.json` records the snapshot manifest hash and exclusions.

Rules:

1. Never edit the sibling `/Users/klaus.behnamshad/Projects/DigQDA` from this repo.
2. Never import or reference DINOH.
3. A future upstream refresh is an explicit, reviewed operation which regenerates
   the snapshot manifest, runs DigQDA's complete conformance suite and records a
   migration note.
4. AegisQDA-specific privacy code lives outside `vendor/digqda/`.

