"""Dedicated Bolt Kids end-to-end orchestration on ReelForge's durable runtime.

No explainer script, documentary retention rubric, Nature cadence rule, or silent
fallback participates. Providers are injected in tests; production always uses the
hash-bound manifest and existing ledger. Local partial media is safe to rebuild.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

from . import media
from .assets import resolve_references
from .config import authorize, readiness
from .gates import (GateBook, judge_checks, timing_checks, SCRIPT_CHECKS,
                    IMAGE_CHECKS, ACTION_CHECKS, FINAL_CHECKS)
from .models import canonical_hash, POLICY_VERSION
from .providers import Providers, transcript_match


def _write(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    return str(path)


def _local(runtime,kind,inputs,path,operation):
    request={"version":media.RENDER_VERSION,"kind":kind,"inputs":inputs}
    def call(_key):
        operation()
        return {"local_compute":True},0.0
    runtime.paid_file(stage_key="kids-render:"+canonical_hash(request)[:32],provider="ffmpeg",
                     request=request,estimated_cost=0,output_path=str(path),operation=call)
    return str(path)


def _review(gates,providers,label,payload,required,images=()):
    result=providers.review(label,payload,required,images)
    checks,unavailable=judge_checks(result,required)
    gates.record(label,checks,evidence={"input_sha256":canonical_hash(payload),
        "image_sha256":[media.sha256(p) for p in images],"assessment":result,
        "method":"independent_model_assessment_not_audience_measurement"},unavailable=unavailable)


def _stamp(value):
    millis=round(value*1000); hours,millis=divmod(millis,3600000)
    minutes,millis=divmod(millis,60000); seconds,millis=divmod(millis,1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def render_episode(envelope, expected_sha256, ceiling, output_dir, runtime, *,
                   services=None, resolver=None, check_configuration=True, log=print):
    """Called only by an approved durable job; configuration flags are internal, not API inputs."""
    if runtime is None: raise ValueError("Kids rendering requires a durable approved job")
    episode=authorize(envelope,expected_sha256,ceiling)
    job=runtime.store.get_job(runtime.job_id)
    if not job or float(job["max_cost_usd"])!=float(ceiling):
        raise ValueError("Kids approval ceiling differs from the durable job")
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    spec=episode.model_dump(mode="json")
    spec_hash=canonical_hash(spec)
    gates=GateBook(out,spec_hash)
    providers=services or Providers(runtime,envelope["providers"])
    manifest={"flow":"bolt_kids_v1","policy_version":POLICY_VERSION,"spec_sha256":spec_hash,
              "authorization_sha256":expected_sha256,"providers":envelope["providers"],
              "assets":{},"audio":{},"status":"processing","publishable":False,
              "accounting":"durable provider reservations; invoice settlement not verified"}
    _write(out/"kids_episode.json",spec)
    _write(out/"_state.json",{"production_flow":"bolt_kids_v1","script":spec})

    def checkpoint(label):
        _write(out/"generation_manifest.json",manifest)
        runtime.checkpoint("kids-"+label)

    try:
        log("stage:Kids source and production preflight")
        state=readiness(episode) if check_configuration else {"configured":True,"test_adapter":True}
        gates.record("configuration",{"configured":state["configured"]},evidence=state)
        references=(resolver or resolve_references)(episode,out/"references",runtime.blob)
        gates.record("references",{r.id:media.sha256(references[r.id])==r.sha256 for r in episode.references},
                     evidence={"references":[{"id":r.id,"sha256":r.sha256} for r in episode.references]})
        _review(gates,providers,"script",spec,SCRIPT_CHECKS)
        checkpoint("script-approved")

        log("stage:Kids voices and songs")
        characters={c.id:c for c in episode.characters}
        songs={s.id:s for s in episode.songs}
        audio_dir=out/"audio"; audio_dir.mkdir(exist_ok=True)
        song_paths={}
        # The same chorus is bought and checked once, then reused byte-for-byte in the timeline.
        for song in episode.songs:
            path=audio_dir/(song.id+".mp3")
            if song.reference_id:
                path=Path(references[song.reference_id])
            else:
                providers.song(song,path)
            observed=providers.transcribe(path)
            match=transcript_match(song.lyrics,observed.get("text", ""))
            gates.record("song-"+song.id,{"lyrics_present":match["expected_coverage"]>=.95,
                "no_unrequested_lyrics":match["observed_precision"]>=.95,
                "duration_in_scope":abs(media.probe(path)["duration_sec"]-song.duration_sec)<=1.0},
                evidence={"audio_sha256":media.sha256(path),"transcript":observed,"alignment":match,
                          "method":"ASR_comparison_requires_final_listening_review"})
            song_paths[song.id]=str(path)
            manifest["audio"][song.id]={"sha256":media.sha256(path),"kind":"song","reused":bool(song.reference_id)}
        cue_paths,measured,caption_rows={},{},[]
        for beat in episode.beats:
            for cue in beat.audio:
                raw=None
                if cue.kind=="speech":
                    raw=references[cue.reference_id] if cue.reference_id else str(audio_dir/(cue.id+".mp3"))
                    if not cue.reference_id: providers.speech(cue,characters[cue.character_id],raw)
                    observed=providers.transcribe(raw)
                    match=transcript_match(cue.text,observed.get("text", ""))
                    gates.record("speech-"+cue.id,{"words_present":match["expected_coverage"]>=.95,
                        "no_extra_speech":match["observed_precision"]>=.95},
                        evidence={"audio_sha256":media.sha256(raw),"transcript":observed,"alignment":match})
                elif cue.kind=="song": raw=song_paths[cue.song_id]
                elif cue.kind=="sfx": raw=references[cue.reference_id]
                path=audio_dir/(cue.id+"_mix.wav")
                inputs={"source_sha256":media.sha256(raw) if raw else None,"silence_sec":cue.duration_sec}
                _local(runtime,"normalize-audio",inputs,path,
                       lambda raw=raw,path=path,cue=cue:media.normalized_audio(raw,path,cue.duration_sec))
                cue_paths[cue.id]=str(path)
                measured[cue.id]=media.probe(path)["duration_sec"]
                manifest["audio"][cue.id]={"sha256":media.sha256(path),"kind":cue.kind,
                                          "duration_sec":measured[cue.id]}
        timeline=media.compile_timeline(episode,measured)
        _write(out/"audio_timing_report.json",timeline)
        gates.record("measured-timing",timing_checks(episode,timeline),evidence=timeline)
        ordered_audio=[cue_paths[c["id"]] for c in timeline["cues"]]
        soundtrack=out/"kids_soundtrack.wav"
        _local(runtime,"soundtrack",[media.sha256(p) for p in ordered_audio],soundtrack,
               lambda:media.mix_audio(ordered_audio,soundtrack))
        cue_by_id={c.id:c for b in episode.beats for c in b.audio}
        for row in timeline["cues"]:
            cue=cue_by_id[row["id"]]
            text=cue.text if cue.kind=="speech" else songs[cue.song_id].lyrics if cue.kind=="song" else ""
            if text: caption_rows.append(f"{len(caption_rows)+1}\n{_stamp(row['start_sec'])} --> {_stamp(row['end_sec'])}\n{text}\n")
        (out/"captions.srt").write_text("\n".join(caption_rows),encoding="utf-8")
        (out/"transcript.txt").write_text("\n".join(c.text if c.kind=="speech" else songs[c.song_id].lyrics
            for b in episode.beats for c in b.audio if c.kind in {"speech","song"}),encoding="utf-8")
        checkpoint("audio-approved")

        log("stage:Kids measured storyboard animatic")
        board={"flow":"bolt_kids_v1","timeline":timeline,"beats":[b.model_dump(mode="json") for b in episode.beats]}
        _write(out/"storyboard.json",board)
        from PIL import Image,ImageDraw,ImageFont
        cards=out/"animatic_cards"; cards.mkdir(exist_ok=True)
        shot_specs={s.id:s for b in episode.beats for s in b.shots}
        animatic_parts=[]
        for row in timeline["shots"]:
            shot=shot_specs[row["id"]]
            card=cards/(shot.id+".png")
            image=Image.new("RGB",(1280,720),"#eff8f5")
            draw=ImageDraw.Draw(image)
            import textwrap
            text=f"BOLT KIDS · ANIMATIC\n{row['role'].upper()} / {shot.id}\n\n{shot.visible_action}\n\nSTART: {shot.first_state}\nEND: {shot.last_state}"
            try: font=ImageFont.truetype("DejaVuSans.ttf",30)
            except OSError: font=ImageFont.load_default()
            draw.multiline_text((45,45),"\n".join(textwrap.fill(line,66) for line in text.splitlines()),font=font,fill="#122c38",spacing=10)
            image.save(card)
            path=cards/(shot.id+".mp4")
            seconds=(round(row["end_sec"]*24)-round(row["start_sec"]*24))/24
            _local(runtime,"animatic-shot",{"card":media.sha256(card),"seconds":seconds},path,
                   lambda card=card,path=path,seconds=seconds:media.render_shot(card,path,seconds,motion=False))
            animatic_parts.append(str(path))
        animatic=out/"animatic_preview.mp4"
        _local(runtime,"animatic",{"shots":[media.sha256(p) for p in animatic_parts],"audio":media.sha256(soundtrack)},animatic,
               lambda:media.assemble(animatic_parts,soundtrack,animatic))
        gates.record("animatic-technical",media.technical_report(animatic,timeline)["checks"],
                     evidence={"animatic_sha256":media.sha256(animatic),"scope":"timing_and_audio_not_creative_quality"})
        checkpoint("animatic-approved")

        log("stage:Kids source-image review before motion spending")
        asset_dir=out/"visuals"; asset_dir.mkdir(exist_ok=True)
        worlds={w.id:w for w in episode.worlds}
        resolved_visuals={}
        for asset in episode.assets:
            world=worlds[asset.world_id]
            cast=[characters[c] for c in asset.cast]
            refs=[references[c.reference_id] for c in cast]+[references[world.reference_id]]
            uses=[{"beat_role":b.role,"round_id":b.round_id,"answer":b.answer,
                   **s.model_dump(mode="json")} for b in episode.beats for s in b.shots if s.asset_id==asset.id]
            payload={"asset":asset.model_dump(mode="json"),"uses":uses,
                     "reference_image_order":[c.id for c in cast]+[world.id,"candidate"],
                     "bolt_present":"bolt" in asset.cast,
                     "instruction_for_absent_robot":"When Bolt is intentionally absent, check no unintended robot appears; identity applies to the declared cast."}
            path=Path(references[asset.reference_id]) if asset.reference_id else asset_dir/(asset.id+".png")
            if not asset.reference_id: providers.image(asset,world,cast,refs,path)
            if asset.mode=="motion" and asset.reference_id:
                frame=media.samples(path,media.probe(path)["duration_sec"],asset_dir/(asset.id+"_source"),count=1)[0]
            else: frame=str(path)
            _review(gates,providers,"source-"+asset.id,payload,IMAGE_CHECKS,[*refs,frame])
            resolved_visuals[asset.id]=str(path)
            manifest["assets"][asset.id]={"source_sha256":media.sha256(path),"reused":bool(asset.reference_id),"mode":asset.mode}
        checkpoint("sources-approved")

        log("stage:Kids required actions and motion review")
        for asset in episode.assets:
            if asset.mode!="motion": continue
            path=resolved_visuals[asset.id]
            if not asset.reference_id:
                clip=asset_dir/(asset.id+".mp4")
                providers.motion(asset,path,clip)
                path=str(clip)
            duration=media.probe(path)["duration_sec"]
            maximum=max(s["end_sec"]-s["start_sec"] for s in timeline["shots"] if s["asset_id"]==asset.id)
            gates.record("motion-duration-"+asset.id,{"action_covers_hold":asset.loopable or duration+.05>=maximum},
                         evidence={"duration_sec":duration,"required_sec":maximum,"sha256":media.sha256(path)})
            frames=media.samples(path,min(duration,maximum),asset_dir/(asset.id+"_action"),count=7)
            uses=[s.model_dump(mode="json") for b in episode.beats for s in b.shots if s.asset_id==asset.id]
            _review(gates,providers,"action-"+asset.id,{"asset":asset.model_dump(mode="json"),"uses":uses,
                "sampled_duration_sec":min(duration,maximum),"full_video_verified":False},ACTION_CHECKS,frames)
            resolved_visuals[asset.id]=path
            manifest["assets"][asset.id]["motion_sha256"]=media.sha256(path)
        checkpoint("actions-approved")

        log("stage:Kids final assembly and encoded review")
        assets={a.id:a for a in episode.assets}
        parts=[]
        shot_dir=out/"shots"; shot_dir.mkdir(exist_ok=True)
        for row in timeline["shots"]:
            asset=assets[row["asset_id"]]; source=resolved_visuals[asset.id]
            seconds=(round(row["end_sec"]*24)-round(row["start_sec"]*24))/24
            path=shot_dir/(row["id"]+".mp4")
            _local(runtime,"final-shot",{"source":media.sha256(source),"seconds":seconds,
                "motion":asset.mode=="motion","loopable":asset.loopable},path,
                lambda source=source,path=path,seconds=seconds,asset=asset:media.render_shot(
                    source,path,seconds,motion=asset.mode=="motion",loopable=asset.loopable))
            if row["requires_motion"]:
                trimmed_frames=media.samples(path,media.probe(path)["duration_sec"],
                                              out/("encoded_action_"+row["id"]),count=7)
                _review(gates,providers,"encoded-action-"+row["id"],
                    {"shot":shot_specs[row["id"]].model_dump(mode="json"),
                     "loopable":asset.loopable,"encoded_sha256":media.sha256(path),
                     "scope":"actual trimmed/looped encoded shot, not untrimmed provider video"},
                    ACTION_CHECKS,trimmed_frames)
            parts.append(str(path))
        video=out/"bolt_kids.mp4"
        _local(runtime,"final-mux",{"shots":[media.sha256(p) for p in parts],"audio":media.sha256(soundtrack)},video,
               lambda:media.assemble(parts,soundtrack,video))
        technical=media.technical_report(video,timeline)
        gates.record("encoded-technical",technical["checks"],evidence=technical)
        # At least one actual encoded frame per beat, not a board metadata screenshot.
        final_frames=[]
        for i,beat in enumerate(timeline["beats"]):
            frame=out/f"final_review_{i:02}.jpg"
            media.encode(["-ss",(beat["start_sec"]+beat["end_sec"])/2,"-i",video,
                          "-frames:v","1","-vf","scale=480:-2",frame],30)
            final_frames.append(str(frame))
        _review(gates,providers,"encoded-editorial-sample",{"episode":spec,"timeline":timeline,
            "video_sha256":media.sha256(video),"limitations":"One encoded frame per beat plus prior action samples; full viewing/listening remains mandatory."},
            FINAL_CHECKS,final_frames)
        final={"flow":"bolt_kids_v1","policy_version":POLICY_VERSION,"status":"passed",
               "video_sha256":media.sha256(video),"technical":technical,
               "gate_report_sha256":media.sha256(gates.path),"editorial_status":"pending_full_viewing",
               "publishable":False,"score":None,"audience_engagement":"unmeasured",
               "review_coverage":"sampled_visuals_and_ASR_not_exhaustive","duration_sec":timeline["duration_sec"]}
        _write(out/"kids_quality.json",final)
        thumbnail=out/"thumbnail.jpg"; shutil.copyfile(final_frames[0],thumbnail)
        (out/"description.txt").write_text(episode.title+"\n\n"+episode.learning_goal+
            "\n\nOriginal storybook animal adventure with AI-generated character speech and visuals. "
            "Music: see the saved provenance manifest. Parent/operator audience and disclosure review required before upload.\n",encoding="utf-8")
        manifest["status"]="completed_awaiting_editorial"
        checkpoint("completed")
        spent=float(runtime.store.get_job(runtime.job_id).get("spent_cost_usd") or 0)
        return {"output_path":str(video),"title":episode.title,"script":spec,
                "hook":episode.learning_goal,"scene_count":len(episode.beats),"shot_count":len(timeline["shots"]),
                "video_format":"landscape","visual_style":"bolt_kids","production_flow":"bolt_kids_v1",
                "status":"ok","technical_status":"completed","automated_grade_status":"passed_checks_not_engagement",
                "editorial_status":"pending_full_viewing","promotion_status":"editorial_required","publishable":False,
                "actual_cost":spent,"est_cost":envelope["estimated_cost_usd"],"duration_sec":timeline["duration_sec"],
                "transcript_path":str(out/"transcript.txt"),"srt_path":str(out/"captions.srt"),
                "description_path":str(out/"description.txt"),"thumbnail_path":str(thumbnail),
                "grade_path":str(out/"kids_quality.json"),"rendered_contract_path":str(out/"kids_quality.json"),
                "audio_timing_report_path":str(out/"audio_timing_report.json"),"storyboard_path":str(out/"storyboard.json"),
                "animatic_preview_path":str(animatic),"generation_manifest_path":str(out/"generation_manifest.json"),
                "kids_gate_path":str(gates.path),"kids_spec_path":str(out/"kids_episode.json"),
                "kids_soundtrack_path":str(soundtrack),
                "kids_media_paths":{**{"kids-audio-"+key:value for key,value in cue_paths.items()},
                                    **{"kids-song-"+key:value for key,value in song_paths.items()},
                                    **{"kids-visual-"+key:value for key,value in resolved_visuals.items()}}}
    except BaseException:
        # Preserve fail/unavailable reports before the worker decides recovery eligibility.
        manifest["status"]="stopped_before_next_stage"
        _write(out/"generation_manifest.json",manifest)
        raise
