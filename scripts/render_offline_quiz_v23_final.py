from __future__ import annotations

"""Final wrapper for the deterministic Quiz V2.3 verification render.

The first render proved the visual compositor, but the default replay line was longer than the
3.6-second closing card in the selected local voice. Manual QC also found that the two intermediate
answer callouts exceeded their reveal cards. Keep the merged visual contract unchanged, provide a
measured replay line, and make only those short answer callouts punchier so narration never spills
into the next clue.
"""

import os
from pathlib import Path
import subprocess

import render_offline_quiz_v23 as renderer
import quiz_pipeline as qp


_original_install = renderer._install_offline_contract


def _install_with_measured_audio(output_dir):
    _original_install(output_dir)
    qp._legacy.final_reveal_narration = (
        lambda answer: f"{str(answer or '').strip().title()}! Go again."
    )

    original_tts = qp._legacy.ep.generate_tts
    punchy_answers = {"CAPYBARA!", "OKAPI!"}

    def measured_tts(text: str, output_path: str, voice: str = "echo", **kwargs) -> str:
        rendered = Path(original_tts(text, output_path, voice=voice, **kwargs))
        if str(text or "").strip().upper() not in punchy_answers:
            return str(rendered)

        tightened = rendered.with_name(f"{rendered.stem}.tight{rendered.suffix}")
        subprocess.run(
            [
                qp.FF, "-y", "-v", "error", "-i", str(rendered),
                "-filter:a", "atempo=1.60",
                "-codec:a", "libmp3lame", "-q:a", "2", str(tightened),
            ],
            check=True,
        )
        os.replace(tightened, rendered)
        return str(rendered)

    qp._legacy.ep.generate_tts = measured_tts


renderer._install_offline_contract = _install_with_measured_audio


if __name__ == "__main__":
    renderer.main()
