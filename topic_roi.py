"""Deterministic Topic ROI v2 scoring and deduplication.

LLMs propose candidates; this module decides how much evidence they deserve.  Keeping the scoring
pure makes it testable and prevents a persuasive model response from silently overriding channel
performance or market reality.
"""
from __future__ import annotations

import math
import re
from statistics import median


_STOP = frozenset((
    "a an the of to in on for and or but with without is are was were be been being this that these "
    "those it its do did does how why what when where who which will would can could your you their "
    "our we they from into out up down over under than then if not no yes about more most very just "
    "only also every happens happen thing things actually really first"
).split())


def _stem(word: str) -> str:
    irregular = {"spun": "spin", "spins": "spin", "lost": "lose", "fell": "fall",
                 "faster": "fast", "slower": "slow"}
    if word in irregular:
        return irregular[word]
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    if len(word) > 4 and word.endswith("ies"):
        word = word[:-3] + "y"
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word


def topic_tokens(text: str) -> set[str]:
    normalized = (text or "").lower().replace("%", " percent ")
    numbers = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
               "ten": "10", "hundred": "100"}
    return {_stem(numbers.get(word, word)) for word in re.findall(r"[a-z0-9]+", normalized)
            if (len(word) >= 3 or word.isdigit() or word in numbers) and word not in _STOP}


def topic_similarity(left: str, right: str) -> float:
    a, b = topic_tokens(left), topic_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedupe_topic_groups(groups: list[dict], threshold: float = 0.56) -> list[dict]:
    """Remove exact and close paraphrases across every channel, keeping the strongest candidate."""
    ranked = []
    for group_idx, group in enumerate(groups):
        for topic_idx, topic in enumerate(group.get("questions") or []):
            ranked.append((
                1 if topic.get("queued") else 0,
                float(topic.get("opportunity") or -1),
                float(topic.get("curiosity_gap") or 0),
                group_idx,
                topic_idx,
                topic,
            ))
    ranked.sort(reverse=True, key=lambda item: item[:3])
    accepted: list[tuple[set[str], str]] = []
    keep: set[tuple[int, int]] = set()
    for _, _, _, group_idx, topic_idx, topic in ranked:
        question = str(topic.get("question") or "").strip()
        tokens = topic_tokens(question)
        duplicate = False
        for prior_tokens, prior_question in accepted:
            similarity = (len(tokens & prior_tokens) / len(tokens | prior_tokens)
                          if tokens and prior_tokens else 0.0)
            if question.lower() == prior_question.lower() or similarity >= threshold:
                duplicate = True
                break
        if not duplicate:
            accepted.append((tokens, question))
            keep.add((group_idx, topic_idx))

    out = []
    for group_idx, group in enumerate(groups):
        copied = dict(group)
        copied["questions"] = [topic for topic_idx, topic in enumerate(group.get("questions") or [])
                               if (group_idx, topic_idx) in keep]
        out.append(copied)
    return out


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _is_short_metric(row: dict) -> bool:
    return str(row.get("format") or "").lower() in ("social", "short", "shorts", "9:16")


def _metric_quality(row: dict, content_format: str) -> float:
    views = max(0.0, _number(row.get("views")))
    length = max(0.0, _number(row.get("video_len_sec")))
    avd = max(0.0, _number(row.get("avg_view_dur_sec")))
    pct_viewed = _number(row.get("pct_viewed"), -1)
    if pct_viewed < 0 and length and avd:
        pct_viewed = 100 * avd / length
    subs = max(0.0, _number(row.get("subs_gained")))
    sub_per_1k = (1000 * subs / views) if views else 0.0
    view_score = min(1.0, math.log10(views + 1) / 4.0)  # 10k views is full credit
    sub_score = min(1.0, sub_per_1k / 5.0)

    if content_format == "short":
        stayed = max(0.0, _number(row.get("stayed_pct")))
        hook_score = min(1.0, stayed / 60.0)
        hold_score = min(1.0, max(0.0, pct_viewed) / 85.0) if pct_viewed >= 0 else hook_score
        return 0.35 * hook_score + 0.30 * hold_score + 0.20 * view_score + 0.15 * sub_score

    hold_score = min(1.0, max(0.0, pct_viewed) / 65.0) if pct_viewed >= 0 else 0.0
    ctr_score = min(1.0, max(0.0, _number(row.get("ctr"))) / 6.0)
    return 0.40 * hold_score + 0.25 * ctr_score + 0.20 * view_score + 0.15 * sub_score


def own_channel_fit(question: str, content_format: str, metrics: list[dict]) -> tuple[float, int]:
    """Return a 0..1 prior from actual channel outcomes plus the evidence count.

    Similar subjects/tags carry most weight.  When no semantic neighbor exists, the format's median
    supplies only a weak prior, preventing five quiz uploads from becoming "proof" for a physics idea.
    """
    want_short = content_format == "short"
    rows = [row for row in metrics if _is_short_metric(row) == want_short]
    if not rows:
        return 0.5, 0
    scored = []
    for row in rows:
        haystack = " ".join(str(row.get(key) or "")
                            for key in ("question", "title", "tags", "notes"))
        similarity = topic_similarity(question, haystack)
        scored.append((_metric_quality(row, content_format), similarity))

    related = sorted(((quality, similarity) for quality, similarity in scored if similarity >= 0.08),
                     key=lambda pair: pair[1], reverse=True)[:6]
    if related:
        weights = [0.25 + 0.75 * similarity for _, similarity in related]
        value = sum(quality * weight for (quality, _), weight in zip(related, weights)) / sum(weights)
        return round(max(0.0, min(1.0, value)), 3), len(related)

    weak_prior = 0.45 * median(quality for quality, _ in scored) + 0.275
    return round(max(0.0, min(1.0, weak_prior)), 3), 0


def opportunity_score(topic: dict, market: dict, own_fit: float) -> tuple[int, dict]:
    """Blend creative, market, channel and production evidence into a 0..100 ROI score."""
    curiosity = min(1.0, max(0.0, _number(topic.get("curiosity_gap")) / 10.0))
    visual = min(1.0, max(0.0, _number(topic.get("visual_promise"), 5) / 10.0))
    production = min(1.0, max(0.0, _number(topic.get("production_fit"), 5) / 10.0))
    fact = min(1.0, max(0.0, _number(topic.get("fact_confidence"), 5) / 10.0))
    novelty = min(1.0, max(0.0, _number(topic.get("novelty"), 5) / 10.0))
    relevant = max(0.0, _number(market.get("relevant_count")))
    evidence = 0.45 + 0.55 * min(1.0, relevant / 4.0)

    median_velocity = max(0.0, _number(market.get("median_views_per_day")))
    velocity = min(1.0, math.log10(median_velocity + 1) / 4.0)  # 10k/day = 1
    outlier = min(1.0, math.log1p(max(0.0, _number(market.get("outlier")))) / math.log(501))
    demand = min(1.0, math.log10(max(0.0, _number(market.get("median_views"))) + 1) / 6.0)
    age = market.get("recency_days")
    recency = (0.0 if relevant == 0 else 1.0 if age is not None and age <= 180
               else 0.75 if age is not None and age <= 365 else 0.45 if age is not None else 0.35)
    saturation = min(1.0, max(0.0, _number(market.get("competition"))) / 12.0)

    score = (
        0.18 * curiosity
        + evidence * (0.17 * velocity + 0.13 * outlier + 0.09 * demand + 0.07 * recency)
        + 0.14 * max(0.0, min(1.0, own_fit))
        + 0.08 * visual + 0.06 * production + 0.04 * fact + 0.04 * novelty
        - 0.10 * saturation
    )
    breakdown = {
        "curiosity": round(curiosity, 3), "velocity": round(velocity, 3),
        "outlier": round(outlier, 3), "demand": round(demand, 3),
        "recency": round(recency, 3), "own_fit": round(own_fit, 3),
        "visual": round(visual, 3), "production": round(production, 3),
        "fact": round(fact, 3), "novelty": round(novelty, 3),
        "evidence": round(evidence, 3), "saturation": round(saturation, 3),
    }
    return max(0, min(100, round(100 * score))), breakdown
