from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one target block, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "_quiz_pipeline_legacy.py",
    '''        # xfade refuses inputs whose timebases differ, and concat hands back 1/1000000 where a
        # single segment is still 1/30. Both sides are normalised rather than one, so the filter
        # is not silently agreeing on whichever timebase happened to arrive first.
        filters.append("".join(labels[:-1]) + f"concat=n={len(specs)-1}:v=1:a=0,settb=AVTB[pre]")
        filters.append(f"{labels[-1]}settb=AVTB[loop]")
''',
    '''        # xfade requires both inputs to be constant-frame-rate with identical frame rate,
        # timebase, resolution and pixel format. concat can advertise an undefined 1/0 frame rate
        # even when every segment was rendered at 30 fps; Vercel's bundled FFmpeg rejects that
        # before encoding frame zero. Reset timestamps first, then let fps establish explicit CFR
        # metadata, and finally put both sides on the same AV timebase.
        filters.append("".join(labels[:-1]) +
                       f"concat=n={len(specs)-1}:v=1:a=0,format=yuv420p,"
                       f"setpts=PTS-STARTPTS,fps={FPS},settb=AVTB[pre]")
        filters.append(f"{labels[-1]}format=yuv420p,setpts=PTS-STARTPTS,"
                       f"fps={FPS},settb=AVTB[loop]")
''',
)

path = Path("tests/test_quiz_render_sequence_errors.py")
text = path.read_text(encoding="utf-8")
addition = '''


def test_loop_xfade_normalizes_both_inputs_to_explicit_cfr(monkeypatch, tmp_path):
    import quiz_pipeline as facade

    legacy = facade._legacy
    captured = {}

    def successful_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(legacy.subprocess, "run", successful_run)
    monkeypatch.setattr(legacy, "_dur", lambda path: 1.0)

    legacy._render_sequence(
        [
            (str(tmp_path / "head.png"), 1.0, False),
            (str(tmp_path / "loop.png"), 0.5, False, {"xfade_prev": 0.4}),
        ],
        str(tmp_path / "out.mp4"),
        1.0,
    )

    command = captured["command"]
    graph = command[command.index("-filter_complex") + 1]
    normalizer = "format=yuv420p,setpts=PTS-STARTPTS,fps=30,settb=AVTB"
    assert f"concat=n=1:v=1:a=0,{normalizer}[pre]" in graph
    assert f"[v1]{normalizer}[loop]" in graph
    assert "[pre][loop]xfade=" in graph
'''
if "test_loop_xfade_normalizes_both_inputs_to_explicit_cfr" in text:
    raise SystemExit("CFR regression test already exists")
path.write_text(text.rstrip() + addition.rstrip() + "\n", encoding="utf-8")

print("Applied explicit-CFR normalization to the quiz loop xfade.")
