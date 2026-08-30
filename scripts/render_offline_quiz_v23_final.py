from __future__ import annotations

"""Final wrapper for the deterministic Quiz V2.3 verification render.

The first render proved the visual compositor, but the default replay line was longer than the
3.6-second closing card in the selected local voice. Keep the merged visual contract unchanged and
supply a measured, shorter replay line before invoking the same renderer.
"""

import sys

import quiz_pipeline as qp
import render_offline_quiz_v23 as renderer


_original_install = renderer._install_offline_contract


def _install_with_measured_cta(output_dir):
    _original_install(output_dir)
    qp._legacy.final_reveal_narration = (
        lambda answer: f"{str(answer or '').strip().title()}! Go again."
    )


renderer._install_offline_contract = _install_with_measured_cta


if __name__ == "__main__":
    renderer.main()
