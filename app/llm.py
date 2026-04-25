"""Groq LLM helpers: query normalisation and playlist generation."""

from __future__ import annotations

import logging
import re

from groq import APIError, AsyncGroq

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """Raised when the LLM call fails (network, rate-limit, key issue, ...)."""


_NORMALIZE_SYSTEM = (
    "You clean up a user's music search query before it is sent to SoundCloud search. "
    "The user often types phonetically or with typos and may mix scripts.\n"
    "\n"
    "Your job: recognise the artist and track they meant and output the query in the "
    "script the artist OFFICIALLY publishes under.\n"
    "Examples (input → output):\n"
    "  пинк флойд камфортабли намб → pink floyd comfortably numb\n"
    "  daft punk one more taim → daft punk one more time\n"
    "  кино группа крови → кино группа крови\n"
    "  zemfira iskala → земфира искала\n"
    "  психоцыкл амба → психоцикл амба\n"
    "  aphex twn windowliker → aphex twin windowlicker\n"
    "\n"
    "Rules:\n"
    "- If the artist is Western / international (releases under a Latin name) → output in Latin.\n"
    "- If the artist is Russian / CIS (releases under Cyrillic name) → output in Cyrillic.\n"
    "- If you genuinely cannot tell who they meant, fix obvious typos and keep the "
    "user's original script.\n"
    "- Keep it short: 'artist track' or 'artist - track', no extra words.\n"
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
