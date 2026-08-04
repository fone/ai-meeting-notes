import pytest
from textual.app import App
from textual.widgets import Input

from meeting_notes.config import AppConfig
from meeting_notes.settings import SettingsScreen


class SettingsHarness(App):
    pass


@pytest.mark.asyncio
async def test_custom_provider_controls_are_visible_and_mask_key():
    app = SettingsHarness()
    async with app.run_test(size=(100, 32)) as pilot:
        await app.push_screen(
            SettingsScreen(
                AppConfig(
                    ai_provider="custom_openai_compatible",
                    ai_model="gateway/model",
                    custom_provider_name="Team Gateway",
                    custom_base_url="https://gateway.example.test/v1",
                    custom_api_key="secret",
                )
            )
        )
        screen = app.screen
        assert screen.query_one("#custom-provider-name-input", Input).value == "Team Gateway"
        assert screen.query_one("#custom-base-url-input", Input).value == "https://gateway.example.test/v1"
        assert screen.query_one("#custom-model-input", Input).value == "gateway/model"
        assert screen.query_one("#custom-api-key-input", Input).password


@pytest.mark.asyncio
async def test_ollama_cloud_controls_expose_freeform_model_and_mask_key():
    app = SettingsHarness()
    async with app.run_test(size=(100, 32)) as pilot:
        await app.push_screen(
            SettingsScreen(
                AppConfig(
                    ai_provider="ollama_cloud",
                    ai_model="kimi-k2.6",
                    ollama_cloud_api_key="secret",
                )
            )
        )
        screen = app.screen
        assert screen.query_one("#ollama-cloud-model-input", Input).value == "kimi-k2.6"
        assert screen.query_one("#ollama-cloud-key-input", Input).password
