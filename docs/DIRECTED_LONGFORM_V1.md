# User-directed longform v1

This is the reusable path for a video whose narration, research and editorial shot decisions were
supplied by the operator. It does not enter the model-authored explainer pipeline.

## API flow

1. `GET /api/explainer/directed/schema` returns the canonical JSON Schema.
2. `GET /api/explainer/directed/template` downloads a complete fillable JSON starter. Its
   unresolved evidence/reference placeholders deliberately prevent accidental spending.
3. `POST /api/explainer/directed/validate` with `{"spec": {...}}` performs a free preflight.
4. A passing response returns `spec_sha256`, a full-film estimate and a separate pilot estimate.
5. `POST /api/explainer/directed/process` must resubmit the unchanged spec, that hash, and
   `"authorize_paid": true`.
6. Processing revalidates the JSON and hash, generates/measures narration, and stops before images
   if measured timing fails. The current endpoint renders only the first-45 pilot. Full-film
   processing remains unavailable until the encoded pilot receives the separate editorial grade.

The web UI exposes the same sequence under **User-directed longform JSON**.

## Required contract sections

- `schema_version`: `directed_longform_v1`
- `project_id`, `title`
- `target`: runtime, pilot window, voice and cost ceiling
- `acceptance`: unchangeable run thresholds
- `worlds`: explicit time ranges and base visual prompts
- `narration`: stable scene IDs, exact text, timings, world and claim references
- `shots`: stable IDs, contiguous timing, world, mode, evidence/reference IDs and `asset_key`
- `evidence`: claims, sources, qualifications and resolved usage/license status
- `references`: URI, SHA-256, MIME, origin and license
- `prohibited_claims`

`asset_key` is the reuse contract. `asset_prompt` defines the paid master image; `visual` describes
the shot the viewer sees, and `transformation` records the crop/camera treatment. Reused keys must
share a master prompt, world and references, and every member must name its transformation. The
validator rejects conflicting or implicit reuse and rejects plans above the declared unique-master
cap. This prevents a 45–60-master plan from silently becoming 181 unrelated paid images.

## Paid and failure behavior

- Validation imports no generation provider and spends nothing.
- Authorization is bound to the canonical spec hash. Any edit requires validation again.
- TTS is the first paid stage. Measured timing is checked before visual generation.
- Declared image references are resolved and checked against their SHA-256 and MIME contract
  before TTS; an unavailable or corrupt reference spends nothing.
- Image reuse includes the full prompt identity.
- I2V cache identity includes source-image bytes, prompt, duration, dimensions and provider model.
- The generation manifest records provider/model IDs, SHA-256 and MIME for produced assets.
- Final video muxing uses MP4 fast-start.
- A failed pilot and every artifact produced before the stop remain failed artifacts; nothing is
  manually replaced or reclassified as a pass.

## Markdown adapter

`user_directed.compile_directed_spec(path)` converts an existing production Markdown document into
the canonical JSON shape. It deliberately does not invent evidence mappings, licenses or master
reuse groups. Those omissions appear as validation failures and must be resolved in JSON before a
paid run.
