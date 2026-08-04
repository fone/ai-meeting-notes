from meeting_notes.device_names import parse_pactl_descriptions, resolve_device_name


PACTL_SOURCES = """Source #12
    State: RUNNING
    Name: alsa_input.usb-Blue_Yeti.analog-stereo
    Description: Blue Yeti Stereo Analog

Source #13
    Name: alsa_input.pci-0000_00_1f.3.analog-stereo
    Description: Built-in Audio Analog Stereo
"""


def test_parse_pactl_descriptions_returns_internal_name_mapping():
    assert parse_pactl_descriptions(PACTL_SOURCES) == {
        "alsa_input.usb-Blue_Yeti.analog-stereo": "Blue Yeti Stereo Analog",
        "alsa_input.pci-0000_00_1f.3.analog-stereo": "Built-in Audio Analog Stereo",
    }


def test_resolve_device_name_uses_human_description():
    assert resolve_device_name(
        "alsa_input.usb-Blue_Yeti.analog-stereo",
        kind="source",
        runner=lambda _cmd: PACTL_SOURCES,
    ) == "Blue Yeti Stereo Analog"


def test_resolve_device_name_falls_back_without_pactl_or_match():
    assert resolve_device_name(
        "unresolved.monitor",
        kind="sink",
        runner=lambda _cmd: "",
    ) == "unresolved.monitor"
