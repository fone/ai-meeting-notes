#!/usr/bin/env python3
"""Meeting Notes - Lazygit-inspired TUI redesign."""

import sys
import time
import math
import subprocess
import os
import multiprocessing.resource_tracker
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.widgets import Static, Label, ListView, ListItem, Footer, Input, Button, TextArea
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen, ModalScreen
from textual import work

from meeting_notes.recorder import AudioRecorder, list_active_sink_inputs
from meeting_notes.transcriber import WhisperTranscriber
from meeting_notes.note_maker import NoteMaker
from meeting_notes.config import load_config, save_config, AppConfig, validate_config
from meeting_notes.settings import SettingsScreen
from meeting_notes.logger import setup_logging, get_logger
from meeting_notes.level_meter import MicLevelMeter
from meeting_notes.device_names import resolve_device_name
from meeting_notes.recording_notes import (
    read_recording_notes,
    remove_recording_notes,
    write_recording_notes,
)
from meeting_notes.audio_test_screen import AudioTestScreen

# Initialize logging
setup_logging(debug=False)
logger = get_logger(__name__)


_METER_FLOOR = 10 ** (-60 / 20)
_METER_HOLD_SECONDS = 1.5
_METER_CLIP_SECONDS = 3.0
_METER_SILENCE_SECONDS = 15.0
_METER_SILENCE_LEVEL = 0.01


def format_dbfs(level: float) -> str:
    """Format a normalized peak as dBFS, using -∞ below the display floor."""
    level = max(0.0, min(level, 1.0))
    if level < _METER_FLOOR:
        return "-∞ dBFS"
    return f"{max(-60.0, 20 * math.log10(level)):.1f} dBFS"


def format_meter_bar(level: float, hold: float, clipped: bool, width: int = 30) -> str:
    """Build a colored peak bar with a peak-hold marker and dBFS reading."""
    level = max(0.0, min(level, 1.0))
    hold = max(level, min(hold, 1.0))
    filled = int(round(level * width))
    marker = min(width - 1, int(round(hold * (width - 1))))
    cells = ["█" if index < filled else "░" for index in range(width)]
    cells[marker] = "│"
    color = "red" if clipped or level >= 0.89 else "yellow" if level >= 0.5 else "green"
    clip_text = "  [bold red]CLIP[/bold red]" if clipped else ""
    return f"[{color}]{''.join(cells)}[/{color}]  {format_dbfs(level)}{clip_text}"


@dataclass
class MeterVisualState:
    """Small per-stream state machine for meter rendering and warnings."""

    hold: float = 0.0
    hold_at: float = 0.0
    clip_until: float = 0.0
    silence_started: float | None = None
    silence_warned: bool = False

    def observe(self, level: float, *, now: float) -> bool:
        """Update visual state and return True once per continuous silence period."""
        level = max(0.0, min(level, 1.0))
        if level >= self.hold:
            self.hold = level
            self.hold_at = now
        else:
            decay = max(0.0, 1.0 - ((now - self.hold_at) / _METER_HOLD_SECONDS))
            self.hold = max(level, self.hold * decay)
        if level >= 0.98:
            self.clip_until = now + _METER_CLIP_SECONDS
        if level >= _METER_SILENCE_LEVEL:
            self.silence_started = None
            self.silence_warned = False
            return False
        if self.silence_started is None:
            self.silence_started = now
        if not self.silence_warned and now - self.silence_started >= _METER_SILENCE_SECONDS:
            self.silence_warned = True
            return True
        return False

    def is_clipped(self, *, now: float) -> bool:
        return now < self.clip_until


class ActionBar(Horizontal):
    """The recording screen's only command surface."""

    def compose(self) -> ComposeResult:
        yield Button("⏸  Pause  ·  p", id="action-toggle", classes="state-btn recording")
        yield Button("⏹  Stop & Process  ·  s", id="action-stop", classes="primary-btn")
        yield Static("", classes="action-spacer")
        yield Button("⏏  Discard  ·  x", id="action-discard", classes="danger-btn")
        yield Static("Discard recording?", id="discard-confirmation", classes="discard-confirmation")
        yield Button("Yes · y", id="confirm-discard-yes", classes="danger-btn discard-confirmation")
        yield Button("No · n", id="confirm-discard-no", classes="state-btn discard-confirmation")

    def set_state(self, state: str) -> None:
        """Render the parent view's state without owning state itself."""
        confirming = state == "confirming_discard"
        toggle = self.query_one("#action-toggle", Button)
        stop = self.query_one("#action-stop", Button)
        discard = self.query_one("#action-discard", Button)
        confirmation = self.query_one("#discard-confirmation", Static)
        confirm_yes = self.query_one("#confirm-discard-yes", Button)
        confirm_no = self.query_one("#confirm-discard-no", Button)

        toggle.label = "▶  Resume  ·  p" if state == "paused" else "⏸  Pause  ·  p"
        toggle.set_classes("state-btn paused" if state == "paused" else "state-btn recording")
        for widget in (toggle, stop, discard):
            widget.display = not confirming
        for widget in (confirmation, confirm_yes, confirm_no):
            widget.display = confirming

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        view = self.app.query_one(RecordingView)
        button_id = event.button.id
        if button_id == "action-toggle":
            self.app.action_toggle_pause()
        elif button_id == "action-stop":
            self.app.action_stop_recording()
        elif button_id == "action-discard":
            view.request_discard()
        elif button_id == "confirm-discard-yes":
            self.app.action_cancel_recording()
        elif button_id == "confirm-discard-no":
            view.cancel_discard()


class RecordingView(Container):
    """Single-column, state-driven view shown during an active recording."""

    elapsed_time = reactive(0)
    state = reactive("recording")

    def compose(self) -> ComposeResult:
        with Vertical(id="recording-container"):
            with Vertical(id="recording-header"):
                with Horizontal(id="recording-status-line"):
                    yield Static("●  RECORDING", id="recording-status")
                    yield Static("00:00:00", id="recording-timer")
                    yield Static("", id="audio-device-info")
                yield Static("[dim]probing…[/dim]", id="audio-sources-list")
                with Horizontal(id="recording-meter-rows"):
                    with Vertical(classes="meter-row"):
                        yield Static("MIC", id="level-meter-label")
                        yield Static("[dim]waiting…[/dim]", id="level-meter-bar")
                    with Vertical(classes="meter-row"):
                        yield Static("SYS", id="system-level-meter-label")
                        yield Static("[dim]waiting…[/dim]", id="system-level-meter-bar")
            with Horizontal(id="recording-title-strip"):
                yield Static("Meeting title", id="title-label")
                yield Input(placeholder="Optional title…", id="meeting-title-input")
            with Vertical(id="recording-notes-region"):
                yield Static("Notes · [ ] action · ? question · #tag · [MM:SS] marker", id="notes-label")
                yield TextArea(id="user-notes-input")
            yield ActionBar()

    def watch_elapsed_time(self, elapsed: int) -> None:
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.query_one("#recording-timer", Static).update(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    def watch_state(self, state: str) -> None:
        self.remove_class("recording", "paused", "confirming-discard")
        self.add_class(state.replace("_", "-"))
        try:
            status = self.query_one("#recording-status", Static)
            status.update({
                "recording": "●  RECORDING",
                "paused": "⏸  PAUSED",
                "confirming_discard": "●  RECORDING",
            }[state])
            self.query_one(ActionBar).set_state(state)
        except Exception:
            # The initial reactive update can happen before child compose.
            pass

    def on_mount(self) -> None:
        self.watch_state(self.state)
        try:
            self.screen.set_focus(None)
        except Exception:
            pass

    def request_discard(self) -> None:
        self.state = "confirming_discard"
        try:
            self.screen.set_focus(None)
        except Exception:
            pass

    def cancel_discard(self) -> None:
        self.state = "paused" if self.app._is_paused() else "recording"

    def on_key(self, event) -> None:
        if self.state == "confirming_discard":
            if event.key == "y":
                event.prevent_default()
                self.app.action_cancel_recording()
            elif event.key in ("n", "escape"):
                event.prevent_default()
                self.cancel_discard()
            return
        if event.key == "escape":
            try:
                if self._has_focused_input():
                    self.screen.set_focus(None)
                    event.prevent_default()
            except Exception:
                pass
        elif event.key == "s" and not self._has_focused_input():
            event.prevent_default()
            self.app.action_stop_recording()
        elif event.key == "x" and not self._has_focused_input():
            event.prevent_default()
            self.request_discard()
        elif event.key == "p" and not self._has_focused_input():
            event.prevent_default()
            self.app.action_toggle_pause()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "meeting-title-input":
            self._persist_notes_sidecar()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "user-notes-input":
            self._persist_notes_sidecar()

    def _persist_notes_sidecar(self) -> None:
        """Write the current inputs atomically while the recording is live."""
        try:
            title = self.query_one("#meeting-title-input", Input).value
            notes = self.query_one("#user-notes-input", TextArea).text
            self.app.persist_recording_notes(title, notes)
        except Exception:
            logger.debug("Could not persist live recording notes", exc_info=True)

    def _has_focused_input(self) -> bool:
        try:
            title_input = self.query_one("#meeting-title-input", Input)
            notes_input = self.query_one("#user-notes-input", TextArea)
            return title_input.has_focus or notes_input.has_focus
        except Exception:
            return False


class MeetingListItem(ListItem):
    """A single meeting in the list."""
    
    def __init__(self, note_path: Path):
        self.note_path = note_path
        
        # Parse note metadata
        try:
            with open(note_path, 'r') as f:
                content = f.read()
                
            date_line = [l for l in content.split('\n') if l.startswith('date:')]
            time_line = [l for l in content.split('\n') if l.startswith('time:')]
            title_line = [l for l in content.split('\n') if l.startswith('title:')]
            word_count_line = [l for l in content.split('\n') if l.startswith('word_count:')]
            tags_line = [l for l in content.split('\n') if l.startswith('tags:')]
            
            self.date = date_line[0].split(':', 1)[1].strip() if date_line else 'Unknown'
            self.time = time_line[0].split(':', 1)[1].strip().strip('"') if time_line else 'Unknown'
            title = title_line[0].split(':', 1)[1].strip().strip('"') if title_line else note_path.stem
            self.word_count = word_count_line[0].split(':', 1)[1].strip() if word_count_line else '0'
            
            # Parse tags from frontmatter (format: tags: [tag1, tag2])
            if tags_line:
                tags_str = tags_line[0].split(':', 1)[1].strip()
                tags_str = tags_str.strip('[]')
                self.tags = [t.strip() for t in tags_str.split(',') if t.strip() and t.strip() != 'meeting' and t.strip() != 'auto-generated']
            else:
                self.tags = []
            
            self.title = title[:40] + '...' if len(title) > 40 else title
            self.full_title = title  # Store full title for searching
            
        except Exception:
            self.date = 'Unknown'
            self.time = 'Unknown'
            self.title = note_path.stem
            self.full_title = note_path.stem
            self.word_count = '0'
            self.tags = []
        
        # Build label with tags if present
        tags_display = f" [{', '.join(self.tags)}]" if self.tags else ""
        label_text = f"{self.date} {self.time}\n{self.title}{tags_display}\n({self.word_count} words)"
        super().__init__(Label(label_text))
    
    def matches_search(self, query: str) -> bool:
        """Check if this meeting matches the search query."""
        if not query:
            return True
        
        query = query.lower()
        
        # Search in title, date, and tags
        return (
            query in self.full_title.lower() or
            query in self.date.lower() or
            query in self.time.lower() or
            any(query in tag.lower() for tag in self.tags)
        )


class NoteViewer(ScrollableContainer):
    """Display selected meeting note content."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_note = None
        
    def show_note(self, note_path: Path):
        """Display note content."""
        self.current_note = note_path
        
        try:
            with open(note_path, 'r') as f:
                content = f.read()
            
            # Remove frontmatter for cleaner display
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    content = parts[2].strip()
            
            # Strip out "## Full Transcript" section for backwards compatibility with old notes
            if '## Full Transcript' in content:
                content = content.split('## Full Transcript')[0].strip()
                content += "\n\n---\n\n*This is an old format note. The transcript has been hidden. Press 't' to view in a separate window.*"
            
            self.remove_children()
            self.mount(Static(content))
            
        except Exception as e:
            self.remove_children()
            self.mount(Static(f"[red]Error loading note:[/red] {e}"))
    
    def show_empty(self):
        """Show empty state."""
        self.remove_children()
        self.mount(Static("[dim]Select a meeting to view notes\n\nPress 'r' to start recording[/dim]"))


class ManageTagsScreen(ModalScreen[list]):
    """Modal screen for managing meeting tags."""
    
    CSS = """
    ManageTagsScreen {
        align: center middle;
    }
    
    #tags-dialog {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    
    #tags-title {
        text-align: center;
        margin: 1 0;
        color: $text;
    }
    
    #current-tags {
        margin: 1 0;
        color: $text-muted;
    }
    
    #tags-input {
        width: 100%;
        margin: 1 0;
    }
    
    #tags-hint {
        color: $text-muted;
        text-align: center;
        margin: 0 0 1 0;
    }
    
    #tags-buttons {
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    
    .tags-button {
        margin: 0 1;
    }
    """
    
    def __init__(self, current_tags: list, **kwargs):
        super().__init__(**kwargs)
        self.current_tags = current_tags or []
    
    def compose(self) -> ComposeResult:
        with Container(id="tags-dialog"):
            yield Static("🏷️  Manage Tags", id="tags-title")
            
            tags_display = ", ".join(self.current_tags) if self.current_tags else "No tags"
            yield Static(f"Current tags: {tags_display}", id="current-tags")
            
            yield Input(placeholder="Enter tags (comma-separated)...", id="tags-input")
            yield Static("Tip: Use commas to separate multiple tags", id="tags-hint")
            
            with Horizontal(id="tags-buttons"):
                yield Button("Cancel", variant="default", id="cancel-button", classes="tags-button")
                yield Button("Save", variant="primary", id="save-button", classes="tags-button")
    
    def on_mount(self) -> None:
        """Focus the input and populate with current tags."""
        tags_input = self.query_one("#tags-input", Input)
        if self.current_tags:
            tags_input.value = ", ".join(self.current_tags)
        tags_input.focus()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-button":
            tags_text = self.query_one("#tags-input", Input).value.strip()
            if tags_text:
                # Parse comma-separated tags
                tags = [t.strip() for t in tags_text.split(',') if t.strip()]
                self.dismiss(tags)
            else:
                self.dismiss([])
        else:
            self.dismiss(None)
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        tags_text = event.value.strip()
        if tags_text:
            tags = [t.strip() for t in tags_text.split(',') if t.strip()]
            self.dismiss(tags)
        else:
            self.dismiss([])


class TranscriptViewer(ModalScreen):
    """Modal screen for viewing full transcript."""
    
    CSS = """
    TranscriptViewer {
        align: center middle;
    }
    
    #transcript-container {
        width: 90%;
        height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 0;
    }
    
    #transcript-header {
        dock: top;
        width: 100%;
        height: 3;
        background: $primary;
        color: $text;
        content-align: center middle;
        text-style: bold;
        padding: 1 2;
    }
    
    #transcript-content {
        width: 100%;
        height: 1fr;
        border: none;
        padding: 2;
    }
    
    #transcript-path {
        dock: top;
        width: 100%;
        height: 1;
        background: $surface-darken-1;
        color: $text-muted;
        content-align: left middle;
        padding: 0 2;
    }
    
    #transcript-footer {
        dock: bottom;
        width: 100%;
        height: 3;
        background: $surface-darken-1;
        color: $text-muted;
        content-align: center middle;
        padding: 1 2;
    }
    """
    
    def __init__(self, transcript_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.transcript_path = transcript_path
    
    def compose(self) -> ComposeResult:
        """Build the transcript viewer UI."""
        with Container(id="transcript-container"):
            yield Static(f"TRANSCRIPT: {self.transcript_path.stem}", id="transcript-header")
            yield Static(f"📄 {self.transcript_path.absolute()}", id="transcript-path")
            
            try:
                content = self.transcript_path.read_text()
                yield ScrollableContainer(Static(content), id="transcript-content")
            except Exception as e:
                yield Static(f"[red]Error loading transcript:[/red] {e}", id="transcript-content")
            
            yield Static("Press 'Esc' to close  |  Press 'e' to open in editor", id="transcript-footer")
    
    def on_key(self, event) -> None:
        """Handle key events."""
        if event.key == "escape":
            self.dismiss()
        elif event.key == "e":
            self.dismiss()
            # Trigger edit action on parent app
            self.app.action_edit_transcript(self.transcript_path)


class EditTitleScreen(ModalScreen[str]):
    """Modal screen for editing meeting title."""
    
    CSS = """
    EditTitleScreen {
        align: center middle;
    }
    
    #edit-dialog {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    
    #edit-title-label {
        text-align: center;
        margin: 1 0;
        color: $text;
    }
    
    #edit-title-input {
        width: 100%;
        margin: 1 0;
    }
    
    #edit-buttons {
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    
    .edit-button {
        margin: 0 1;
    }
    """
    
    def __init__(self, current_title: str, **kwargs):
        super().__init__(**kwargs)
        self.current_title = current_title
    
    def compose(self) -> ComposeResult:
        with Container(id="edit-dialog"):
            yield Static("✏️  Edit Meeting Title", id="edit-title-label")
            yield Input(value=self.current_title, placeholder="Enter new title...", id="edit-title-input")
            with Horizontal(id="edit-buttons"):
                yield Button("Cancel", variant="default", id="cancel-button", classes="edit-button")
                yield Button("Save", variant="primary", id="save-button", classes="edit-button")
    
    def on_mount(self) -> None:
        """Focus the input when mounted."""
        self.query_one("#edit-title-input", Input).focus()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-button":
            new_title = self.query_one("#edit-title-input", Input).value.strip()
            if new_title:
                self.dismiss(new_title)
            else:
                self.dismiss(None)
        else:
            self.dismiss(None)
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        new_title = event.value.strip()
        if new_title:
            self.dismiss(new_title)


class ConfirmDeleteScreen(ModalScreen):
    """Modal screen for confirming meeting deletion."""
    
    CSS = """
    ConfirmDeleteScreen {
        align: center middle;
    }
    
    #confirm-dialog {
        width: 60;
        height: auto;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    
    #confirm-message {
        text-align: center;
        margin: 1 0;
        color: $text;
    }
    
    #confirm-buttons {
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 1;
    }
    
    .confirm-button {
        margin: 0 1;
    }
    """
    
    def __init__(self, meeting_title: str, **kwargs):
        super().__init__(**kwargs)
        self.meeting_title = meeting_title
    
    def compose(self) -> ComposeResult:
        with Container(id="confirm-dialog"):
            yield Static("⚠️  Delete Meeting?", id="confirm-title")
            yield Static(f'Are you sure you want to delete:\n"{self.meeting_title}"?\n\nThis cannot be undone.', id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", variant="primary", id="cancel-button", classes="confirm-button")
                yield Button("Delete", variant="error", id="delete-button", classes="confirm-button")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "delete-button":
            self.dismiss(True)
        else:
            self.dismiss(False)


class MeetingNotesApp(App):
    """Main application with Lazygit-inspired layout."""
    
    CSS = """
    Screen {
        layout: vertical;
    }
    
    #main-panels {
        layout: horizontal;
        height: 1fr;
    }
    
    #meetings-panel {
        width: 35%;
        height: 100%;
        border: solid $primary;
        padding: 1;
    }
    
    #search-input {
        margin-bottom: 1;
        width: 100%;
    }
    
    #note-panel {
        width: 65%;
        height: 100%;
        border: solid $primary;
        padding: 1;
        margin-left: 1;
    }
    
    /* Recording-screen tokens. Keep this visual system local and inline. */
    $rec-active: $error;
    $rec-paused: $warning;
    $meter-ok: $success;
    $meter-warn: $warning;
    $meter-clip: $error;
    $recording-gutter: 2;

    RecordingView {
        width: 100%;
        height: 1fr;
        padding: 0 $recording-gutter;
        background: $panel;
    }

    RecordingView.recording { border: solid $rec-active; }
    RecordingView.paused { border: solid $rec-paused; }
    RecordingView.confirming-discard { border: solid $rec-active; }

    #recording-container {
        width: 100%;
        height: 1fr;
    }

    #recording-header {
        height: auto;
        padding: 0;
        border-bottom: solid $panel-lighten-1;
    }

    #recording-status-line {
        height: 1;
        width: 100%;
    }

    #recording-status {
        width: 18;
        text-style: bold;
        color: $rec-active;
    }

    RecordingView.paused #recording-status { color: $rec-paused; }

    #recording-timer {
        width: 12;
        text-style: bold;
        color: $text;
    }

    #audio-device-info {
        width: 1fr;
        text-align: right;
        color: $text-muted;
    }

    #audio-sources-list {
        display: none;
        height: auto;
        color: $text-muted;
        padding: 0;
    }

    #recording-meter-rows {
        height: auto;
        width: 100%;
    }

    .meter-row {
        width: 1fr;
        height: 2;
    }

    #level-meter-label,
    #system-level-meter-label {
        width: 5;
        color: $text-muted;
        text-style: bold;
    }

    #level-meter-label.silence-warning,
    #system-level-meter-label.silence-warning {
        color: $meter-warn;
    }

    #level-meter-bar,
    #system-level-meter-bar {
        width: 1fr;
        color: $meter-ok;
    }

    #recording-title-strip {
        height: 3;
        padding: 0;
        border-bottom: solid $panel-lighten-1;
        align: left middle;
    }

    #title-label {
        width: 16;
        color: $text-muted;
    }

    #meeting-title-input {
        width: 1fr;
    }

    #recording-notes-region {
        height: 1fr;
        padding: 0;
    }

    #notes-label {
        height: 1;
        color: $text-muted;
    }

    #user-notes-input {
        width: 100%;
        height: 1fr;
    }

    ActionBar {
        dock: bottom;
        height: 4;
        width: 100%;
        padding: 0;
        background: $surface;
        border-top: solid $panel-lighten-1;
        align: left middle;
    }

    ActionBar Button {
        height: 3;
        min-width: 20;
        margin: 0 1 0 0;
        border: none;
        text-style: bold;
    }

    ActionBar #action-discard,
    ActionBar #confirm-discard-no { margin-right: 0; }
    ActionBar .action-spacer { width: 1fr; }
    ActionBar .state-btn.recording { background: $primary; color: $text; }
    ActionBar .state-btn.paused { background: $success; color: $text; }
    ActionBar .primary-btn { background: $accent; color: $text; }
    ActionBar .danger-btn {
        background: transparent;
        color: $error;
        border: tall $error 35%;
    }
    ActionBar .danger-btn:hover, ActionBar .danger-btn:focus {
        background: $error;
        color: $text;
        border: tall $error;
    }
    ActionBar .discard-confirmation { display: none; }
    #discard-confirmation {
        width: 1fr;
        text-align: right;
        color: $warning;
        text-style: bold;
    }

    .panel-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    
    ListView {
        height: 1fr;
        margin-top: 1;
    }
    
    ListItem {
        padding: 1 0;
    }
    
    ListItem:hover {
        background: $boost;
    }
    
    Footer {
        background: $panel;
    }
    """
    
    BINDINGS = [
        Binding("r", "start_recording", "Record", show=True),
        Binding("s", "stop_recording", "Stop", show=False, priority=True),
        Binding("x", "request_discard", "Discard", show=False, priority=True),
        Binding("p", "toggle_pause", "Pause", show=False, priority=True),
        Binding("y", "confirm_discard", "Confirm Discard", show=False, priority=True),
        Binding("n", "reject_discard", "Keep Recording", show=False, priority=True),
        Binding("o", "open_in_editor", "Open", show=True),
        Binding("c", "copy_to_clipboard", "Copy", show=True),
        Binding("P", "copy_path", "Copy Path", show=True),
        Binding("f", "show_in_folder", "Show in Folder", show=True),
        Binding("d", "delete_meeting", "Delete", show=True),
        Binding("e", "edit_title", "Edit Title", show=True),
        Binding("t", "view_transcript", "Transcript", show=True),
        Binding("T", "manage_tags", "Tags", show=True),
        Binding("comma", "open_settings", "Settings", show=True),
        Binding("A", "audio_test", "Audio Test", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]
    
    def __init__(self, dev_mode: bool = False):
        super().__init__()
        self.dev_mode = dev_mode
        
        # Load configuration
        self.config = load_config()
        
        # Validate config
        valid, error = validate_config(self.config)
        if not valid:
            logger.warning(f"Config validation failed: {error}")
            logger.warning("Using default values for invalid settings")
        
        # Initialize components with config values
        self.recorder: Optional[AudioRecorder] = None
        self.transcriber = WhisperTranscriber(
            self.config.whisper_model,
            device=self.config.whisper_device,
        )
        
        # Get appropriate API key based on provider (check config first, then env vars)
        api_key = None
        if self.config.ai_provider == "openai":
            api_key = self.config.openai_api_key or os.getenv("OPENAI_API_KEY")
        elif self.config.ai_provider == "anthropic":
            api_key = self.config.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        elif self.config.ai_provider == "openrouter":
            api_key = self.config.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
        elif self.config.ai_provider == "ollama_cloud":
            api_key = self.config.ollama_cloud_api_key or os.getenv("OLLAMA_API_KEY")
        
        self.note_maker = NoteMaker(
            output_dir=self.config.notes_dir,
            transcripts_dir=self.config.transcripts_dir,
            ai_provider=self.config.ai_provider,
            ai_model=self.config.ai_model,
            api_key=api_key
        )
        self.notes_dir = Path(self.config.notes_dir).expanduser()
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.is_recording = False
        self.timer_interval = None
        # Refreshes the "audio sources" panel in the recording view so
        # the user can see in real time which apps are routing to the
        # captured sink.
        self._routing_refresh_interval = None
        self.recording_start_time = None
        self._active_recording_path: Optional[Path] = None
        self.all_note_paths = []  # Store all note paths for filtering
        self._level_meter: Optional[MicLevelMeter] = None
        self._system_level_meter: Optional[MicLevelMeter] = None
        # Updates per second from the meter thread are >> our redraw budget.
        # We coalesce to ~10 Hz by tracking the last render timestamp.
        self._last_level_render = 0.0
        self._last_system_level_render = 0.0
        # Peak amplitude seen on each leg during the current recording —
        # logged periodically so we can confirm in the log file that audio
        # was actually flowing. Resets at start_recording time.
        self._peak_mic_level = 0.0
        self._peak_system_level = 0.0
        self._last_peak_log = 0.0
        self._meter_visuals = {
            "mic": MeterVisualState(),
            "system": MeterVisualState(),
        }
        # Whether we've already emitted the "system audio looks silent"
        # warning for this recording session. Without this we'd spam the
        # log every 5 seconds for entire meetings where the user is just
        # talking (e.g. a 1:1 with no screen share). One warning is
        # enough; the level meter bar is the live signal.
        self._warned_silent_system = False
        # Track apps we've already warned about routing to the wrong sink.
        # Cleared at recording start. Prevents notification spam when an
        # app keeps a stream open on a non-captured sink for the whole
        # meeting.
        self._warned_misrouted_apps: set[str] = set()

        # Clean up old recordings on startup
        self._cleanup_old_recordings()

    def _cleanup_old_recordings(self) -> None:
        """Run the configured retention policy against the recordings directory.

        Delegates to the pure ``recording_cleanup`` module so the rules are
        testable without a Textual app instance.
        """
        from meeting_notes.recording_cleanup import CleanupPolicy, cleanup_recordings

        policy = CleanupPolicy(
            normal_retention_days=getattr(self.config, "recording_retention_days", 0),
            temp_retention_hours=getattr(self.config, "diagnostic_temp_retention_hours", 72),
            temp_size_cap_gib=getattr(self.config, "diagnostic_temp_size_cap_gib", 20),
        )
        recordings_dir = Path(self.config.recordings_dir).expanduser()
        removed = cleanup_recordings(recordings_dir, policy)
        if removed:
            logger.info("Startup cleanup removed %d file(s): %s", len(removed), removed)
        else:
            logger.debug("Startup cleanup did not remove any recordings from %s", recordings_dir)

    def persist_recording_notes(self, title: str, notes: str) -> None:
        """Atomically checkpoint live title/notes beside the active recording WAV."""
        if not self.is_recording or self._active_recording_path is None:
            return
        try:
            write_recording_notes(self._active_recording_path, title=title, notes=notes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist recording notes sidecar: %s", exc)

    def _load_final_recording_notes(self, title: str | None, notes: str) -> tuple[str | None, str]:
        """Flush and read the durable sidecar before handing notes to processing."""
        if self._active_recording_path is None:
            return title, notes
        self.persist_recording_notes(title or "", notes)
        try:
            snapshot = read_recording_notes(self._active_recording_path)
            return snapshot.title.strip() or None, snapshot.notes
        except (FileNotFoundError, ValueError) as exc:
            logger.warning("Could not reload recording notes sidecar: %s", exc)
            return title, notes

    def compose(self) -> ComposeResult:
        """Build the UI."""
        # Main content area
        with Container(id="main-panels"):
            # Meetings list panel
            with Vertical(id="meetings-panel"):
                yield Static("Meeting Notes", classes="panel-title")
                yield Input(placeholder="Search meetings...", id="search-input")
                yield ListView(id="meetings")
            
            # Note viewer panel  
            with Vertical(id="note-panel"):
                yield Static("Note Preview", classes="panel-title")
                yield NoteViewer(id="note-viewer")
        
        # Footer with keyboard shortcuts
        yield Footer()
    
    def on_mount(self) -> None:
        """Initialize app on mount."""
        logger.info("Initializing Meeting Notes app")
        logger.info(f"Config: {self.config.to_safe_dict()}")
        logger.debug(f"Dev mode: {self.dev_mode}")
        
        self.title = "Meeting Notes"
        self.sub_title = "Keyboard-driven meeting recorder"
        self.load_meetings()
        
        # Initialize recorder with config
        logger.info(f"Initializing audio recorder (mode: {self.config.recording_mode})")
        self.recorder = AudioRecorder(
            output_dir=self.config.recordings_dir,
            mode=self.config.recording_mode,
            dev_mode=self.dev_mode,
            mic_device=self.config.mic_device or None,
            system_device=self.config.system_device or None,
        )
        
        # Clear status file on startup
        self._write_status_file("idle")
        
        # Show empty state
        viewer = self.query_one("#note-viewer", NoteViewer)
        viewer.show_empty()
        
        # Focus on the meetings list instead of search input
        try:
            meetings_list = self.query_one("#meetings", ListView)
            meetings_list.focus()
        except Exception as e:
            logger.warning(f"Could not focus on meetings list: {e}")
    
    def on_unmount(self) -> None:
        """Cleanup when app exits."""
        # Kill any active recording to clean up processes. We use
        # cancel_recording rather than stop_recording so we don't leave a
        # background ffmpeg mix running after the TUI is gone.
        if self.recorder and self.recorder.is_recording():
            try:
                self.recorder.cancel_recording()
            except Exception:
                pass  # Ignore errors during shutdown

        # Stop timer if running
        if self.timer_interval:
            try:
                self.timer_interval.stop()
            except Exception:
                pass

        if self._routing_refresh_interval:
            try:
                self._routing_refresh_interval.stop()
            except Exception:
                pass

        # Always stop the level meter on shutdown so its parec subprocess
        # doesn't outlive the TUI.
        self._stop_level_meter()
    
    def load_meetings(self):
        """Load meeting notes from disk."""
        notes = sorted(
            self.notes_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        # Store all note paths
        self.all_note_paths = list(notes)
        
        # Apply current search filter
        self.filter_meetings()
    
    def filter_meetings(self, query: str = ""):
        """Filter meetings based on search query."""
        try:
            meeting_list = self.query_one("#meetings", ListView)
        except Exception:
            return  # ListView not mounted yet
        
        meeting_list.clear()
        
        if not self.all_note_paths:
            meeting_list.append(ListItem(Label("[dim]No meetings yet\nPress 'r' to record[/dim]")))
            return
        
        # Filter meetings by query - create fresh MeetingListItem for each check
        filtered_paths = []
        for note_path in self.all_note_paths:
            # Create temporary item to check if it matches
            temp_item = MeetingListItem(note_path)
            if temp_item.matches_search(query):
                filtered_paths.append(note_path)
        
        if not filtered_paths:
            meeting_list.append(ListItem(Label(f"[dim]No meetings match '{query}'[/dim]")))
        else:
            # Create fresh MeetingListItem instances for display
            for note_path in filtered_paths:
                meeting_list.append(MeetingListItem(note_path))
    
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle meeting selection."""
        if isinstance(event.item, MeetingListItem):
            viewer = self.query_one("#note-viewer", NoteViewer)
            viewer.show_note(event.item.note_path)
    
    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes."""
        if event.input.id == "search-input":
            self.filter_meetings(event.value)
    
    def _write_status_file(self, status: str, title: str = "", duration: str = "") -> None:
        """Write status file for Waybar integration.
        
        Args:
            status: One of "idle", "recording", "processing"
            title: Optional meeting title (for recording status)
            duration: Optional duration string like "05:42" (for recording status)
        """
        try:
            status_file = Path(__file__).parent.parent / ".status"
            with open(status_file, 'w') as f:
                f.write(f'STATUS="{status}"\n')
                if title:
                    f.write(f'TITLE="{title}"\n')
                if duration:
                    f.write(f'DURATION="{duration}"\n')
        except Exception as e:
            logger.warning(f"Failed to write status file: {e}")
    
    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Control which actions are available based on recording state."""
        if action == "start_recording":
            return not self.is_recording
        elif action in ["stop_recording", "request_discard", "cancel_recording"]:
            return self.is_recording
        elif action == "audio_test":
            # Hide from the footer while recording — running the test mid-meeting
            # would fight the recorder for the same source.
            return not self.is_recording
        if action in {
            "open_in_editor", "copy_to_clipboard", "copy_path", "show_in_folder",
            "delete_meeting", "edit_title", "view_transcript", "manage_tags",
        }:
            # These operate on a completed meeting and are inert mid-recording.
            return not self.is_recording
        return True  # Settings and Quit remain available while recording
    
    def update_recording_timer(self) -> None:
        """Called every second to update recording timer.

        While paused, the timer does not advance.  The total paused duration
        reported by the recorder is subtracted from the wall-clock elapsed
        time so the displayed and persisted duration reflect only active
        recording time.
        """
        if self.is_recording and self.recording_start_time:
            elapsed = int(time.time() - self.recording_start_time - self._paused_duration())
            elapsed = max(elapsed, 0)
            duration_str = f"{elapsed // 60:02d}:{elapsed % 60:02d}"

            # Update status file with current duration
            status = "paused" if self._is_paused() else "recording"
            self._write_status_file(status, duration=duration_str)

            try:
                recording_view = self.query_one(RecordingView)
                recording_view.elapsed_time = elapsed
            except Exception:
                pass  # View might not be mounted yet

    def _is_paused(self) -> bool:
        """Return True if the recorder is currently paused."""
        return bool(self.recorder and self.recorder.is_paused())

    def _paused_duration(self) -> float:
        """Return total seconds the current recording has been paused."""
        return self.recorder.get_paused_duration() if self.recorder else 0.0

    def _render_routing_block(self, widget: Static, lines: list[str]) -> None:
        """Collapse healthy routing status; show only actionable routing warnings."""
        if lines:
            widget.update("\n".join(lines))
            widget.display = True
        else:
            widget.update("")
            widget.display = False

    def update_audio_sources_panel(self) -> None:
        """Refresh the 'Audio sources' panel with what's currently playing.

        Pulls `pactl list sink-inputs`, filters to the sink we're recording,
        and shows app names. If nothing is routing to our sink, we say so
        loudly — that's the user-actionable signal that the system-audio
        leg won't capture other meeting participants.

        This refresh is skipped while paused: no audio is being captured,
        so routing updates would show stale or misleading activity.
        """
        if not self.is_recording or self.recorder is None or self._is_paused():
            return

        try:
            recording_view = self.query_one(RecordingView)
            widget = recording_view.query_one("#audio-sources-list", Static)
        except Exception:
            return

        try:
            target_sink = self.recorder.resolved_system_sink
            active = list_active_sink_inputs(include_corked=False)
            on_target = []
            elsewhere = []
            # active sink-inputs reference sinks by numeric index;
            # we need to map to names to compare against the target.
            from meeting_notes.recorder import _sink_index_to_name

            idx_to_name = _sink_index_to_name()
            for si in active:
                sink_name = idx_to_name.get(si.sink, si.sink)
                label = si.application or si.media_name or "?"
                if target_sink and sink_name == target_sink:
                    on_target.append(label)
                else:
                    elsewhere.append((label, sink_name))

            lines = []
            if not on_target:
                lines.append(
                    "[yellow]⚠ Nothing routing to the captured sink right now[/yellow]"
                )
            if elsewhere:
                # Surface mis-routed audio so the user can fix it on the fly
                pairs = ", ".join(
                    f"{app} → {sink}" for app, sink in elsewhere[:3]
                )
                lines.append(f"[red]Playing elsewhere:[/red] {pairs}")
            self._render_routing_block(widget, lines)

            # Surface a TOAST notification when a meeting-style app appears
            # on a non-captured sink for the first time. This is the
            # high-stakes moment: "Zoom just opened on your laptop speakers
            # instead of the Scarlett — your system audio is silent right
            # now". We only fire once per app per recording session so we
            # don't spam the user.
            _MEETING_APP_HINTS = (
                "zoom", "meet", "chrome", "chromium", "firefox", "teams",
                "slack", "discord", "skype", "webex", "jitsi",
            )
            for app, sink_name in elsewhere:
                if app in self._warned_misrouted_apps:
                    continue
                app_l = app.lower()
                if not any(h in app_l for h in _MEETING_APP_HINTS):
                    continue
                self._warned_misrouted_apps.add(app)
                msg = (
                    f"⚠ {app} just started playing on {sink_name} — "
                    f"you're capturing {target_sink}. "
                    f"This audio will NOT be in your meeting notes."
                )
                logger.warning(f"misrouted-app alert: {msg}")
                try:
                    self.notify(msg, severity="warning", timeout=12)
                except Exception:
                    pass

            # Also log so we have an audit trail after the recording finishes
            logger.info(
                f"audio sources @ {int(time.time() - (self.recording_start_time or 0))}s: "
                f"on_target={on_target!r}, elsewhere={elsewhere!r}, "
                f"target_sink={target_sink!r}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"update_audio_sources_panel failed: {exc}")

    def _format_level_bar(self, level: float, stream: str, now: float) -> tuple[str, bool, bool]:
        """Update one stream's presentation state and return meter text + silence state."""
        visual = self._meter_visuals[stream]
        warn_silence = visual.observe(level, now=now)
        return (
            format_meter_bar(level, visual.hold, visual.is_clipped(now=now)),
            warn_silence,
            visual.silence_warned,
        )

    def _set_meter_label(self, stream: str, *, silent: bool) -> None:
        """Reflect the existing silence latch in its meter label without touching capture."""
        label_id = "#level-meter-label" if stream == "mic" else "#system-level-meter-label"
        normal = "MIC" if stream == "mic" else "SYS"
        try:
            label = self.query_one(RecordingView).query_one(label_id, Static)
            label.update(f"{normal} SILENT?" if silent else normal)
            label.set_class(silent, "silence-warning")
        except Exception:
            pass

    def _notify_silent_stream(self, stream: str) -> None:
        label = "Microphone" if stream == "mic" else "System audio"
        message = f"⚠ {label} has been silent for 15 seconds. Check your audio routing."
        logger.warning("level-meter[%s]: %s", stream, message)
        try:
            self.notify(message, severity="warning", timeout=12)
        except Exception:
            pass

    def _maybe_log_peaks(self) -> None:
        """Once every ~5s, log the running peak levels so the file log can
        confirm audio was actually flowing during a recording. This is what
        makes 'I recorded for 12 minutes and only my voice came through'
        diagnosable after the fact."""
        now = time.monotonic()
        if now - self._last_peak_log < 5.0:
            return
        self._last_peak_log = now
        logger.info(
            f"level-meter peaks (rolling 5s window): "
            f"mic={self._peak_mic_level * 100:.0f}%, "
            f"system={self._peak_system_level * 100:.0f}%"
        )
        # Reset rolling peaks for the next window
        self._peak_mic_level = 0.0
        self._peak_system_level = 0.0

    def _render_level(self, level: float) -> None:
        """Render the mic level-meter bar. Called from the meter thread."""
        if level > self._peak_mic_level:
            self._peak_mic_level = level
        self._maybe_log_peaks()

        now = time.monotonic()
        if self._is_paused() or now - self._last_level_render < 0.08:
            return
        self._last_level_render = now
        text, warn_silence, silent = self._format_level_bar(level, "mic", now)

        def _update():
            try:
                view = self.query_one(RecordingView)
                view.query_one("#level-meter-bar", Static).update(text)
                self._set_meter_label("mic", silent=silent)
                if warn_silence:
                    self._notify_silent_stream("mic")
            except Exception:
                pass  # view torn down; meter will be stopped shortly

        try:
            self.call_from_thread(_update)
        except Exception:
            pass

    def _render_system_level(self, level: float) -> None:
        """Render the system-audio level-meter bar. Called from the meter thread."""
        if level > self._peak_system_level:
            self._peak_system_level = level
        self._maybe_log_peaks()

        now = time.monotonic()
        if self._is_paused() or now - self._last_system_level_render < 0.08:
            return
        self._last_system_level_render = now
        text, warn_silence, silent = self._format_level_bar(level, "system", now)

        def _update():
            try:
                view = self.query_one(RecordingView)
                view.query_one("#system-level-meter-bar", Static).update(text)
                self._set_meter_label("system", silent=silent)
                if warn_silence:
                    self._notify_silent_stream("system")
            except Exception:
                pass

        try:
            self.call_from_thread(_update)
        except Exception:
            pass

    def _start_level_meter(self) -> None:
        """Start both the mic and system-audio level meters and reset peaks."""
        self._peak_mic_level = 0.0
        self._peak_system_level = 0.0
        self._last_peak_log = time.monotonic()
        self._meter_visuals = {
            "mic": MeterVisualState(),
            "system": MeterVisualState(),
        }
        if self._level_meter is None and self.config.recording_mode in ("mic", "combined"):
            device = self.config.mic_device or None
            logger.info(f"level-meter[mic]: starting on device={device or 'default'}")
            meter = MicLevelMeter(on_level=self._render_level, device=device)
            if not meter.is_available():
                logger.warning(
                    "level-meter[mic]: unavailable (no parec/pw-record); skipping"
                )
            else:
                meter.start()
                self._level_meter = meter

        # System-audio meter: reads from the SAME monitor source the recorder is
        # using, so the user sees exactly what's being captured to disk.
        if (
            self._system_level_meter is None
            and self.config.recording_mode in ("system", "combined")
            and self.recorder is not None
        ):
            sink = self.recorder.resolved_system_sink or self.config.system_device or None
            monitor = None
            if sink:
                monitor = f"{sink}.monitor"
            logger.info(
                f"level-meter[system]: starting on sink={sink!r}, monitor={monitor!r}"
            )
            sys_meter = MicLevelMeter(on_level=self._render_system_level, device=monitor)
            if not sys_meter.is_available():
                logger.warning(
                    "level-meter[system]: unavailable (no parec/pw-record); skipping"
                )
            else:
                sys_meter.start()
                self._system_level_meter = sys_meter

    def _stop_level_meter(self) -> None:
        """Stop both level meters and log the final peaks."""
        # Final peak log so we have something even if we never hit the 5s window
        logger.info(
            f"level-meter: final peaks "
            f"mic={self._peak_mic_level * 100:.0f}%, "
            f"system={self._peak_system_level * 100:.0f}%"
        )
        for attr in ("_level_meter", "_system_level_meter"):
            meter = getattr(self, attr, None)
            if meter is not None:
                try:
                    meter.stop()
                    logger.debug(f"level-meter: stopped {attr}")
                except Exception as exc:
                    logger.debug(f"level-meter: error stopping {attr}: {exc}")
                setattr(self, attr, None)

    async def action_start_recording(self) -> None:
        """Start recording and switch to full-screen recording view."""
        logger.info(
            f"action_start_recording: mode={self.config.recording_mode}, "
            f"mic_device={self.config.mic_device!r}, "
            f"system_device={self.config.system_device!r}"
        )
        if self.recorder and not self.recorder.is_recording():
            try:
                # Start the actual recorder FIRST. If it fails (bad device,
                # missing tool, busy hardware) we want to surface the error
                # without having torn down the main UI.
                self.recorder.start_recording()
                self.is_recording = True
                self.recording_start_time = time.time()
                self._active_recording_path = getattr(self.recorder, "current_file", None)
                self.persist_recording_notes("", "")
                # Reset mid-recording warning state for this session
                self._warned_misrouted_apps = set()
                self._warned_silent_system = False
                logger.info(
                    f"action_start_recording: recorder running, "
                    f"resolved_system_sink={self.recorder.resolved_system_sink!r}"
                )

                # Now swap UI to recording view
                main_panels = self.query_one("#main-panels", Container)
                main_panels.display = False
                recording_view = RecordingView()
                await self.mount(recording_view)

                # Update status file for Waybar
                self._write_status_file("recording", duration="00:00")

                # Get and display audio device info
                device_info = self.recorder.get_audio_device_info()
                logger.info(f"action_start_recording: device_info={device_info}")
                mode_display = {
                    'mic': '🎤 Microphone Only',
                    'system': '🔊 System Audio Only',
                    'combined': '🎤🔊 Microphone + System Audio'
                }
                info_lines = [mode_display.get(device_info['mode'], device_info['mode'])]

                if 'mic_device' in device_info:
                    mic_device = device_info['mic_device']
                    info_lines.append(
                        f"Mic: {resolve_device_name(mic_device, kind='source')}"
                    )
                if 'system_device' in device_info:
                    system_device = self.recorder.resolved_system_sink or device_info['system_device']
                    info_lines.append(
                        f"System: {resolve_device_name(system_device, kind='sink')}"
                    )
                
                audio_info_text = '\n'.join(info_lines)
                audio_info_widget = recording_view.query_one("#audio-device-info", Static)
                audio_info_widget.update(audio_info_text)
                
                # Start timer updates (every 1 second)
                self.timer_interval = self.set_interval(1.0, self.update_recording_timer)

                # Start the live level meters (mic + system audio).
                # Real-time visual feedback that audio is actually arriving
                # — and CRUCIALLY that system-audio capture isn't silent.
                self._start_level_meter()

                # Refresh the "what is playing right now" list every 3 seconds
                # so the user can see when meeting participants start/stop
                # being captured.
                self._routing_refresh_interval = self.set_interval(
                    3.0, self.update_audio_sources_panel
                )
                self.update_audio_sources_panel()  # populate immediately

                # Update footer bindings
                self.refresh_bindings()

                # Wire the recording view's pause state to the recorder so
                # the UI stays consistent if we launch already paused.
                try:
                    recording_view = self.query_one(RecordingView)
                    recording_view.state = "paused" if self._is_paused() else "recording"
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"Failed to start recording: {e}", exc_info=True)
                self.notify(f"Failed to start recording: {e}", severity="error")
                self.is_recording = False
                # Restore main panels if something failed
                try:
                    main_panels = self.query_one("#main-panels", Container)
                    main_panels.display = True
                except Exception:
                    pass

    def action_toggle_pause(self) -> None:
        """Toggle pause/resume on the active recording."""
        if not self.is_recording or not self.recorder or not self.recorder.is_recording():
            return

        try:
            if self.recorder.is_paused():
                self.recorder.resume_recording()
                # The meter subprocesses were stopped on pause so nothing
                # continues sampling while the recording is halted.
                self._start_level_meter()
                logger.info("Recording resumed from pause")
                self.notify("Recording resumed", severity="information")
            else:
                self.recorder.pause_recording()
                # Do not leave diagnostic meter processes capturing in the
                # background while the user believes recording is paused.
                self._stop_level_meter()
                logger.info("Recording paused")
                self.notify("Recording paused", severity="warning")

            try:
                recording_view = self.query_one(RecordingView)
                recording_view.state = "paused" if self.recorder.is_paused() else "recording"
            except Exception:
                pass

            # Update the status file immediately so Waybar reflects the state.
            self.update_recording_timer()
        except Exception as e:
            logger.error(f"Failed to toggle pause: {e}", exc_info=True)
            self.notify(f"Failed to pause/resume: {e}", severity="error")

    def action_request_discard(self) -> None:
        """Show the in-view discard confirmation without destroying the recording."""
        if not self.is_recording:
            return
        try:
            self.query_one(RecordingView).request_discard()
        except Exception:
            logger.debug("Discard requested before recording view mounted")

    def action_confirm_discard(self) -> None:
        """Confirm discard only while its inline confirmation is visible."""
        try:
            view = self.query_one(RecordingView)
            if view.state == "confirming_discard":
                self.action_cancel_recording()
        except Exception:
            pass

    def action_reject_discard(self) -> None:
        """Return from inline discard confirmation to the active recording."""
        try:
            view = self.query_one(RecordingView)
            if view.state == "confirming_discard":
                view.cancel_discard()
        except Exception:
            pass

    def action_cancel_recording(self) -> None:
        """Cancel recording and discard without processing."""
        logger.info("Cancelling recording")
        if not self.is_recording or not self.recorder:
            return
        
        try:
            # Stop timer + level meter + routing refresh
            if self.timer_interval:
                self.timer_interval.stop()
                self.timer_interval = None
            if self._routing_refresh_interval:
                self._routing_refresh_interval.stop()
                self._routing_refresh_interval = None
            self._stop_level_meter()

            # Discard recording (kills processes, deletes files, no ffmpeg mix)
            self.recorder.cancel_recording()
            if self._active_recording_path is not None:
                remove_recording_notes(self._active_recording_path)
                self._active_recording_path = None
            self.is_recording = False
            self.recording_start_time = None
            logger.info("Recording cancelled successfully")
            
            # Update status back to idle
            self._write_status_file("idle")
            
            # Remove recording view
            try:
                recording_view = self.query_one(RecordingView)
                recording_view.remove()
            except Exception:
                pass
            
            # Show main panels
            main_panels = self.query_one("#main-panels", Container)
            main_panels.display = True
            
            # Update footer bindings
            self.refresh_bindings()
            
            # Notify user
            self.notify("Recording cancelled", severity="warning")
            
        except Exception as e:
            logger.error(f"Failed to cancel recording: {e}", exc_info=True)
            self.notify(f"Failed to cancel recording: {e}", severity="error")
    
    def action_stop_recording(self) -> None:
        """Stop recording, get title if provided, and process."""
        logger.info("Stopping recording")
        if self.recorder and self.recorder.is_recording():
            try:
                # Get meeting title if provided
                meeting_title = None
                user_notes = ""
                try:
                    recording_view = self.query_one(RecordingView)
                    title_input = recording_view.query_one("#meeting-title-input", Input)
                    meeting_title = title_input.value.strip() if title_input.value else None
                    if meeting_title:
                        logger.info(f"Meeting title: {meeting_title}")
                    
                    # Get user notes from text area
                    notes_input = recording_view.query_one("#user-notes-input", TextArea)
                    user_notes = notes_input.text.strip() if notes_input.text else ""
                    if user_notes:
                        logger.info(f"User notes captured: {len(user_notes)} characters")
                except Exception:
                    pass  # No title input found

                meeting_title, user_notes = self._load_final_recording_notes(meeting_title, user_notes)
                
                # Stop timer + level meter + routing refresh
                if self.timer_interval:
                    self.timer_interval.stop()
                    self.timer_interval = None
                if self._routing_refresh_interval:
                    self._routing_refresh_interval.stop()
                    self._routing_refresh_interval = None
                self._stop_level_meter()

                # If the user pauses right before hitting stop, the recorder
                # internally resumes children so WAV headers flush.  Mark the
                # UI unpaused too so the elapsed timer includes the final
                # burst accurately and the view shows RECORDING briefly.
                try:
                    recording_view = self.query_one(RecordingView)
                    recording_view.state = "recording"
                except Exception:
                    pass

                # Stop recording
                audio_path = self.recorder.stop_recording()
                self.is_recording = False
                self.recording_start_time = None
                logger.info(f"Recording stopped. Audio saved to: {audio_path}")

                # Surface per-leg silence warnings BEFORE the user navigates
                # away. This is the bug that ate James' first real meeting:
                # silent system-audio leg → transcript only has his voice.
                if getattr(self.recorder, "last_system_silent", False):
                    self.notify(
                        "⚠ System audio leg looked silent during this recording. "
                        "Other participants may be missing. Temp files preserved.",
                        severity="warning",
                        timeout=15,
                    )
                if getattr(self.recorder, "last_mic_silent", False):
                    self.notify(
                        "⚠ Microphone leg looked silent during this recording. "
                        "Your voice may be missing. Temp files preserved.",
                        severity="warning",
                        timeout=15,
                    )
                preserved = getattr(self.recorder, "last_temp_files", [])
                if preserved:
                    logger.warning(
                        f"Preserved temp files for manual recovery: {preserved}"
                    )

                # Update status to processing
                self._write_status_file("processing")
                
                # Remove recording view
                try:
                    recording_view = self.query_one(RecordingView)
                    recording_view.remove()
                except Exception:
                    pass
                
                # Show main panels
                main_panels = self.query_one("#main-panels", Container)
                main_panels.display = True
                
                # Update footer bindings
                self.refresh_bindings()
                
                # Process in background
                self.notify("Processing recording...", severity="information")
                self.process_recording(audio_path, meeting_title, user_notes)
                
            except Exception as e:
                logger.error(f"Failed to stop recording: {e}", exc_info=True)
                self.notify(f"Failed to stop recording: {e}", severity="error")
                self.is_recording = False
    
    @work(exclusive=True, thread=True)
    def process_recording(self, audio_path: str, meeting_title: Optional[str] = None, user_notes: str = "") -> None:
        """Process recording in background thread."""
        logger.info(f"Processing recording: {audio_path}")
        try:
            # Load Whisper model (if not already loaded)
            logger.info("Loading Whisper model")
            self.call_from_thread(self.notify, f"Loading Whisper {self.config.whisper_model} model...", severity="information")
            self.transcriber.load_model()
            
            # Transcribe
            logger.info("Starting transcription")
            self.call_from_thread(self.notify, "Transcribing audio (this may take a few minutes)...", severity="information")
            result = self.transcriber.transcribe(audio_path)
            
            word_count = len(result.text.split())
            logger.info(f"Transcription complete: {word_count} words")
            self.call_from_thread(self.notify, f"✓ Transcribed {word_count} words. Generating AI summary...", severity="information")
            
            # Format transcript
            formatted = '\n\n'.join([
                f'**[{int(seg.start // 60):02d}:{int(seg.start % 60):02d}]** {seg.text.strip()}'
                for seg in result.segments
            ])
            
            # Generate note with AI summary (pass custom title if provided)
            logger.info("Creating note with AI summary")
            duration = result.segments[-1].end if result.segments else 0
            note_path, transcript_path, ai_error = self.note_maker.create_note(
                transcript_text=result.text,
                formatted_transcript=formatted,
                duration=duration,
                title=meeting_title,
                user_notes=user_notes
            )
            
            # Update UI
            if ai_error:
                logger.warning(f"Note created but AI summarization failed: {ai_error}")
                self.call_from_thread(self.notify, f"⚠ Note created but {ai_error}", severity="warning")
                self.call_from_thread(self.notify, f"Check ~/.config/meeting-notes/errors.log for details", severity="warning")
            else:
                logger.info(f"Note created successfully: {note_path}")
                logger.info(f"Transcript saved: {transcript_path}")
                self.call_from_thread(self.notify, f"✓ Note created: {Path(note_path).name}", severity="information")
            self.call_from_thread(self.load_meetings)
            
            # Clear status back to idle after successful processing
            self._write_status_file("idle")
            
        except Exception as e:
            logger.error(f"Error processing recording: {e}", exc_info=True)
            self.call_from_thread(self.notify, f"Error processing: {e}", severity="error")
            
            # Clear status back to idle after error
            self._write_status_file("idle")
    
    def _open_in_new_terminal(self, editor: str, file_path: str) -> bool:
        """
        Open editor in a new terminal window.
        
        Returns:
            True if successfully opened in new terminal, False otherwise
        """
        import shutil
        
        # If running inside tmux, open editor in a new tmux window
        if os.getenv("TMUX"):
            try:
                subprocess.Popen(["tmux", "new-window", "--", editor, file_path])
                return True
            except Exception:
                pass  # Fall through to terminal detection
        # Try to detect terminal emulator (check $TERMINAL first, then common terminals)
        terminal = os.getenv('TERMINAL')
        
        terminal_commands = {
            'alacritty': ['alacritty', '-e', editor, file_path],
            'kitty': ['kitty', editor, file_path],
            'ghostty': ['ghostty', '-e', editor, file_path],
            'wezterm': ['wezterm', 'start', '--', editor, file_path],
            'foot': ['foot', editor, file_path],
            'gnome-terminal': ['gnome-terminal', '--', editor, file_path],
            'konsole': ['konsole', '-e', editor, file_path],
            'xterm': ['xterm', '-e', editor, file_path],
            'urxvt': ['urxvt', '-e', editor, file_path],
            'st': ['st', '-e', editor, file_path],
        }
        
        # If $TERMINAL is set and exists, try it first
        if terminal:
            terminal_name = Path(terminal).name
            if terminal_name in terminal_commands:
                try:
                    subprocess.Popen(terminal_commands[terminal_name])
                    return True
                except Exception:
                    pass  # Fall through to auto-detection
        
        # Auto-detect by checking which terminals are available
        for term_name, cmd in terminal_commands.items():
            if shutil.which(term_name):
                try:
                    subprocess.Popen(cmd)
                    return True
                except Exception:
                    continue
        
        return False
    
    def action_open_in_editor(self) -> None:
        """Open selected note in editor in a new terminal window."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            import shutil
            
            editor = self.config.editor
            file_path = str(viewer.current_note)
            
            # Check if editor exists
            if not shutil.which(editor):
                self.notify(f"✗ Editor '{editor}' not found. Update in settings (,) or install it.", severity="error")
                return
            
            # Try to open in new terminal window
            try:
                if self._open_in_new_terminal(editor, file_path):
                    self.notify(f"✓ Opened in {editor}", severity="information")
                else:
                    # Fallback: open in same terminal (will replace TUI temporarily)
                    subprocess.Popen([editor, file_path])
                    self.notify(f"⚠ Opened in {editor} (same terminal - no terminal emulator detected)", severity="warning")
            except Exception as e:
                self.notify(f"✗ Failed to open editor: {e}", severity="error")
        else:
            self.notify("No note selected", severity="warning")
    
    def action_copy_to_clipboard(self) -> None:
        """Copy selected note to clipboard."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            try:
                with open(viewer.current_note, 'r') as f:
                    content = f.read()
                
                # Try clipboard tools in order: wl-copy (Wayland), xclip, xsel
                import shutil
                
                if shutil.which('wl-copy'):
                    # Wayland (Hyprland, Sway, etc.)
                    process = subprocess.Popen(
                        ['wl-copy'],
                        stdin=subprocess.PIPE
                    )
                    process.communicate(content.encode())
                    self.notify("✓ Copied to clipboard", severity="information")
                elif shutil.which('xclip'):
                    # X11 with xclip
                    process = subprocess.Popen(
                        ['xclip', '-selection', 'clipboard'],
                        stdin=subprocess.PIPE
                    )
                    process.communicate(content.encode())
                    self.notify("✓ Copied to clipboard", severity="information")
                elif shutil.which('xsel'):
                    # X11 with xsel
                    process = subprocess.Popen(
                        ['xsel', '--clipboard'],
                        stdin=subprocess.PIPE
                    )
                    process.communicate(content.encode())
                    self.notify("✓ Copied to clipboard", severity="information")
                else:
                    self.notify("Install wl-clipboard (Wayland) or xclip/xsel (X11)", severity="error")
                    
            except Exception as e:
                self.notify(f"Failed to copy: {e}", severity="error")
        else:
            self.notify("No note selected", severity="warning")
    
    def action_show_in_folder(self) -> None:
        """Show selected note in file manager and focus on the file."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            try:
                import shutil
                file_path = str(viewer.current_note.absolute())
                folder = str(viewer.current_note.parent)

                # If a terminal file browser is configured, use it
                terminal_browser = self.config.terminal_file_browser
                if terminal_browser and shutil.which(terminal_browser):
                    if self._open_in_new_terminal(terminal_browser, folder):
                        self.notify(
                            f"Opened in {terminal_browser}", severity="information"
                        )
                        return

                # Try to detect file manager and use --select flag
                # This focuses on the specific file instead of just opening the folder
                file_managers = [
                    (['dolphin', '--select', file_path], 'dolphin'),  # KDE
                    (['nautilus', '--select', file_path], 'nautilus'),  # GNOME
                    (['nemo', file_path], 'nemo'),  # Cinnamon
                    (['thunar', file_path], 'thunar'),  # XFCE
                    (['pcmanfm', '--select', file_path], 'pcmanfm'),  # LXDE
                ]
                
                # Try each file manager
                opened = False
                for cmd, fm_name in file_managers:
                    if shutil.which(cmd[0]):
                        subprocess.Popen(cmd)
                        self.notify(f"Opened in {fm_name}", severity="information")
                        return

                # Fallback: try to auto-detect a terminal file browser
                terminal_browsers = [
                    "ranger",
                    "yazi",
                    "lf",
                    "nnn",
                    "vifm",
                    "mc",
                    "vidir",
                    "joshuto",
                    "broot",
                ]
                for browser in terminal_browsers:
                    if shutil.which(browser):
                        if self._open_in_new_terminal(browser, folder):
                            self.notify(f"Opened in {browser}", severity="information")
                            return
                
                # Fallback: just open the folder
                subprocess.Popen(['xdg-open', folder])
                self.notify(f"Opened folder (file manager doesn't support --select)", severity="information")

            except Exception as e:
                self.notify(f"Failed to open: {e}", severity="error")
        else:
            self.notify("No note selected", severity="warning")
    
    def action_copy_path(self) -> None:
        """Copy the full absolute path of the selected note to clipboard."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            try:
                import shutil
                file_path = str(viewer.current_note.absolute())
                
                # Try clipboard tools in order: wl-copy (Wayland), xclip, xsel
                if shutil.which('wl-copy'):
                    # Wayland (Hyprland, Sway, etc.)
                    process = subprocess.Popen(
                        ['wl-copy'],
                        stdin=subprocess.PIPE
                    )
                    process.communicate(file_path.encode())
                    self.notify(f"✓ Copied path to clipboard", severity="information")
                elif shutil.which('xclip'):
                    # X11 with xclip
                    process = subprocess.Popen(
                        ['xclip', '-selection', 'clipboard'],
                        stdin=subprocess.PIPE
                    )
                    process.communicate(file_path.encode())
                    self.notify(f"✓ Copied path to clipboard", severity="information")
                elif shutil.which('xsel'):
                    # X11 with xsel
                    process = subprocess.Popen(
                        ['xsel', '--clipboard'],
                        stdin=subprocess.PIPE
                    )
                    process.communicate(file_path.encode())
                    self.notify(f"✓ Copied path to clipboard", severity="information")
                else:
                    self.notify("Install wl-clipboard (Wayland) or xclip/xsel (X11)", severity="error")
                    
            except Exception as e:
                self.notify(f"Failed to copy path: {e}", severity="error")
        else:
            self.notify("No note selected", severity="warning")
    
    def action_delete_meeting(self) -> None:
        """Delete the selected meeting after confirmation."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            # Get the meeting item to show its title
            meeting_item = None
            try:
                meeting_list = self.query_one("#meetings", ListView)
                if meeting_list.highlighted_child and isinstance(meeting_list.highlighted_child, MeetingListItem):
                    meeting_item = meeting_list.highlighted_child
            except Exception:
                pass
            
            title = meeting_item.full_title if meeting_item else viewer.current_note.name
            
            # Show confirmation modal
            self.push_screen(
                ConfirmDeleteScreen(title),
                self.handle_delete_confirmation
            )
        else:
            self.notify("No note selected", severity="warning")
    
    def handle_delete_confirmation(self, confirmed: Optional[bool]) -> None:
        """Handle the result of delete confirmation."""
        if confirmed is True:
            viewer = self.query_one("#note-viewer", NoteViewer)
            if viewer.current_note:
                try:
                    # Delete the file
                    os.remove(viewer.current_note)
                    self.notify(f"✓ Deleted meeting", severity="information")
                    
                    # Clear viewer
                    viewer.show_empty()
                    
                    # Reload meetings list
                    self.load_meetings()
                    
                except Exception as e:
                    self.notify(f"Failed to delete: {e}", severity="error")
    
    def action_edit_title(self) -> None:
        """Edit the title of the selected meeting."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            # Get the current title
            meeting_item = None
            try:
                meeting_list = self.query_one("#meetings", ListView)
                if meeting_list.highlighted_child and isinstance(meeting_list.highlighted_child, MeetingListItem):
                    meeting_item = meeting_list.highlighted_child
            except Exception:
                pass
            
            current_title = meeting_item.full_title if meeting_item else "Meeting"
            
            # Show edit modal
            self.push_screen(
                EditTitleScreen(current_title),
                self.handle_edit_title
            )
        else:
            self.notify("No note selected", severity="warning")
    
    def handle_edit_title(self, new_title: Optional[str]) -> None:
        """Handle the result of title editing."""
        if new_title:
            viewer = self.query_one("#note-viewer", NoteViewer)
            if viewer.current_note:
                try:
                    # Read the file
                    with open(viewer.current_note, 'r') as f:
                        content = f.read()
                    
                    # Update the title in frontmatter
                    if content.startswith('---'):
                        parts = content.split('---', 2)
                        if len(parts) >= 3:
                            frontmatter = parts[1]
                            body = parts[2]
                            
                            # Replace title line
                            lines = frontmatter.split('\n')
                            new_lines = []
                            for line in lines:
                                if line.strip().startswith('title:'):
                                    new_lines.append(f'title: "{new_title}"')
                                else:
                                    new_lines.append(line)
                            
                            new_frontmatter = '\n'.join(new_lines)
                            new_content = f"---{new_frontmatter}---{body}"
                            
                            # Write back to file
                            with open(viewer.current_note, 'w') as f:
                                f.write(new_content)
                            
                            self.notify(f"✓ Updated title", severity="information")
                            
                            # Reload meetings and refresh viewer
                            self.load_meetings()
                            viewer.show_note(viewer.current_note)
                    
                except Exception as e:
                    self.notify(f"Failed to update title: {e}", severity="error")
    
    def action_manage_tags(self) -> None:
        """Manage tags for the selected meeting."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            # Get the current tags
            meeting_item = None
            try:
                meeting_list = self.query_one("#meetings", ListView)
                if meeting_list.highlighted_child and isinstance(meeting_list.highlighted_child, MeetingListItem):
                    meeting_item = meeting_list.highlighted_child
            except Exception:
                pass
            
            current_tags = meeting_item.tags if meeting_item else []
            
            # Show tags modal
            self.push_screen(
                ManageTagsScreen(current_tags),
                self.handle_manage_tags
            )
        else:
            self.notify("No note selected", severity="warning")
    
    def handle_manage_tags(self, new_tags: Optional[list]) -> None:
        """Handle the result of tag management."""
        if new_tags is not None:
            viewer = self.query_one("#note-viewer", NoteViewer)
            if viewer.current_note:
                try:
                    # Read the file
                    with open(viewer.current_note, 'r') as f:
                        content = f.read()
                    
                    # Update the tags in frontmatter
                    if content.startswith('---'):
                        parts = content.split('---', 2)
                        if len(parts) >= 3:
                            frontmatter = parts[1]
                            body = parts[2]
                            
                            # Build new tags list (always include default tags)
                            all_tags = ['meeting', 'auto-generated'] + new_tags
                            tags_str = f"tags: [{', '.join(all_tags)}]"
                            
                            # Replace tags line
                            lines = frontmatter.split('\n')
                            new_lines = []
                            tags_found = False
                            for line in lines:
                                if line.strip().startswith('tags:'):
                                    new_lines.append(tags_str)
                                    tags_found = True
                                else:
                                    new_lines.append(line)
                            
                            # If no tags line exists, add it before the closing ---
                            if not tags_found:
                                new_lines.insert(-1, tags_str)
                            
                            new_frontmatter = '\n'.join(new_lines)
                            new_content = f"---{new_frontmatter}---{body}"
                            
                            # Write back to file
                            with open(viewer.current_note, 'w') as f:
                                f.write(new_content)
                            
                            tag_count = len(new_tags)
                            self.notify(f"✓ Updated tags ({tag_count} custom tag{'s' if tag_count != 1 else ''})", severity="information")
                            
                            # Reload meetings and refresh viewer
                            self.load_meetings()
                            viewer.show_note(viewer.current_note)
                    
                except Exception as e:
                    self.notify(f"Failed to update tags: {e}", severity="error")
    
    def action_view_transcript(self) -> None:
        """View transcript for the selected meeting."""
        viewer = self.query_one("#note-viewer", NoteViewer)
        if viewer.current_note:
            # Guard against the underlying note file having been deleted
            # since it was loaded (e.g. cleaned up externally) — otherwise
            # the open() below crashes with FileNotFoundError.
            if not Path(viewer.current_note).exists():
                self.notify("Note file no longer exists", severity="warning")
                return
            try:
                # Read note to get transcript_file from frontmatter
                with open(viewer.current_note, 'r') as f:
                    content = f.read()
                
                # Parse transcript_file from frontmatter
                transcript_filename = None
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    if len(parts) >= 2:
                        frontmatter = parts[1]
                        for line in frontmatter.split('\n'):
                            if line.strip().startswith('transcript_file:'):
                                transcript_filename = line.split(':', 1)[1].strip().strip('"')
                                break
                
                if transcript_filename:
                    transcript_path = Path(self.config.transcripts_dir).expanduser() / transcript_filename
                    
                    if transcript_path.exists():
                        self.push_screen(TranscriptViewer(transcript_path))
                    else:
                        self.notify(f"Transcript not found: {transcript_filename}", severity="error")
                else:
                    self.notify("This note doesn't have a separate transcript file", severity="warning")
                    
            except Exception as e:
                logger.error(f"Error viewing transcript: {e}", exc_info=True)
                self.notify(f"Error viewing transcript: {e}", severity="error")
        else:
            self.notify("No note selected", severity="warning")
    
    def action_edit_transcript(self, transcript_path: Path) -> None:
        """Open transcript in external editor."""
        editor = self.config.editor or os.environ.get('EDITOR', 'vim')
        
        try:
            # Suspend the app to open editor
            with self.suspend():
                subprocess.run([editor, str(transcript_path)])
            
            self.notify(f"Edited: {transcript_path.name}")
        except Exception as e:
            logger.error(f"Error opening editor: {e}", exc_info=True)
            self.notify(f"Error opening editor: {e}", severity="error")
    
    def action_open_settings(self) -> None:
        """Open the settings screen."""
        self.push_screen(SettingsScreen(self.config), self.handle_settings_closed)

    def action_audio_test(self) -> None:
        """Open the audio test / diagnostics screen.

        Disabled while a real recording is in flight so the test capture
        can't fight the meeting capture for the same source.
        """
        if self.is_recording:
            self.notify("Stop the current recording before running the audio test.",
                        severity="warning")
            return
        self.push_screen(AudioTestScreen(self.config))
    
    def handle_settings_closed(self, new_config: Optional[AppConfig]) -> None:
        """Handle settings screen closing."""
        if new_config:
            # Settings were saved, reload config and components
            self.config = new_config
            
            # Reinitialize components with new config
            self.transcriber = WhisperTranscriber(
                self.config.whisper_model,
                device=self.config.whisper_device,
            )
            
            # Get appropriate API key based on provider (check config first, then env vars)
            api_key = None
            if self.config.ai_provider == "openai":
                api_key = self.config.openai_api_key or os.getenv("OPENAI_API_KEY")
            elif self.config.ai_provider == "anthropic":
                api_key = self.config.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
            elif self.config.ai_provider == "openrouter":
                api_key = self.config.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
            elif self.config.ai_provider == "ollama_cloud":
                api_key = self.config.ollama_cloud_api_key or os.getenv("OLLAMA_API_KEY")
            
            self.note_maker = NoteMaker(
                output_dir=self.config.notes_dir,
                transcripts_dir=self.config.transcripts_dir,
                ai_provider=self.config.ai_provider,
                ai_model=self.config.ai_model,
                api_key=api_key
            )
            self.notes_dir = Path(self.config.notes_dir).expanduser()
            self.notes_dir.mkdir(parents=True, exist_ok=True)
            
            # Reinitialize recorder if not currently recording
            if not self.is_recording:
                self.recorder = AudioRecorder(
                    output_dir=self.config.recordings_dir,
                    mode=self.config.recording_mode,
                    dev_mode=self.dev_mode,
                    mic_device=self.config.mic_device or None,
                    system_device=self.config.system_device or None,
                )
            
            # Reload meetings from potentially new directory
            self.load_meetings()
            
            self.notify("✓ Settings saved and applied", severity="information")


def run(dev_mode: bool = False):
    """Run the application."""
    # Pre-initialize the multiprocessing resource tracker while sys.stderr
    # is still the real fd 2.  Textual's app.run() redirects stderr to a
    # _PrintCapture whose fileno() returns -1, which later causes
    # "bad value(s) in fds_to_keep" when whisper/tqdm triggers
    # resource_tracker._launch().
    try:
        multiprocessing.resource_tracker.ensure_running()
    except Exception:
        pass  # Non-critical, best effort

    # Belt-and-braces: tqdm lazily creates a multiprocessing.RLock the first
    # time it is used, which on Python 3.14 also triggers the same
    # fork_exec/fds_to_keep validation against a now-closed stderr. Force
    # tqdm's lock to be created here while stderr is still valid; tqdm caches
    # it at the class level so whisper's later progress bars reuse it.
    try:
        import tqdm
        tqdm.tqdm.get_lock()
    except Exception:
        pass  # Non-critical, best effort

    app = MeetingNotesApp(dev_mode=dev_mode)
    app.run()
