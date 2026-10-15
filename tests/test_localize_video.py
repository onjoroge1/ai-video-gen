"""Localized metadata keeps every number, link and chapter; subtitles keep their timings."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import localize_video as lv  # noqa: E402

SOURCE = {"title": "America Brought in 1 Fish. It Took Over 45 States.",
          "description": "Carp escaped.\n\n0:00 The Green Pond\n2:26 Growth\n\nSource: https://www.doi.gov/x"}


def test_a_faithful_translation_passes():
    ok = {"title": "Estados Unidos trajo 1 pez. Terminó invadiendo 45 estados.",
          "description": "Las carpas escaparon.\n\n0:00 El estanque verde\n2:26 Crecimiento\n\n"
                         "Fuente: https://www.doi.gov/x"}
    assert lv.check_translation(SOURCE, ok) == []


def test_lost_numbers_links_and_chapters_are_refused():
    bad = {"title": "Estados Unidos trajo un pez. Invadió el país.",
           "description": "Las carpas escaparon.\n\n0:00 El estanque\n\nFuente: https://doi.gov"}
    problems = " ".join(lv.check_translation(SOURCE, bad))
    assert "lost numbers" in problems and "lost URL" in problems and "2:26" in problems
    assert lv.check_translation(SOURCE, {"title": "x" * 101, "description": SOURCE["description"]})


def test_subtitles_round_trip_with_their_timings():
    srt = "1\n00:00:00,000 --> 00:00:14,880\nFirst line\nsecond line\n\n2\n00:00:14,880 --> 00:00:26,880\nNext.\n"
    cues = lv.parse_srt(srt)
    assert [c["time"] for c in cues] == ["00:00:00,000 --> 00:00:14,880", "00:00:14,880 --> 00:00:26,880"]
    assert cues[0]["text"] == "First line second line"
    assert lv.parse_srt(lv.render_srt(cues)) == cues


# --- the film template, 2026-10-14 ----------------------------------------------------------------

TEMPLATE_SOURCE = {
    "title": "The Cotton Plan That Worked and Shrank the Aral Sea",
    "description": (
        "By 1961 the Syr Darya delivered zero water. Roughly 60,000 jobs vanished.\n\n"
        "Every factual line in this film was checked against quoted passages from the sources below.\n\n"
        "⏱️ CHAPTERS\n0:00 The Lifeline\n1:13 Doubling Down\n\n"
        "📚 RESEARCH & SOURCES\nasianstudies.org\nhttps://www.asianstudies.org/a\n"
        "↳ In 1961 the station at Kazalinsk recorded no discharge for the year.\n\n"
        "ReliefWeb, health in Karakalpakstan (anemia survey)\nhttps://reliefweb.int/r\n"
        "↳ A survey found an 80 to 90 percent rate of anemia.\n\n"
        "📍 PEOPLE & PLACES IN THIS FILM\nMoynaq — Now about 150 kilometres from the water.\n\n"
        "#AralSea\n\n🤖 AI line.")}


def _translated(**changes):
    desc = (
        "Para 1961 el Syr Darya no aportaba agua. Desaparecieron unos 60.000 empleos.\n\n"
        "Cada línea factual de esta película se comprobó con pasajes citados de las fuentes.\n\n"
        "⏱️ CAPÍTULOS\n0:00 El sustento\n1:13 Redoblar la apuesta\n\n"
        "📚 INVESTIGACIÓN Y FUENTES\nasianstudies.org\nhttps://www.asianstudies.org/a\n"
        "↳ En 1961 la estación de Kazalinsk no registró caudal en todo el año.\n\n"
        "ReliefWeb, health in Karakalpakstan (anemia survey)\nhttps://reliefweb.int/r\n"
        "↳ Una encuesta halló una tasa de anemia del 80 al 90 por ciento.\n\n"
        "📍 PERSONAS Y LUGARES\nMoynaq — Hoy a unos 150 kilómetros del agua.\n\n"
        "#AralSea\n\n🤖 Línea de IA.")
    for old, new in changes.items():
        desc = desc.replace(old, new)
    return {"title": "El plan del algodón que funcionó y encogió el mar de Aral", "description": desc}


def test_german_french_and_italian_are_default_languages_alongside_the_first_four():
    assert lv.DEFAULT_LANGS.split(",") == ["es", "pt", "id", "hi", "de", "fr", "it"]
    assert {"de", "fr", "it"} <= set(lv.LANG_NAMES)
    assert lv.LANG_NAMES["it"] == "Italian"


def test_a_template_translation_keeping_citations_and_numbers_passes():
    # 60,000 written 60.000 is the same number.
    assert lv.check_translation(TEMPLATE_SOURCE, _translated()) == []


def test_check_translation_still_guards_numbers_in_findings_and_people():
    lost = lv.check_translation(TEMPLATE_SOURCE, _translated(**{"del 80 al 90": "muy alta"}))
    assert any("lost numbers" in p and "80" in p for p in lost)
    lost = lv.check_translation(TEMPLATE_SOURCE, _translated(**{"unos 150": "muchos"}))
    assert any("lost numbers" in p and "150" in p for p in lost)


def test_a_translated_source_title_is_refused():
    changed = _translated(**{"ReliefWeb, health in Karakalpakstan (anemia survey)":
                             "ReliefWeb, salud en Karakalpakstán (encuesta de anemia)"})
    assert any("source citation" in p for p in lv.check_translation(TEMPLATE_SOURCE, changed))


def test_an_over_budget_translation_sheds_findings_then_people_and_is_checked_on_the_rest():
    padded = _translated(**{"Desaparecieron": "x" * 2400 + " Desaparecieron"})
    fitted = lv.fit_translation(padded, limit=2900)
    assert "↳" not in fitted["description"] and "📍" in fitted["description"]
    # The numbers that left with the findings are not counted against it.
    source = {**TEMPLATE_SOURCE, "description": TEMPLATE_SOURCE["description"].replace(
        "Roughly", "x" * 2400 + " Roughly")}
    assert lv.check_translation(source, fitted) == []
    tighter = lv.fit_translation(padded, limit=2850)
    assert "📍" not in tighter["description"] and "https://reliefweb.int/r" in tighter["description"]


def test_the_description_limit_is_bytes():
    hindi = {"title": "x", "description": "क" * 1700}          # 1700 characters, 5100 bytes
    assert any("5000 bytes" in p for p in lv.check_translation({"title": "x", "description": ""}, hindi))


def test_if_changed_retranslates_a_changed_english_description_and_otherwise_only_missing():
    old_source = {"title": "T", "description": "old description"}
    previous = {"video_id": "V", "source": old_source, "languages": {
        lang: {"metadata": {"title": f"T-{lang}", "description": "d"}} for lang in ("es", "pt", "id", "hi")}}
    wanted = lv.DEFAULT_LANGS.split(",")
    redescribed = {"title": "T", "description": "new template description"}
    langs, note, keep_captions = lv.plan_languages(previous, redescribed, wanted, "V", True)
    assert langs == wanted and "changed" in note
    assert keep_captions is False, "de/fr/it have no subtitle tracks yet"
    langs, note, _ = lv.plan_languages(previous, old_source, wanted, "V", True)
    assert langs == ["de", "fr", "it"], "same English: only the new languages cost a call"
    previous["languages"].update({l: {"metadata": {"title": "x"}} for l in ("de", "fr", "it")})
    langs, note, _ = lv.plan_languages(previous, old_source, wanted, "V", True)
    assert langs == [] and note.startswith("unchanged")
    langs, _, keep_captions = lv.plan_languages(previous, redescribed, wanted, "V", True)
    assert langs == wanted and keep_captions is True
    assert lv.plan_languages(previous, old_source, ["es"], "V", False)[0] == ["es"]


def test_an_older_descriptions_free_form_labels_may_be_translated():
    old = {"title": "T", "description": "📚 SOURCES\nResearch paper:\nhttps://ncbi.nlm.nih.gov/pmc/1\n"}
    translated = {"title": "T", "description": "📚 FUENTES\nArtículo científico:\nhttps://ncbi.nlm.nih.gov/pmc/1\n"}
    assert lv.check_translation(old, translated) == []
