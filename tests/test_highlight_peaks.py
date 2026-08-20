import numpy as np

from highlights import _find_peaks, _uniform_filter


def test_uniform_filter_matches_scipy_default_boundary_alignment():
    values = np.arange(8, dtype=np.float32)

    result = _uniform_filter(values, size=4)

    np.testing.assert_allclose(
        result,
        np.array([0.5, 0.75, 1.5, 2.5, 3.5, 4.5, 5.5, 6.25], dtype=np.float32),
    )


def test_find_peaks_keeps_tallest_peak_inside_minimum_distance():
    values = np.array([0, 3, 0, 5, 0, 4, 0, 1, 0], dtype=np.float32)

    peaks, heights = _find_peaks(values, min_height=2, min_distance=3)

    np.testing.assert_array_equal(peaks, np.array([3]))
    np.testing.assert_array_equal(heights, np.array([5], dtype=np.float32))


def test_find_peaks_uses_midpoint_for_flat_peak():
    values = np.array([0, 1, 4, 4, 4, 1, 0], dtype=np.float32)

    peaks, heights = _find_peaks(values, min_height=3, min_distance=1)

    np.testing.assert_array_equal(peaks, np.array([3]))
    np.testing.assert_array_equal(heights, np.array([4], dtype=np.float32))
