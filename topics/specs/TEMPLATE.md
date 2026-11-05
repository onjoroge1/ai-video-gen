# Spec: <working title>

Copy this file to `topics/specs/<slug>.md`, fill the JSON block, and run

    python3 scripts/import_spec.py topics/specs/<slug>.md --out jobs/<slug>

Prose outside the fenced block is your notes; only the block is read. The full format is in
docs/SPEC_IMPORT.md. Rules that matter most:

- Every factual sentence carries its source URL and the **exact** quote from that page — copy it,
  do not paraphrase. ReelForge fetches the page itself and checks the quote is there.
- Lines with no claims are framing ("You want dinner."). A framing line that states a number or
  says who said something is flagged as unsourced.
- A claim used again later is cited by its id (`"cite": ["c01"]`), not redefined.
- `evidence` is `documented` (it happened and the source says so), `model` (a model, projection or
  estimate) or `interpretation` (an expert's reading, a hedge: may, could, suggests). Only a
  documented event or outcome can BE the consequence; a hedged or model quote is never treated as
  documented, whatever the label.
- World films: a past deliberate, named, dated decision -> its documented consequence -> a dated
  sign (within five years) that it is still unfolding -> a question about that consequence,
  never a forward hypothetical ("What happens when ...?").
- ChatGPT tip: ask it to fill this block from the pages you give it and to copy quotes character
  for character. ReelForge never rewrites your narration; failed lines get a suggestion in the
  report and you edit the spec.

```json
{
  "spec_version": 1,
  "slug": "example-slug",
  "channel": "world",
  "duration_sec": 300,
  "title": "Florida Let Pet Pythons Into the Everglades. Why Are Hunters Still Pulling Them Out?",

  "decision": {
    "what": "Burmese pythons imported through the exotic pet trade, released or escaped",
    "who": "pet owners and the exotic pet trade",
    "when": "1980s-1990s",
    "kind": "animal_introduced",
    "cite": ["c01"]
  },
  "consequence": {
    "what": "fur-bearing mammals in parts of the Everglades fell by up to 95 percent",
    "cite": ["c02"]
  },
  "still_unfolding": {
    "what": "over 23,500 pythons removed as of April 2025",
    "as_of": "2025",
    "cite": ["c03"]
  },
  "central_question": "Florida let pet pythons into the Everglades; why are hunters still pulling them out by the thousand?",
  "ending_answer": "Because the pets that escaped are still eating the Everglades.",
  "human": {
    "person": "a contracted python hunter (named only if a source names them)",
    "want": "paid removals",
    "detail": "one concrete, sourced detail: a night hunt, a number, a quote"
  },
  "forbidden_claims": ["pythons can be eradicated"],
  "recurring_image": "a hunter's headlamp beam across the sawgrass",
  "render": {"palette": "natural", "music_mix": "ambient_pad", "voice": "echo"},

  "sources": {
    "route": "https://www.example.org/pythons-everglades-2025",
    "fwc": "https://www.example.org/fwc-python-program"
  },

  "narration": [
    {"say": "Picture a pet snake that outgrew its tank.", "part": "opening",
     "picture": "a young Burmese python coiled in a glass tank in a suburban living room"},
    {"say": "Burmese pythons came to Florida through the pet trade, and some escaped or were released.",
     "claims": [{"id": "c01", "source": "route", "kind": "event", "evidence": "documented",
                 "quote": "they were brought through the exotic pet trade and escaped their enclosures or were released"}]},
    {"say": "In parts of the Everglades, fur-bearing animals fell by up to 95 percent.", "part": "development",
     "claims": [{"id": "c02", "source": "route", "kind": "outcome", "evidence": "documented",
                 "quote": "The pythons have reduced the population of fur-bearing animals by up to 95%"}]},
    {"say": "As of April 2025, hunters had pulled out more than 23,500.", "part": "ending",
     "claims": [{"id": "c03", "source": "fwc", "kind": "event", "evidence": "documented",
                 "quote": "As of April 2025, over 23,500 pythons have been removed from natural areas in the state of Florida"}]},
    {"say": "Every one of them came from the same decision.", "cite": ["c01"]},
    {"say": "And the snakes are still out there."}
  ]
}
```

Field reference (all in docs/SPEC_IMPORT.md):

- `part`: opening | attempt | complication | development | ending; carries forward to later lines.
- `kind` (ledger): event | outcome | mechanism | context | general_principle.
- `decision.kind`: animal_introduced | animal_removed | animal_targeted | invention_adopted |
  product_adopted | rule_enforced.
- `source`: a key of `sources` or a full https URL. Optional per claim: `claim` (the fact in plain
  words; defaults to the line), `source_type` (primary | authoritative_secondary), `scope`.
- `picture`: optional; what we see when that line starts. Lines without one get a default picture.
