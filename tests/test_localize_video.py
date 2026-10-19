"""Localized metadata keeps every number, link and chapter; subtitles keep their timings."""
import json
import os
import sys
import types

import pytest

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


# --- review fixes, 2026-10-15 ---------------------------------------------------------------------

def test_a_chapter_label_starting_with_a_number_is_not_merged_with_its_timestamp():
    # "3:39 150 to 200" read as 39150 failed every translation that moved the 150.
    hippos = {"title": "T", "description": "⏱️ CHAPTERS\n0:00 Four hippos\n3:39 150 to 200 hippos today"}
    spanish = {"title": "T", "description": "⏱️ CAPÍTULOS\n0:00 Cuatro hipopótamos\n"
                                            "3:39 De 150 a 200 hipopótamos hoy"}
    assert lv.check_translation(hippos, spanish) == []
    toads = {"title": "T", "description": "⏱️ CHAPTERS\n0:31 101 Toads Arrive"}
    german = {"title": "T", "description": "⏱️ KAPITEL\n0:31 Ankunft der 101 Kröten"}
    assert lv.check_translation(toads, german) == []
    assert any("150" in p for p in lv.check_translation(
        hippos, {"title": "T", "description": spanish["description"].replace("150", "15")}))


def test_numbers_match_in_any_locale_but_not_a_different_value():
    assert lv.lost_numbers("home to around 1.5 million people", "rund 1,5 Millionen Menschen") == []
    assert lv.lost_numbers("home to around 1.5 million people", "rund 15 Millionen Menschen") == ["1.5"]
    for written in ("60 000", "60.000", "60 000", "60,000"):
        assert lv.lost_numbers("Roughly 60,000 jobs", f"Environ {written} emplois") == [], written
    assert lv.lost_numbers("Roughly 60,000 jobs", "Environ 6.000 emplois") == ["60,000"]
    assert lv.lost_numbers("In 1960, 43,000 tonnes", "En 1960, 43.000 toneladas") == []
    title = {"title": "The 1.5 Million People the Sea Fed", "description": ""}
    assert lv.check_translation(title, {"title": "Die 1,5 Millionen Menschen, die das Meer nährte",
                                        "description": ""}) == []
    assert any("title lost numbers" in p for p in lv.check_translation(
        title, {"title": "Die 15 Millionen Menschen", "description": ""}))


def test_subtitles_in_decimal_comma_languages_keep_their_numbers(monkeypatch):
    cues = [{"index": "19", "time": "00:01:00,000 --> 00:01:03,000",
             "text": "home to around 1.5 million people"},
            {"index": "20", "time": "00:01:03,000 --> 00:01:06,000", "text": "and 60,000 jobs"}]
    replies = {"de": ["Heimat von rund 1,5 Millionen Menschen", "und 60.000 Arbeitsplätze"],
               "fr": ["qui abritait environ 1,5 million de personnes", "et 60 000 emplois"]}
    for lang, texts in replies.items():
        monkeypatch.setattr(lv, "_ask", lambda system, user, schema, t=texts: {"cues": t})
        assert [c["text"] for c in lv.translate_captions(cues, lang)] == texts
    monkeypatch.setattr(lv, "_ask", lambda *a, **k: {"cues": ["rund 15 Millionen", "und 60.000"]})
    try:
        lv.translate_captions(cues, "de")
    except ValueError as exc:
        assert "cue 19 lost a number" in str(exc)
    else:
        raise AssertionError("1.5 written as 15 is a different number")


def test_a_dropped_marker_does_not_excuse_the_section_from_the_number_check():
    # The model replaced "↳" by "→" and changed 80 to 8: the finding is lost, not excused.
    arrow = _translated(**{"↳ Una encuesta halló una tasa de anemia del 80":
                           "→ Una encuesta halló una tasa de anemia del 8"})
    problems = lv.check_translation(TEMPLATE_SOURCE, arrow)
    assert any("lost numbers" in p and "80" in p for p in problems)
    assert any("finding under https://reliefweb.int/r" in p for p in problems)
    assert any("1 '↳' finding lines, not 2" in p for p in problems)
    # The 📍 emoji dropped while 150 became 15.
    pin = _translated(**{"📍 PERSONAS Y LUGARES": "PERSONAS Y LUGARES", "unos 150": "unos 15"})
    problems = lv.check_translation(TEMPLATE_SOURCE, pin)
    assert any("lost the People & Places section" in p for p in problems)
    assert any("lost numbers" in p and "150" in p for p in problems)


def test_a_number_added_to_a_finding_or_people_line_is_refused():
    added = _translated(**{"Hoy a unos 150 kilómetros del agua.":
                           "Hoy a unos 150 kilómetros del agua, abandonado en 1987."})
    assert any("added numbers ['1987']" in p for p in lv.check_translation(TEMPLATE_SOURCE, added))


def _big_template(n=8, people=True):
    """An English template description with n research entries, and its 'translation' (the prose
    doubled, citations and URLs kept), the way a long-prose language comes back."""
    entries_en, entries_tr = [], []
    for i in range(n):
        entries_en.append(f"site{i}.org\nhttps://site{i}.org/paper\n"
                          f"↳ Study {i} counted {100 + i} animals across the basin in {1990 + i}.")
        entries_tr.append(f"site{i}.org\nhttps://site{i}.org/paper\n"
                          f"↳ El estudio {i} contó {100 + i} animales en toda la cuenca en {1990 + i}, "
                          f"según el informe de campo largo y detallado.")
    people_en = "📍 PEOPLE & PLACES IN THIS FILM\nMoynaq — Now about 150 kilometres from the water.\n" \
                "Kazalinsk — The station recorded no discharge in 1961."
    people_tr = "📍 PERSONAS Y LUGARES\nMoynaq — Hoy a unos 150 kilómetros del agua, muy lejos.\n" \
                "Kazalinsk — La estación no registró caudal en 1961, según los datos."
    english = ("Summary of the film, about 60,000 jobs.\n\n⏱️ CHAPTERS\n0:00 Start\n\n"
               "📚 RESEARCH & SOURCES\n" + "\n\n".join(entries_en) + "\n\n"
               + (people_en + "\n\n" if people else "")
               + "Short version: https://youtube.com/shorts/abc\n\n#Tag\n\n🤖 AI line.")
    translated = ("Resumen de la película, unos 60.000 empleos, contado con más palabras.\n\n"
                  "⏱️ CAPÍTULOS\n0:00 Inicio\n\n📚 INVESTIGACIÓN Y FUENTES\n"
                  + "\n\n".join(entries_tr) + "\n\n" + (people_tr + "\n\n" if people else "")
                  + "Versión corta: https://youtube.com/shorts/abc\n\n#Tag\n\n🤖 Línea de IA.")
    return {"title": "T", "description": english}, {"title": "T", "description": translated}


def test_fit_sheds_findings_one_at_a_time_from_the_least_used_source():
    source, translated = _big_template()
    size = len(translated["description"].encode("utf-8"))
    fitted = lv.fit_translation(translated, limit=size - 150)
    removed = fitted["_removed"]
    # Only as many findings as needed, from the end; People & Places and every source stay.
    assert 1 <= len(removed["findings"]) <= 3 and removed["findings"][0] == "https://site7.org/paper"
    assert not removed["people"] and not removed["sources"]
    assert fitted["description"].count("↳") == 8 - len(removed["findings"])
    assert "📍" in fitted["description"]
    assert lv.check_translation(source, fitted) == []


def test_a_hindi_sized_translation_sheds_whole_sources_last_and_still_passes():
    source, translated = _big_template()
    # Everything but the summary, chapters, three entries and the footer has to go.
    fitted = lv.fit_translation(translated, limit=400)
    removed, desc = fitted["_removed"], fitted["description"]
    assert removed["people"] and len(removed["findings"]) == 8
    assert removed["sources"] == ["https://site7.org/paper", "https://site6.org/paper",
                                  "https://site5.org/paper"]
    assert len(desc.encode("utf-8")) <= 400
    assert "https://site4.org/paper" in desc and "Versión corta: https://youtube.com/shorts/abc" in desc
    assert desc.rstrip().endswith("🤖 Línea de IA.") and "0:00 Inicio" in desc
    assert lv.check_translation(source, fitted) == []
    # The checks still hold the entries that remain.
    broken = {**fitted, "description": desc.replace("https://site0.org/paper", "https://site0.org/x")}
    assert any("lost URL https://site0.org/paper" in p for p in lv.check_translation(source, broken))


def test_a_two_line_short_link_is_never_shed_as_a_source():
    source, translated = _big_template(n=2, people=False)
    translated["description"] = translated["description"].replace(
        "Versión corta: https://youtube.com/shorts/abc", "Versión corta:\nhttps://youtube.com/shorts/abc")
    blocks = lv._blocks(translated["description"])
    assert [e["url"] for e in lv.research_entries(blocks)] == [
        "https://site0.org/paper", "https://site1.org/paper"]


def test_a_language_skipped_for_this_english_is_not_retried_until_it_changes():
    source = {"title": "T", "description": "template"}
    previous = {"video_id": "V", "source": source, "languages": {
        "es": {"metadata": {"title": "T-es"}},
        "hi": {"metadata": {"skipped": ["description over 5000 bytes (5200)"]}}}}
    assert lv.plan_languages(previous, source, ["es", "hi"], "V", True)[0] == []
    changed = {"title": "T", "description": "template, edited"}
    assert lv.plan_languages(previous, changed, ["es", "hi"], "V", True)[0] == ["es", "hi"]


def test_a_failed_subtitle_track_is_retried_on_the_next_changed_english_run():
    previous = {"video_id": "V", "source": {"title": "T", "description": "old"}, "languages": {
        "es": {"metadata": {"title": "x"}, "captions": "existing track kept"},
        "de": {"metadata": {"title": "x"}, "captions_error": "ValueError: de: cue 19 lost a number"}}}
    _, _, keep = lv.plan_languages(previous, {"title": "T", "description": "new"}, ["es", "de"], "V", True)
    assert keep is False


class _FakeLocalizeYouTube:
    def __init__(self, description):
        self.snippet = {"title": "T", "description": description, "categoryId": "27",
                        "defaultLanguage": "en"}
        self.updates = []

    def videos(self):
        return self

    def captions(self):
        return self

    def list(self, part, id=None, videoId=None):  # noqa: A002 - the API's names
        class _Call:
            def __init__(self, value):
                self.value = value

            def execute(self):
                return self.value
        if videoId:
            return _Call({"items": []})
        return _Call({"items": [{"id": id, "snippet": dict(self.snippet), "localizations": {}}]})

    def update(self, part, body):
        self.updates.append(body)
        return self

    def execute(self):
        return {}


def _stub_google(monkeypatch, yt):
    monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(load_dotenv=lambda *a, **k: None))
    monkeypatch.setitem(sys.modules, "youtube_upload", types.SimpleNamespace(_creds=lambda ch: None))
    monkeypatch.setitem(sys.modules, "googleapiclient", types.ModuleType("googleapiclient"))
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery",
                        types.SimpleNamespace(build=lambda *a, **k: yt))
    monkeypatch.setitem(sys.modules, "googleapiclient.http",
                        types.SimpleNamespace(MediaIoBaseUpload=None))


def test_a_translation_over_the_byte_limit_is_skipped_without_a_second_call(tmp_path, monkeypatch):
    yt = _FakeLocalizeYouTube("Short English.")
    _stub_google(monkeypatch, yt)
    calls = []
    monkeypatch.setattr(lv, "translate_metadata", lambda title, desc, lang: calls.append(lang) or {
        "title": "T", "description": "क" * 1700})
    assert lv.main(["VID", "--job", str(tmp_path), "--langs", "hi", "--no-captions", "--dry-run"]) == 0
    assert calls == ["hi"], "a size-only failure is not retried"
    record = json.loads((tmp_path / "localizations.json").read_text())
    assert record["languages"]["hi"]["metadata"]["skipped"][0].startswith("description over")
    assert not yt.updates


# --- the pythons film, 2026-10-19 -----------------------------------------------------------------

QUOTED = ("📍 PEOPLE & PLACES IN THIS FILM\nBob McCleery — Robert McCleery, a wildlife ecologist at the "
          "University of Florida, said: \"We want to capture all of the processes that an actual "
          "rabbit would give off.\"")


class _FakeMessages:
    """messages.create that records each request and answers with the next scripted reply."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []

    def create(self, **request):
        self.requests.append(request)
        text, stop = self.replies.pop(0)
        return types.SimpleNamespace(
            stop_reason=stop, usage=types.SimpleNamespace(output_tokens=request["max_tokens"]),
            content=[types.SimpleNamespace(type="thinking", thinking=""),
                     types.SimpleNamespace(type="text", text=text)])


def _fake_client(monkeypatch, *replies):
    messages = _FakeMessages(*replies)
    monkeypatch.setattr(lv, "_client", lambda: types.SimpleNamespace(messages=messages))
    return messages


def test_a_quoted_description_comes_back_through_a_schema_and_keeps_its_quotation(monkeypatch):
    italian = ("📍 PERSONE E LUOGHI IN QUESTO FILM\nBob McCleery — Robert McCleery, ecologo della "
               "fauna selvatica all'Università della Florida, ha detto: \"Vogliamo riprodurre tutti "
               "i processi che emetterebbe un coniglio vero.\"")
    reply = json.dumps({"title": "Perché la Florida costruisce conigli robot?", "description": italian},
                       ensure_ascii=False)
    messages = _fake_client(monkeypatch, (reply, "end_turn"))
    out = lv.translate_metadata("Why Is Florida Building Robot Rabbits?", QUOTED, "it")
    assert out["description"] == italian and '"Vogliamo' in out["description"]
    request = messages.requests[0]
    # The reply is held to this schema, so the API escapes the quotation's quotes itself.
    assert request["output_config"]["format"] == {"type": "json_schema", "schema": lv.METADATA_SCHEMA}
    assert request["max_tokens"] >= 16000
    assert json.loads(request["messages"][0]["content"])["description"] == QUOTED
    assert "four digits" in request["system"]
    assert lv.check_translation({"title": "T", "description": QUOTED},
                                {"title": "T", "description": italian}) == []


def test_a_reply_cut_off_at_max_tokens_is_reported_as_cut_off_not_as_bad_json(monkeypatch):
    # Hindi, 2026-10-19: every output token spent and the description string never closed.
    cut = '{"title": "फ़्लोरिडा रोबोट खरगोश क्यों बना रहा है?", "description": "बर्मीज़ अजगर'
    _fake_client(monkeypatch, (cut, "max_tokens"))
    with pytest.raises(lv.ReplyCutOff, match="max_tokens after 16000 of 16000 output tokens"):
        lv.translate_metadata("T", QUOTED, "hi")


def test_a_language_whose_reply_is_cut_off_twice_is_skipped_and_the_rest_still_go_out(tmp_path, monkeypatch):
    yt = _FakeLocalizeYouTube("Short English.")
    _stub_google(monkeypatch, yt)
    calls = []

    def translate(title, description, lang):
        calls.append(lang)
        if lang == "hi":
            raise lv.ReplyCutOff("reply stopped early: max_tokens after 16000 of 16000 output tokens")
        return {"title": "T-it", "description": "Breve."}
    monkeypatch.setattr(lv, "translate_metadata", translate)
    assert lv.main(["VID", "--job", str(tmp_path), "--langs", "hi,it", "--no-captions"]) == 0
    assert calls == ["hi", "hi", "it"], "a cut-off reply gets the one retry, then the run moves on"
    record = json.loads((tmp_path / "localizations.json").read_text())
    assert record["languages"]["hi"]["metadata"]["skipped"][0].startswith("translation failed: ReplyCutOff")
    assert record["languages"]["it"]["metadata"]["title"] == "T-it"
    [update] = yt.updates
    assert update["localizations"]["it"]["title"] == "T-it" and "hi" not in update["localizations"]


def test_subtitles_are_asked_for_four_digit_years_and_a_shortened_decade_is_still_refused(monkeypatch):
    cues = [{"index": "1", "time": "00:00:00,000 --> 00:00:34,080",
             "text": "Released pets brought them there by the mid-1980s."}]
    asked = []

    def answer(text):
        return lambda system, user, schema: asked.append((system, schema)) or {"cues": [text]}
    monkeypatch.setattr(lv, "_ask", answer("Animali domestici liberati li portarono lì entro la "
                                           "metà degli anni 1980."))
    assert lv.translate_captions(cues, "it")[0]["text"].endswith("anni 1980.")
    system, schema = asked[0]
    assert "four digits" in system and "never 'anni '80'" in system and schema is lv.CUES_SCHEMA
    for kept in ("Mitte der 1980er Jahre", "au milieu des années 1980", "1980 के दशक के मध्य तक",
                 "१९८० के दशक के मध्य तक"):
        assert lv.lost_numbers(cues[0]["text"], kept) == [], kept
    # The check stays strict: the decade written short is a lost number.
    for short in ("entro la metà degli anni '80.", "entro la metà degli anni ottanta."):
        monkeypatch.setattr(lv, "_ask", answer(short))
        with pytest.raises(ValueError, match=r"cue 1 lost a number \['1980'\]"):
            lv.translate_captions(cues, "it")
