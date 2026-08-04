"""Tests for AppConfig: defaults, serialisation, validation."""
from meeting_notes.config import AppConfig, validate_config


def test_default_recording_retention_days():
    """The retention field should default to 30 days (jmalobicky fork)."""
    cfg = AppConfig()
    assert cfg.recording_retention_days == 30


def test_diagnostic_temp_policy_defaults_and_roundtrips():
    """Diagnostic temp audio keeps 72 hours and is capped at 20 GiB by default."""
    cfg = AppConfig()
    assert cfg.diagnostic_temp_retention_hours == 72
    assert cfg.diagnostic_temp_size_cap_gib == 20

    saved = AppConfig.from_dict(
        {
            "diagnostic_temp_retention_hours": 48,
            "diagnostic_temp_size_cap_gib": 8,
        }
    )
    assert saved.diagnostic_temp_retention_hours == 48
    assert saved.diagnostic_temp_size_cap_gib == 8
    assert saved.to_dict()["diagnostic_temp_retention_hours"] == 48
    assert saved.to_dict()["diagnostic_temp_size_cap_gib"] == 8


def test_validate_rejects_negative_diagnostic_temp_policy_values():
    invalid_configs = (
        (AppConfig(ai_provider="none", diagnostic_temp_retention_hours=-1), "diagnostic_temp_retention_hours"),
        (AppConfig(ai_provider="none", diagnostic_temp_size_cap_gib=-1), "diagnostic_temp_size_cap_gib"),
    )
    for cfg, field in invalid_configs:
        ok, error = validate_config(cfg)
        assert not ok
        assert error is not None
        assert field in error


def test_recording_retention_days_can_be_disabled():
    """Setting retention to 0 disables cleanup."""
    cfg = AppConfig.from_dict({"recording_retention_days": 0})
    assert cfg.recording_retention_days == 0


def test_recording_retention_roundtrips_through_dict():
    """to_dict / from_dict should preserve the new field."""
    cfg = AppConfig.from_dict({"recording_retention_days": 7})
    assert cfg.recording_retention_days == 7
    d = cfg.to_dict()
    assert d["recording_retention_days"] == 7
    cfg2 = AppConfig.from_dict(d)
    assert cfg2.recording_retention_days == 7


def test_terminal_file_browser_defaults_to_empty():
    """The terminal_file_browser field (mathstuf #8) defaults to empty string."""
    cfg = AppConfig()
    assert cfg.terminal_file_browser == ""


def test_unknown_keys_in_from_dict_are_ignored():
    """Old/unknown config keys should not crash from_dict."""
    cfg = AppConfig.from_dict({
        "ai_provider": "anthropic",
        "future_field_we_dont_know_about": "value",
    })
    assert cfg.ai_provider == "anthropic"


def test_theme_roundtrips_through_config():
    cfg = AppConfig(theme="dracula")
    assert AppConfig.from_dict(cfg.to_dict()).theme == "dracula"


def test_default_provider_is_anthropic():
    """Sanity check: the default cloud provider hasn't drifted."""
    cfg = AppConfig()
    assert cfg.ai_provider == "anthropic"
    assert cfg.ai_model == "haiku"


def test_validate_rejects_unknown_provider():
    cfg = AppConfig(ai_provider="not-a-real-provider")
    ok, err = validate_config(cfg)
    assert not ok
    assert "ai_provider" in err.lower()


def test_validate_rejects_invalid_anthropic_model():
    cfg = AppConfig(ai_provider="anthropic", ai_model="not-a-real-model",
                    anthropic_api_key="sk-ant-test")
    ok, err = validate_config(cfg)
    assert not ok
    assert "ai_model" in err.lower()


def test_validate_accepts_valid_anthropic_config():
    cfg = AppConfig(ai_provider="anthropic", ai_model="haiku",
                    anthropic_api_key="sk-ant-test")
    ok, err = validate_config(cfg)
    assert ok, f"expected valid, got error: {err}"


def test_validate_none_provider_is_always_valid():
    """ai_provider='none' should validate without any keys."""
    cfg = AppConfig(ai_provider="none")
    ok, err = validate_config(cfg)
    assert ok, err


def test_default_whisper_device_is_cpu():
    """CPU is the safe default — matches README's 'CPU-based' promise and
    avoids broken-CUDA-wheel crashes."""
    cfg = AppConfig()
    assert cfg.whisper_device == "cpu"


def test_validate_rejects_unknown_whisper_device():
    cfg = AppConfig(ai_provider="none", whisper_device="tpu")
    ok, err = validate_config(cfg)
    assert not ok
    assert "whisper_device" in err.lower()


def test_validate_accepts_cuda_and_auto_whisper_devices():
    for device in ("cpu", "cuda", "auto"):
        cfg = AppConfig(ai_provider="none", whisper_device=device)
        ok, err = validate_config(cfg)
        assert ok, f"{device}: {err}"


def test_default_audio_devices_are_empty_strings():
    """Empty string == 'use system default'."""
    cfg = AppConfig()
    assert cfg.mic_device == ""
    assert cfg.system_device == ""


def test_audio_devices_roundtrip():
    cfg = AppConfig.from_dict({
        "mic_device": "alsa_input.usb-X",
        "system_device": "alsa_output.pci-Y",
    })
    assert cfg.mic_device == "alsa_input.usb-X"
    assert cfg.system_device == "alsa_output.pci-Y"
    d = cfg.to_dict()
    assert d["mic_device"] == "alsa_input.usb-X"
    assert d["system_device"] == "alsa_output.pci-Y"


def test_custom_compatible_provider_roundtrips_and_validates():
    cfg = AppConfig(
        ai_provider="custom_openai_compatible",
        ai_model="llama-3.3-70b",
        custom_provider_name="Team Gateway",
        custom_base_url="https://llm.example.test/v1",
        custom_api_key="test-key",
    )
    saved = cfg.to_dict()
    restored = AppConfig.from_dict(saved)
    assert restored.custom_provider_name == "Team Gateway"
    assert restored.custom_base_url == "https://llm.example.test/v1"
    assert restored.ai_model == "llama-3.3-70b"
    ok, error = validate_config(restored)
    assert ok, error


def test_custom_compatible_provider_rejects_bad_endpoint_or_blank_model():
    invalid = (
        AppConfig(ai_provider="custom_openai_compatible", ai_model="model", custom_base_url="not-a-url"),
        AppConfig(ai_provider="custom_openai_compatible", ai_model="", custom_base_url="https://llm.example.test/v1"),
    )
    for cfg in invalid:
        ok, error = validate_config(cfg)
        assert not ok
        assert error


def test_ollama_cloud_requires_key_and_accepts_freeform_model():
    missing_key = AppConfig(ai_provider="ollama_cloud", ai_model="kimi-k2.6")
    ok, error = validate_config(missing_key)
    assert not ok
    assert "OLLAMA_API_KEY" in error

    configured = AppConfig(
        ai_provider="ollama_cloud",
        ai_model="custom-model:latest",
        ollama_cloud_api_key="test-key",
    )
    ok, error = validate_config(configured)
    assert ok, error


def test_to_safe_dict_redacts_keys():
    """API keys must be redacted in the safe dict (used for logging)."""
    cfg = AppConfig(
        anthropic_api_key="sk-ant-supersecretkey12345",
        openai_api_key="sk-openaikey9876543210",
        openrouter_api_key="orkey1234567890",
    )
    safe = cfg.to_safe_dict()
    assert "supersecretkey" not in safe["anthropic_api_key"]
    assert "openaikey" not in safe["openai_api_key"]
    assert "1234567890" not in safe["openrouter_api_key"]
