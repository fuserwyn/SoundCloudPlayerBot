"""Groq LLM helpers: query normalisation and playlist generation."""

from __future__ import annotations

import logging
import re

from groq import APIError, AsyncGroq

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """Raised when the LLM call fails (network, rate-limit, key issue, ...)."""


_NORMALIZE_SYSTEM = (
    "You normalise a user music search request into the best query for SoundCloud's "
    "search engine. Rules:\n"
    "- If the request is in Russian or another non-Latin language and the artist/title "
    "is likely released under a Latin name, transliterate or translate it.\n"
    "- Fix obvious typos.\n"
    "- Keep it short: artist + track name only when known, otherwise just the topic.\n"
    "- Output ONLY the final search string. No quotes, no explanations, no leading text."
)

_PLAYLIST_SYSTEM = (
    "You are a music curator who suggests REAL tracks that are very likely to exist on "
    "SoundCloud (independent, electronic, hip-hop, lo-fi, ambient, indie, beats and "
    "remixes do extremely well there; mainstream pop hits often don't). "
    "Given a user prompt (mood, scenario, genre, language) propose track ideas.\n"
    "Output STRICTLY one track per line in the format: 'Artist - Title'. "
    "No numbering, no bullets, no quotes, no explanations, no headers. "
    "Use Latin spelling when possible to maximise SoundCloud search hits."
)


class LLMClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncGroq(api_key=api_key)
        self._model = model

    async def normalize_query(self, query: str) -> str:
        text = await self._chat(
            user=f"User request: {query}",
            system=_NORMALIZE_SYSTEM,
            max_tokens=80,
            temperature=0.2,
        )
        cleaned = text.strip().splitlines()[0].strip().strip('"').strip("'")
        return cleaned or query

    async def suggest_tracks(self, prompt: str, n: int = 8) -> list[str]:
        n = max(1, min(20, n))
        text = await self._chat(
            user=f"Suggest {n} tracks for: {prompt}",
            system=_PLAYLIST_SYSTEM,
            max_tokens=400,
            temperature=0.8,
        )
        lines: list[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            line = re.sub(r"^[\s\-\*\u2022\d\.\)]+", "", line).strip()
            line = line.strip('"').strip("'").strip("`")
            if not line:
                continue
            if " - " not in line and " — " not in line:
                continue
            lines.append(line)
            if len(lines) >= n:
                break
        return lines

    async def _chat(
        self,
        user: str,
        *,
        system: str | None = None,
        max_tokens: int = 200,
        temperature: float = 0.7,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except APIError as exc:
            logger.warning("Groq API error: %s", exc)
            raise LLMUnavailable(str(exc)) from exc
        except Exception as exc:
            logger.exception("Unexpected Groq failure")
            raise LLMUnavailable(str(exc)) from exc

        content = (response.choices[0].message.content or "").strip()
        if not content:
            raise LLMUnavailable("LLM returned an empty response.")
        return content
