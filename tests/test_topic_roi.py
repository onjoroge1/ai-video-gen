import topic_roi


def test_cross_channel_dedupe_keeps_stronger_candidate():
    groups = [
        {"label": "Earth", "questions": [{"question": "What If Earth Spun 1% Faster?",
                                            "opportunity": 81, "curiosity_gap": 9}]},
        {"label": "Physics", "questions": [{"question": "What Happens If Earth Spins One Percent Faster?",
                                              "opportunity": 62, "curiosity_gap": 8}]},
    ]
    deduped = topic_roi.dedupe_topic_groups(groups, threshold=0.45)
    assert len(deduped[0]["questions"]) == 1
    assert deduped[1]["questions"] == []


def test_own_channel_fit_uses_format_and_retention_not_views_alone():
    metrics = [
        {"format": "social", "title": "Dinosaur quiz", "tags": "quiz animals",
         "views": 1600, "stayed_pct": 16, "video_len_sec": 30, "avg_view_dur_sec": 10,
         "subs_gained": 2},
        {"format": "social", "title": "What If Earth Lost One Percent of Its Water?",
         "tags": "earth water oceans science", "views": 1100, "stayed_pct": 56,
         "video_len_sec": 34, "avg_view_dur_sec": 25, "subs_gained": 4},
        {"format": "landscape", "title": "Earth magnetic field explained", "views": 500,
         "video_len_sec": 480, "avg_view_dur_sec": 250, "ctr": 5.0, "subs_gained": 5},
    ]
    earth_fit, evidence = topic_roi.own_channel_fit(
        "What Happens If Earth Loses Fresh Water?", "short", metrics)
    quiz_fit, _ = topic_roi.own_channel_fit("Can You Guess These Dinosaurs?", "short", metrics)
    long_fit, long_evidence = topic_roi.own_channel_fit("Why Earth Has a Magnetic Field", "long", metrics)
    assert earth_fit > quiz_fit
    assert evidence == 1
    assert long_evidence == 1
    assert long_fit > 0.5


def test_velocity_and_production_quality_raise_roi():
    topic = {"curiosity_gap": 9, "visual_promise": 9, "production_fit": 9,
             "fact_confidence": 9, "novelty": 8}
    strong = {"relevant_count": 5, "median_views_per_day": 2500, "outlier": 90,
              "median_views": 250000, "recency_days": 60, "competition": 5}
    stale = {"relevant_count": 5, "median_views_per_day": 8, "outlier": 4,
             "median_views": 5000, "recency_days": 1800, "competition": 11}
    strong_score, breakdown = topic_roi.opportunity_score(topic, strong, own_fit=0.8)
    stale_score, _ = topic_roi.opportunity_score(topic, stale, own_fit=0.35)
    assert strong_score > stale_score + 20
    assert breakdown["velocity"] > 0.8


def test_channel_feedback_scores_topics_without_youtube_key(monkeypatch):
    import explainer_pipeline as pipeline

    monkeypatch.setattr(pipeline, "YOUTUBE_API_KEY", "")
    candidates = [{"question": "What Happens If Earth Loses Fresh Water?",
                   "curiosity_gap": 9, "visual_promise": 8, "production_fit": 8,
                   "fact_confidence": 8, "novelty": 7}]
    metrics = [{"format": "social", "title": "Earth loses fresh water",
                "views": 1200, "stayed_pct": 58, "video_len_sec": 35,
                "avg_view_dur_sec": 27, "subs_gained": 4}]

    ranked = pipeline.validate_topics_youtube(candidates, "short", metrics)

    assert ranked[0]["validated"] is False
    assert ranked[0]["opportunity"] > 0
    assert ranked[0]["own_fit"] > 0.5
    assert ranked[0]["score_breakdown"]["own_fit"] == ranked[0]["own_fit"]
