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

PR154's production viewer subsequently exposed the complete failed narration. That
inspection identified a changed denominator (half of chick deaths became half of all
chicks), an orphaned "It survives", a missing Guam introduction, and a closing lesson
that reversed predator introduction into removal. The failure report also called an
omitted reserve name "not flagged" while treating it as unsupported.

## Follow-up: meaning and sequence integrity

`script_integrity.py` reviews the complete spoken sequence, including empty-event
discourse and closing lines that the local factual cascade intentionally skips. It
receives scene events and their cited ledger statements/source quotes. It reports
addressable metric changes, causal reversals, unresolved references and missing case
transitions. This complements, rather than replaces, the existing sourcing boundaries.
The claim gate includes these errors; Studio's final readiness check therefore cannot
approve an integrity failure. The private viewer shows `_script_integrity` separately.

Drafting, entailment and targeted repair share explicit meaning-preservation rules.
The editor receives the new scene-level findings and retains its four-scene batch and
existing attempt limits. A source judge's supported-core paraphrase is not new evidence.
Contradictory entailment replies (including "not flagged" failures) retry once and then
fail as an operational problem rather than becoming destructive edit instructions.

Whole-script review costs one bounded 2,400-output-token request per distinct input,
with at most one retry for invalid/unavailable output. Exact quotes and scene numbers
are validated before findings can reach the editor. Input hashes cover ordered wording,
events, cited claims and source passages; unchanged reviews reuse the script-local
checkpoint cache. Contract versions also invalidate old plan/graded-script results.
No new job restart permission or budget allowance is introduced.

Mechanical trimming no longer guesses a sentence to delete from lexical overlap.
Exact-span trim candidates are copied, rebound and revalidated before acceptance.
Both targeted edits and trims require fewer errors and reject a new meaning/continuity
error even when total error count falls. Rejected candidates retain the prior draft;
provider validation/repair costs remain accounted for. An unavailable judge stops edits.

The regression suite covers these control paths offline. Nine Promptfoo cases include
the observed defects plus corrected wording and harmless name omission, using the
production review prompt with explicit expected findings. They are paid opt-in tests,
not results: neither these fixtures nor mocked tests establish that the live judge is
accurate or that a script will achieve high YouTube retention. After deployment, run
the authenticated Studio script-only test and inspect its exact final narration and
readiness report. The historical dec618fc failure remains a failure.
