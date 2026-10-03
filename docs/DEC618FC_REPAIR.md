# Changes following Studio job dec618fc

The saved job failed at claim-ledger validation after fact-checking. Its preliminary
editorial score was 76; two sentence-trimming passes left 11 errors. Recorded spend
was $3.94. No passing final script or media delivery was established.

This change exposes the exact failed script and report from the latest timestamped,
allowlisted semantic-failure diagnostic when a job is in error, even if `_state.json`
is absent or contains an earlier draft. Studio labels its source and keeps it unapproved.

The parallel-case check ignores generic geography and animal words, uses whole-word
matches, and recognizes four-letter names such as Guam. This removes the observed
“island” false positive without ignoring explicit comparison names. It remains a
lexical heuristic, not a semantic guarantee.

Targeted claim repair now copies reports before resolving scene IDs, selects at most
four addressable scenes despite unrelated hard errors, and limits each scene to its
event's attached claim IDs. Legacy events without references retain dossier scope.
Other errors remain blocking. The exact event, supported-core feedback, neighboring
narration and allowed IDs guide the edit; grammar, duplicate and full ledger checks
remain authoritative. Non-improving candidates are discarded with billable cost retained.
Semantic plan and graded-script versions change to prevent old validation results from
silently satisfying the new rules. No automatic recovery permission is added.

The complete live failed narration has not yet been retrieved through the updated
viewer. After merge, inspect dec618fc read-only before choosing another paid test.
These offline regressions do not establish a production pass or measured retention.
