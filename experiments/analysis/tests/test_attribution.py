import numpy as np
import pytest

from pocketpet_analysis.attribution import UC_PER_MAH, attribute_charge
from pocketpet_analysis.manifest import MarkerMap
from pocketpet_analysis.ppk2 import read_capture

MARKERS = MarkerMap(
    state_channels=(0, 1),
    state_names={0: "sleep", 2: "connected"},
    events={2: "button", 3: "find"},
)


def write_export(path, rows, header="Timestamp(ms),Current(uA),D0-D7"):
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def export_rows(segments, period_ms=1.0):
    """Expand (sample count, current, D0-D7 levels) segments into export rows."""
    rows, index = [], 0
    for count, current, levels in segments:
        for _ in range(count):
            rows.append(f"{index * period_ms:.10g},{current:.3f},{levels}")
            index += 1
    return rows


# 1 kHz samples: 1 s asleep at 10 uA, then 2 s connected at 100 uA with a button press,
# a find request, and 20 ms where both are active.
SEGMENTS = [
    (1000, 10.0, "00000000"),
    (500, 100.0, "01000000"),
    (50, 5100.0, "01100000"),
    (400, 100.0, "01000000"),
    (30, 30100.0, "01010000"),
    (20, 35100.0, "01110000"),
    (1000, 100.0, "01000000"),
]


@pytest.fixture
def capture(tmp_path):
    return write_export(tmp_path / "run.csv", export_rows(SEGMENTS))


def test_background_and_incremental_charge(capture):
    result = attribute_charge(read_capture(capture), MARKERS)

    states = {row["state"]: row for row in result["states"]}
    assert states["sleep"]["background_ua"] == pytest.approx(10.0)
    assert states["sleep"]["duration_s"] == pytest.approx(1.0)
    assert states["connected"]["background_ua"] == pytest.approx(100.0)
    # Background is charged for the whole state, including time under events.
    assert states["connected"]["background_charge_uc"] == pytest.approx(100.0 * 2.0)

    increments = {tuple(row["events"]): row["incremental_charge_uc"] for row in result["events"]}
    assert increments[("button",)] == pytest.approx(5000.0 * 0.050)
    assert increments[("find",)] == pytest.approx(30000.0 * 0.030)
    # The overlap is its own group, so neither event is charged for it twice.
    assert increments[("button", "find")] == pytest.approx(35000.0 * 0.020)

    assert result["event_counts"] == {"button": 2, "find": 1}
    assert result["unattributed_charge_uc"] == pytest.approx(0.0, abs=1e-6)
    assert result["warnings"] == []


def test_total_matches_hand_integration(capture):
    total = attribute_charge(read_capture(capture), MARKERS)["total"]

    expected_uc = sum(count * current for count, current, _ in SEGMENTS) * 1e-3
    assert total["duration_s"] == pytest.approx(3.0)
    assert total["charge_uc"] == pytest.approx(expected_uc)
    assert total["charge_mah"] == pytest.approx(expected_uc / UC_PER_MAH)
    assert total["mean_current_ua"] == pytest.approx(expected_uc / 3.0)


@pytest.mark.parametrize("chunk_rows", [2, 7, 1000, 5000])
def test_result_does_not_depend_on_chunk_size(capture, chunk_rows):
    whole = attribute_charge(read_capture(capture), MARKERS)
    chunked = attribute_charge(read_capture(capture, chunk_rows), MARKERS)

    assert chunked["event_counts"] == whole["event_counts"]
    assert chunked["capture"] == whole["capture"]
    assert chunked["total"] == pytest.approx(whole["total"])
    for chunked_row, whole_row in zip(chunked["states"], whole["states"], strict=True):
        assert chunked_row == pytest.approx(whole_row)


def test_dropped_samples_are_reported_and_not_integrated(tmp_path):
    rows = export_rows([(1000, 50.0, "00000000")])
    del rows[400:600]
    capture = write_export(tmp_path / "gap.csv", rows)

    result = attribute_charge(read_capture(capture), MarkerMap())

    assert result["capture"]["gap_count"] == 1
    assert result["capture"]["gap_s"] == pytest.approx(0.2)
    assert result["total"]["duration_s"] == pytest.approx(0.8)
    assert result["total"]["charge_uc"] == pytest.approx(50.0 * 0.8)


def test_state_without_quiet_samples_has_no_background(tmp_path):
    capture = write_export(
        tmp_path / "busy.csv",
        export_rows([(100, 10.0, "00000000"), (50, 900.0, "01100000")]),
    )

    result = attribute_charge(read_capture(capture), MARKERS)

    connected = next(row for row in result["states"] if row["state"] == "connected")
    assert connected["background_ua"] is None
    assert result["events"][0]["incremental_charge_uc"] is None
    assert len(result["warnings"]) == 1
    # The charge that could not be split stays visible instead of vanishing.
    assert result["unattributed_charge_uc"] == pytest.approx(900.0 * 0.050)


def test_mixed_level_counts_as_high_and_undeclared_code_is_kept(tmp_path):
    capture = write_export(
        tmp_path / "mixed.csv",
        export_rows([(10, 5.0, "00000000"), (1, 5.0, "00X00000"), (10, 5.0, "1-000000")]),
    )

    result = attribute_charge(read_capture(capture), MARKERS)

    assert result["event_counts"]["button"] == 1
    assert result["capture"]["marker_mixed_samples"] == 1
    assert result["capture"]["marker_undriven_samples"] == 10
    assert {row["state"] for row in result["states"]} == {"sleep", "unmapped_1"}


def test_separate_channel_columns_and_missing_logic_columns(tmp_path):
    header = "Timestamp(ms),Current(uA),D0,D1,D2,D3,D4,D5,D6,D7"
    split = write_export(
        tmp_path / "split.csv",
        ["0,10.000,0,1,1,0,0,0,0,0", "1,10.000,0,1,0,0,0,0,0,0", "2,10.000,0,1,0,0,0,0,0,0"],
        header,
    )
    assert attribute_charge(read_capture(split), MARKERS)["event_counts"]["button"] == 1

    bare = write_export(
        tmp_path / "bare.csv", ["0,10.000", "1,30.000"], "Timestamp(ms),Current(uA)"
    )
    assert attribute_charge(read_capture(bare), MarkerMap())["total"][
        "mean_current_ua"
    ] == pytest.approx(20.0)
    with pytest.raises(ValueError, match="no logic columns"):
        attribute_charge(read_capture(bare), MARKERS)


def test_rejects_unusable_exports(tmp_path):
    no_time = write_export(tmp_path / "no_time.csv", ["10.000"], "Current(uA)")
    with pytest.raises(ValueError, match="Timestamp"):
        list(read_capture(no_time))

    backwards = write_export(
        tmp_path / "backwards.csv", ["0,1.000", "2,1.000", "1,1.000"], "Timestamp(ms),Current(uA)"
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        attribute_charge(read_capture(backwards), MarkerMap())

    bad_levels = write_export(tmp_path / "bad.csv", ["0,1.000,0000000Z", "1,1.000,00000000"])
    with pytest.raises(ValueError, match="characters other than"):
        list(read_capture(bad_levels))


def test_sample_period_override(tmp_path):
    capture = write_export(tmp_path / "one.csv", ["0,40.000"], "Timestamp(ms),Current(uA)")

    with pytest.raises(ValueError, match="sample period"):
        attribute_charge(read_capture(capture), MarkerMap())
    result = attribute_charge(read_capture(capture), MarkerMap(), sample_period_s=0.5)
    assert result["total"]["charge_uc"] == pytest.approx(20.0)
    assert np.isclose(result["capture"]["sample_period_s"], 0.5)


def test_crlf_line_endings_parse_like_lf(capture, tmp_path):
    crlf = tmp_path / "crlf.csv"
    lf_bytes = capture.read_bytes().replace(b"\r\n", b"\n")
    crlf.write_bytes(lf_bytes.replace(b"\n", b"\r\n"))

    assert attribute_charge(read_capture(crlf), MARKERS) == attribute_charge(
        read_capture(capture), MARKERS
    )
