"""Note generation module for creating markdown notes."""

from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from collections import Counter
import json
import re

from .meeting_context import split_csv

from .logger import get_logger
from .live_notes import entries_for_prompt, entries_tags, format_live_notes, format_note_entries, parse_live_notes
from .recording_notes import NoteEntry

logger = get_logger(__name__)

try:
    from .summarizer import OllamaSummarizer
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

try:
    from .ai_summarizer import OpenAISummarizer, AnthropicSummarizer, OpenRouterSummarizer, OllamaCloudSummarizer, OpenAICompatibleSummarizer, MeetingSummary  # type: ignore
    CLOUD_AVAILABLE = True
except ImportError:
    CLOUD_AVAILABLE = False
    # Fallback MeetingSummary for type hints
    MeetingSummary = None  # type: ignore


class NoteMaker:
    """Generate markdown meeting notes."""

    def __init__(
        self,
        output_dir: str = "notes",
        transcripts_dir: str = "transcripts",
        ai_provider: str = "none",  # "cloud", "local", or "none"
        ai_model: str = "balanced",  # For cloud: tier, for local: ollama model
        api_key: Optional[str] = None,
        api_base_url: Optional[str] = None,
        provider_name: Optional[str] = None,
    ):
        """
        Initialize note maker.

        Args:
            output_dir: Directory to save notes
            transcripts_dir: Directory to save transcripts
            ai_provider: AI provider - "cloud" (OpenRouter), "local" (Ollama), or "none"
            ai_model: Model to use (tier for cloud, model name for local)
            api_key: API key for cloud provider (or use env var)
        """
        logger.info(f"Initializing NoteMaker (output_dir: {output_dir}, transcripts_dir: {transcripts_dir}, ai_provider: {ai_provider}, ai_model: {ai_model})")
        self.output_dir = Path(output_dir).expanduser()
        self.transcripts_dir = Path(transcripts_dir).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self.ai_provider = ai_provider
        self.summarizer: Optional[Any] = None

        if ai_provider in ["openai", "anthropic", "openrouter", "ollama_cloud", "custom_openai_compatible"]:
            if not CLOUD_AVAILABLE:
                logger.warning("Cloud AI packages not installed")
                self.ai_provider = "none"
            else:
                try:
                    from .ai_summarizer import OpenAISummarizer, AnthropicSummarizer, OpenRouterSummarizer, OpenAICompatibleSummarizer  # type: ignore

                    if ai_provider == "openai":
                        self.summarizer = OpenAISummarizer(api_key=api_key, model=ai_model)
                        model_name = OpenAISummarizer.MODELS[ai_model]["name"]
                        logger.info(f"AI summarization enabled (OpenAI: {model_name})")
                    elif ai_provider == "anthropic":
                        self.summarizer = AnthropicSummarizer(api_key=api_key, model=ai_model)
                        model_name = AnthropicSummarizer.MODELS[ai_model]["name"]
                        logger.info(f"AI summarization enabled (Anthropic: {model_name})")
                    elif ai_provider == "openrouter":
                        self.summarizer = OpenRouterSummarizer(api_key=api_key, model=ai_model)
                        model_name = OpenRouterSummarizer.MODELS[ai_model]["name"]
                        logger.info(f"AI summarization enabled (OpenRouter: {model_name})")
                    elif ai_provider == "ollama_cloud":
                        from .ai_summarizer import OllamaCloudSummarizer  # type: ignore
                        self.summarizer = OllamaCloudSummarizer(api_key=api_key, model=ai_model or "kimi-k2.6")
                        logger.info(f"AI summarization enabled (Ollama Cloud: {ai_model or 'kimi-k2.6'})")
                    elif ai_provider == "custom_openai_compatible":
                        self.summarizer = OpenAICompatibleSummarizer(
                            api_key=api_key,
                            model=ai_model,
                            base_url=api_base_url or "",
                            provider_name=provider_name or "Custom OpenAI-compatible",
                        )
                        logger.info("AI summarization enabled (%s: %s)", provider_name, ai_model)

                except Exception as e:
                    logger.error(f"Could not initialize cloud AI: {e}", exc_info=True)
                    self.ai_provider = "none"

        elif ai_provider == "local":
            if not OLLAMA_AVAILABLE:
                logger.warning("Ollama not available")
                self.ai_provider = "none"
            else:
                try:
                    from .summarizer import OllamaSummarizer  # type: ignore
                    # Defensive fallback: empty model name reaches
                    # `ollama run "" <prompt>` and errors with "model is required".
                    self.summarizer = OllamaSummarizer(model=ai_model or "llama3.2:3b")
                    logger.info(f"AI summarization enabled (Local Ollama: {ai_model})")
                except Exception as e:
                    logger.error(f"Could not initialize Ollama: {e}", exc_info=True)
                    self.ai_provider = "none"

    def create_note(
        self,
        transcript_text: str,
        formatted_transcript: str,
        duration: float,
        title: Optional[str] = None,
        metadata: Optional[dict] = None,
        user_notes: str = "",
        meeting_start: Optional[datetime] = None,
        prompt_transcript: Optional[str] = None,
        entries: Optional[list[NoteEntry]] = None,
    ) -> tuple[str, str, Optional[str]]:
        """Create a markdown note and separate transcript file.

        Args:
            transcript_text: Plain text transcript
            formatted_transcript: Transcript with timestamps
            duration: Recording duration in seconds
            title: Optional meeting title
            metadata: Optional additional metadata
            user_notes: Optional notes written by user during recording

        Returns:
            Tuple of (note_path, transcript_path, error_message). error_message is None if no error occurred.
        """
        # Notes are generated only after transcription and summarization.
        # Their timestamps must describe when capture began, not when
        # processing eventually completed.
        now = meeting_start or datetime.now()

        # Keep a non-empty user title; otherwise let the summarizer suggest one.
        # Collapse whitespace so either a user or model cannot inject new frontmatter
        # lines through the title field.
        explicit_title = bool(title and title.strip())
        if explicit_title:
            title = " ".join((title or "").split())
        else:
            # Placeholder used only if summarization is disabled or fails later.
            title = f"Meeting {now.strftime('%Y-%m-%d %H:%M')}"

        logger.info(f"Creating note: {title}")
        logger.debug(f"Transcript length: {len(transcript_text.split())} words")

        # Generate AI summary if enabled, otherwise use simple summary
        ai_error = None
        ai_suggested_title: Optional[str] = None
        if self.ai_provider != "none" and self.summarizer:
            try:
                if self.ai_provider in ["openai", "anthropic", "openrouter", "ollama_cloud", "custom_openai_compatible"]:
                    logger.info("Generating AI summary with cloud API")
                else:
                    logger.info("Generating AI summary with local Ollama")

                try:
                    ai_summary = self.summarizer.summarize(
                        prompt_transcript or transcript_text,
                        user_notes=entries_for_prompt(entries) if entries is not None else user_notes,
                        attendees=(metadata or {}).get("attendees", ""),
                        glossary=(metadata or {}).get("glossary", ""),
                    )
                except TypeError as exc:
                    if "attendees" not in str(exc) and "glossary" not in str(exc):
                        raise
                    # Preserve third-party/older summarizer adapter compatibility.
                    ai_summary = self.summarizer.summarize(
                        prompt_transcript or transcript_text,
                        user_notes=entries_for_prompt(entries) if entries is not None else user_notes,
                    )
                summary = {
                    'word_count': len(transcript_text.split()),
                    'ai_summary': ai_summary,
                    'keywords': [],  # AI summary replaces keywords
                    'questions': []  # AI summary includes this
                }
                ai_suggested_title = getattr(ai_summary, 'title', None)
                if ai_suggested_title:
                    # A model response can contain line breaks despite the prompt.
                    # Keep the title safe for YAML frontmatter and filesystem names.
                    ai_suggested_title = " ".join(ai_suggested_title.split())
                logger.info("AI summary generated successfully")
            except Exception as e:
                ai_error = f"AI summarization failed: {type(e).__name__}: {str(e)}"
                logger.error(ai_error, exc_info=True)
                summary = self._extract_simple_summary(transcript_text)
        else:
            logger.info("Using simple keyword-based summary (AI disabled)")
            summary = self._extract_simple_summary(transcript_text)

        # Finalize title after summarization: explicit user title wins,
        # then a non-empty AI suggestion, then the timestamp fallback.
        if not explicit_title and ai_suggested_title:
            title = ai_suggested_title
        # If no explicit title and no AI suggestion, title stays as the
        # timestamp fallback already set above.

        # Keep filenames legible in Obsidian. The first meeting of a day is
        # YYYY-MM-DD-DayName-Meeting; later meetings get their start time, and
        # a numeric suffix only for the exceptional same-minute collision.
        filename_base = self._meeting_filename_base(now)

        # Get recording filename from metadata
        recording_file = metadata.get('recording_file', '') if metadata else ''

        # Create transcript file (plain text)
        transcript_filename = f"{filename_base}.txt"
        transcript_path = self.transcripts_dir / transcript_filename
        transcript_content = self._generate_transcript_file(
            title=title,
            date=now,
            duration=duration,
            formatted_transcript=formatted_transcript,
            recording_file=recording_file
        )
        transcript_path.write_text(transcript_content)
        logger.info(f"Transcript saved: {transcript_path}")

        # Create note file (markdown, summary only)
        note_filename = f"{filename_base}.md"
        note_path = self.output_dir / note_filename
        note_content = self._generate_note_file(
            title=title,
            date=now,
            duration=duration,
            summary=summary,
            transcript_filename=transcript_filename,
            recording_file=recording_file,
            metadata=metadata or {},
            user_notes=user_notes,
            entries=entries,
        )
        note_path.write_text(note_content)
        logger.info(f"Note saved: {note_path}")

        # Link meeting to daily note
        self._link_to_daily_note(now, title)

        return str(note_path), str(transcript_path), ai_error

    def _meeting_filename_base(self, date: datetime) -> str:
        """Return a collision-safe, human-readable shared note/transcript stem."""
        base = f"{date.strftime('%Y-%m-%d-%A')}-Meeting"
        if not (self.output_dir / f"{base}.md").exists() and not (
            self.transcripts_dir / f"{base}.txt"
        ).exists():
            return base

        timed = f"{base}-{date.strftime('%H%M')}"
        candidate = timed
        suffix = 2
        while (self.output_dir / f"{candidate}.md").exists() or (
            self.transcripts_dir / f"{candidate}.txt"
        ).exists():
            candidate = f"{timed}-{suffix}"
            suffix += 1
        return candidate

    def _extract_simple_summary(self, text: str) -> dict:
        """Extract basic summary information without LLM.

        This is a fallback method when no AI provider is configured.
        """
        words = text.split()
        word_count = len(words)

        # Extract common keywords (simple frequency analysis)
        # Remove common words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                     'of', 'with', 'is', 'was', 'are', 'were', 'been', 'be', 'have', 'has',
                     'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may',
                     'might', 'can', 'this', 'that', 'these', 'those', 'i', 'you', 'he',
                     'she', 'it', 'we', 'they', 'my', 'your', 'his', 'her', 'its', 'our',
                     'their', 'what', 'which', 'who', 'when', 'where', 'why', 'how'}

        # Clean and filter words
        clean_words = [
            word.lower().strip('.,!?;:()[]{}""\'')
            for word in words
            if len(word) > 3
        ]

        filtered_words = [
            word for word in clean_words
            if word not in stop_words and word.isalpha()
        ]

        # Get top keywords
        word_freq = Counter(filtered_words)
        top_keywords = [word for word, count in word_freq.most_common(10)]

        # Extract sentences with question marks (potential questions)
        sentences = re.split(r'[.!?]+', text)
        questions = [s.strip() for s in sentences if '?' in s and len(s.strip()) > 10]

        return {
            'word_count': word_count,
            'keywords': top_keywords[:5],  # Top 5 keywords
            'questions': questions[:3]  # Up to 3 questions
        }

    def _generate_transcript_file(
        self,
        title: str,
        date: datetime,
        duration: float,
        formatted_transcript: str,
        recording_file: str
    ) -> str:
        """Generate plain text transcript file."""
        duration_str = self._format_duration(duration)
        date_str = date.strftime("%B %d, %Y at %I:%M %p")

        content = f"""Meeting: {title}
Start: {date_str}
Duration: {duration_str}
Recording: {recording_file}

{'─' * 60}

{formatted_transcript}
"""
        return content

    def _generate_note_file(
        self,
        title: str,
        date: datetime,
        duration: float,
        summary: dict,
        transcript_filename: str,
        recording_file: str,
        metadata: dict,
        user_notes: str = "",
        entries: Optional[list[NoteEntry]] = None,
    ) -> str:
        """Generate markdown note file (summary only, no transcript)."""

        duration_str = self._format_duration(duration)
        date_str = date.strftime("%B %d, %Y at %I:%M %p")

        # Build frontmatter with transcript reference
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        day_name = day_names[date.weekday()]
        month_dir = date.strftime("%m-%B")
        daily_note_path = f"Daily/{date.strftime('%Y')}/{month_dir}/{date.strftime('%Y-%m-%d')}-{day_name}"
        attendees = metadata.get("attendees", "")
        glossary = metadata.get("glossary", "")
        # Typed roster wins. Only use model-extracted people when no roster exists.
        people = split_csv(attendees) if attendees else getattr(summary.get("ai_summary"), "participants", [])
        note_tags = entries_tags(entries or []) if entries is not None else parse_live_notes(user_notes).tags
        tags = list(dict.fromkeys(["meeting", "auto-generated", *note_tags]))
        tags_frontmatter = ", ".join(tags)

        frontmatter = f"""---
title: "{title}"
date: {date.strftime("%Y-%m-%d")}
time: "{date.strftime("%H:%M")}"
duration_seconds: {int(duration)}
word_count: {summary['word_count']}
tags: [{tags_frontmatter}]
people: {json.dumps(people)}
attendees: {json.dumps(attendees)}
glossary: {json.dumps(glossary)}
recording_file: "{recording_file}"
transcript_file: "{transcript_filename}"
daily_note: "[[{daily_note_path}]]"
---
"""

        # Build content with AI summary if available (NO transcript)
        if 'ai_summary' in summary:
            # AI-powered summary
            ai = summary['ai_summary']
            summary_section = self._format_ai_summary(ai)
        else:
            # Simple keyword-based summary
            summary_section = f"""## Summary

This meeting covered several topics. Key themes included: {', '.join(summary['keywords'][:3]) if summary['keywords'] else 'various discussions'}.

### Key Topics

{self._format_list(summary['keywords']) if summary['keywords'] else '- (Auto-summary will be added when AI is enabled)'}

### Questions Raised

{self._format_list(summary['questions']) if summary['questions'] else '- None detected'}

"""

        # Structured ledgers are already parsed at commit time. Old sidecars retain
        # the legacy parser so historical meetings stay readable.
        live_notes_section = format_note_entries(entries or []) if entries is not None else format_live_notes(parse_live_notes(user_notes))
        if live_notes_section:
            live_notes_section += "\n\n"

        content = f"""{frontmatter}
# {title}

**Start:** {date_str}
**Duration:** {duration_str}
**Words:** {summary['word_count']:,}

{live_notes_section}{summary_section}

---

*Generated by Meeting Notes v0.3.0 on {datetime.now().strftime("%Y-%m-%d at %H:%M:%S")}*
"""

        return content

    def _link_to_daily_note(self, date: datetime, title: str) -> None:
        """Verify daily note exists for this meeting's date.

        The daily note's dataview query automatically lists meetings from the
        Meetings/ folder where date matches the filename, so no manual link
        injection is needed.
        """
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        day_name = day_names[date.weekday()]
        month_dir = date.strftime("%m-%B")
        daily_note_path = self.output_dir.parent / "Daily" / date.strftime("%Y") / month_dir / f"{date.strftime('%Y-%m-%d')}-{day_name}.md"

        if daily_note_path.exists():
            logger.info(f"Daily note found: {daily_note_path.name}")
        else:
            logger.info(f"No daily note found at {daily_note_path}, meeting will still appear when daily note is created")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in human-readable format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if secs > 0 or not parts:
            parts.append(f"{secs} second{'s' if secs != 1 else ''}")

        return ", ".join(parts)

    @staticmethod
    def _format_list(items: list) -> str:
        """Format a list as markdown bullet points."""
        if not items:
            return "- None"
        return "\n".join(f"- {item}" for item in items)

    @staticmethod
    def _format_ai_summary(ai_summary: Any) -> str:
        """Format AI-generated summary as markdown."""
        sections = []

        # Overview
        sections.append("## AI Summary\n")
        sections.append(ai_summary.overview)
        sections.append("")

        # Key Points
        sections.append("### Key Points\n")
        if ai_summary.key_points:
            sections.append("\n".join(f"- {point}" for point in ai_summary.key_points))
        else:
            sections.append("- None identified")
        sections.append("")

        # Action Items
        sections.append("### Action Items\n")
        if ai_summary.action_items:
            sections.append("\n".join(f"- {item}" for item in ai_summary.action_items))
        else:
            sections.append("- None identified")
        sections.append("")

        # Decisions
        sections.append("### Decisions Made\n")
        if ai_summary.decisions:
            sections.append("\n".join(f"- {decision}" for decision in ai_summary.decisions))
        else:
            sections.append("- None identified")
        sections.append("")

        # Open questions
        sections.append("### Open Questions\n")
        if getattr(ai_summary, "open_questions", []):
            sections.append("\n".join(f"- {question}" for question in ai_summary.open_questions))
        else:
            sections.append("- None identified")
        sections.append("")

        # This is explicitly not an attendee roster. The source is the
        # transcript, so it can include people discussed but absent.
        if ai_summary.participants:
            sections.append("### Names Mentioned\n")
            sections.append(", ".join(ai_summary.participants))
            sections.append("")

        return "\n".join(sections)


if __name__ == "__main__":
    # Simple test
    maker = NoteMaker()

    test_transcript = """
    Let's start with reviewing last sprint's velocity. We completed 23 story points
    which is pretty good. I think we should focus on the API endpoints first this sprint.
    We have three main endpoints to implement: user authentication, data sync, and analytics.
    What do you think about the timeline? Can we get this done in two weeks?
    """

    formatted = """**[00:00]** Let's start with reviewing last sprint's velocity.

**[00:05]** We completed 23 story points which is pretty good.

**[00:10]** I think we should focus on the API endpoints first this sprint."""

    note_path, transcript_path, error = maker.create_note(
        transcript_text=test_transcript,
        formatted_transcript=formatted,
        duration=125.0,
        title="Sprint Planning"
    )

    print(f"Created note: {note_path}")
    print(f"Created transcript: {transcript_path}")
    if error:
        print(f"Warning: {error}")
