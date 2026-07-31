"""Finish the keep/unlist audit: validate the quota-blocked titles in pending_audit.json.
Run after the YouTube quota resets. Writes results to finished_videos/pending_audit_results.json."""
import json, time, os
import explainer_pipeline as ep

PEND = "finished_videos/pending_audit.json"
OUT = "finished_videos/pending_audit_results.json"

pending = json.load(open(PEND))
titles = [p["title"] for p in pending]

# curiosity grade (one call, same order)
r = ep._claude().messages.create(model="claude-opus-4-8", max_tokens=2000, system=ep._CURIOSITY_SYSTEM,
    messages=[{"role": "user", "content":
        "Grade EACH title on curiosity_gap (0-10) per your rubric, same order. "
        "Return ONLY JSON {\"questions\":[{\"question\":\"<echo>\",\"curiosity_gap\":<int>}]}.\n"
        + "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))}])
data, _ = ep._parse_script_json(r.content[0].text)
gq = data.get("questions", [])
cg = [int(gq[i].get("curiosity_gap", 6)) if i < len(gq) else 6 for i in range(len(titles))]

# validate one at a time with a delay to avoid the QPS throttle that bit the batch run
results = []
for i, p in enumerate(pending):
    cand = [{"question": p["title"], "curiosity_gap": cg[i]}]
    out = ep.validate_topics_youtube(cand)[0]
    out["channel"] = p["channel"]
    results.append(out)
    time.sleep(2)

results.sort(key=lambda x: -(x.get("opportunity") or 0))
json.dump(results, open(OUT, "w"), indent=2)

print(f"{'opp':>3} {'pattern':>9} {'out':>7} {'median':>9} ch  title")
for q in results:
    if q.get("validated"):
        print(f"{q.get('opportunity',0):>3} {q.get('pattern','?'):>9} {str(q.get('outlier'))+'x':>7} "
              f"{q.get('median_views',0):>9} {q.get('channel'):>3}  {q['question'][:48]}")
    else:
        print(f"{'FAIL':>3} {'(quota?)':>9} {'':>7} {'':>9} {q.get('channel'):>3}  {q['question'][:48]}")
print(f"\nwrote {OUT}")
