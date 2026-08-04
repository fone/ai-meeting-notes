from meeting_notes.app import MeterVisualState, format_dbfs, format_meter_bar


def test_dbfs_display_uses_negative_infinity_below_floor():
    assert format_dbfs(1.0) == "0.0 dBFS"
    assert format_dbfs(0.1) == "-20.0 dBFS"
    assert format_dbfs(0.001) == "-60.0 dBFS"
    assert format_dbfs(0.0009) == "-∞ dBFS"
    assert format_dbfs(0.0) == "-∞ dBFS"


def test_meter_bar_contains_peak_hold_and_clip_latch():
    text = format_meter_bar(level=0.5, hold=0.8, clipped=True)
    assert "│" in text
    assert "CLIP" in text
    assert "-6.0 dBFS" in text


def test_peak_hold_decays_over_about_one_and_a_half_seconds():
    state = MeterVisualState()
    state.observe(1.0, now=0.0)
    state.observe(0.2, now=0.75)
    assert 0.45 <= state.hold <= 0.55
    state.observe(0.2, now=1.6)
    assert state.hold == 0.2


def test_clip_latches_for_three_seconds():
    state = MeterVisualState()
    state.observe(0.99, now=5.0)
    assert state.is_clipped(now=7.9)
    assert not state.is_clipped(now=8.1)


def test_silence_watchdog_requires_fifteen_continuous_seconds():
    state = MeterVisualState()
    assert not state.observe(0.0, now=0.0)
    assert not state.observe(0.0, now=14.9)
    assert state.observe(0.0, now=15.0)
    assert not state.observe(0.0, now=20.0)
    assert not state.observe(0.1, now=21.0)
    assert not state.observe(0.0, now=22.0)
