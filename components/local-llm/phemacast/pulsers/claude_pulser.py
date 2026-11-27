"""
Claude pulser: serves the shared `llm_chat` pulse with Anthropic's Claude models.

Any `llm_chat` caller can be pointed at this pulser unchanged. A request that
names a model which is not a Claude model, for example one written for another
provider, is redirected to the configured Claude model; the response names the
model that actually ran.

Credentials come from the pulser configuration or the process environment
(`ANTHROPIC_API_KEY`). Requests never carry provider keys.

`ClaudeChat` holds the Claude Messages API call itself, so the LLM pulser's
Anthropic provider (phemacast.pulsers.llm_pulser) runs exactly the same request.
"""

import logging
from typing import Any, Dict, List, Mapping, Optional, Tuple

import anthropic

from phemacast.agents.pulser import Pulser

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_TOKENS = 16000
# Adaptive thinking shares the output allowance, so callers sized for
# non-thinking models may lower the cap only this far.
DEFAULT_MIN_TOKENS = 4096
DEFAULT_EFFORT = "medium"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Models that accept server-side refusal fallback on the Claude API.
FALLBACK_MODELS = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


# How the Claude Messages API writes vendor-neutral message parts (phemacast.core.llm_content), and the tool that
# reads one web page. The LLM pulser publishes the same templates for a Terminal that calls Claude with a viewer's key.
ANTHROPIC_PARTS = {
    "text": {"type": "text", "text": "$text"},
    "imageData": {"type": "image", "source": {"type": "base64", "media_type": "$mediaType", "data": "$data"}},
    "imageUrl": {"type": "image", "source": {"type": "url", "url": "$url"}},
}
WEB_FETCH_MAX_CONTENT_TOKENS = 20000
# Reading the page first. Many sites draw their pages with scripts, so a read returns only a header or settings; the
# model may then search once for pages that show or describe that layout and read two of them. Claude's servers
# search and fetch, never this agent, and a read only reaches addresses already in the conversation.
WEB_FETCH_TOOL = [{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3,
                   "max_content_tokens": WEB_FETCH_MAX_CONTENT_TOKENS},
                  {"type": "web_search_20260209", "name": "web_search", "max_uses": 1}]
# Models that take the web fetch tool above (dynamic filtering); others are not offered page reading.
WEB_FETCH_PREFIXES = ("claude-fable-5", "claude-mythos-5", "claude-opus-5", "claude-sonnet-5",
                      "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8", "claude-sonnet-4-6")
ANSWER_BLOCKS = {"list": "content", "match": {"type": "text"}, "field": "text", "after": {"type": "web_fetch_tool_result"}}


def reads_pages(model: str) -> bool:
    return isinstance(model, str) and model.startswith(WEB_FETCH_PREFIXES)


def web_fetch_variants(models: List[str]) -> List[Dict[str, Any]]:
    readers = [m for m in models if reads_pages(m)]
    return [{"models": readers, "field": "tools", "value": WEB_FETCH_TOOL}] if readers else []


def chat_messages(input_data: Mapping[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """The system text and the user/assistant turns of an `llm_chat` request.

    A request carries either `messages` (system turns are joined into the system text) or a single `prompt`;
    a separate `system` comes first. A user or assistant turn's content is text, or a list of text and picture
    parts (phemacast.core.llm_content), checked here: at most two pictures. ValueError for a malformed part."""
    from phemacast.core.llm_content import MAX_IMAGES, checked_part
    system = [_text(input_data.get("system"))] if _text(input_data.get("system")) else []
    turns: List[Dict[str, Any]] = []
    images = 0
    messages = input_data.get("messages")
    if isinstance(messages, list) and messages:
        for message in messages:
            if not isinstance(message, Mapping):
                continue
            role, raw = _text(message.get("role")).lower(), message.get("content")
            if isinstance(raw, list) and role != "system":
                if not raw:
                    continue
                images += sum(checked_part(part) == "image" for part in raw)
                turns.append({"role": "assistant" if role == "assistant" else "user", "content": [dict(part) for part in raw]})
                continue
            content = _text(raw)
            if not content:
                continue
            if role == "system":
                system.append(content)
            else:
                turns.append({"role": "assistant" if role == "assistant" else "user", "content": content})
    elif _text(input_data.get("prompt")):
        turns.append({"role": "user", "content": input_data["prompt"]})
    if images > MAX_IMAGES:
        raise ValueError(f"Send at most {MAX_IMAGES} pictures.")
    return "\n\n".join(system), turns


def page_to_read(input_data: Mapping[str, Any]) -> Optional[str]:
    """The one web page an `llm_chat` request asks the model to read (`web_fetch`: {"url"}), checked."""
    from phemacast.core.llm_content import https_url
    asked = input_data.get("web_fetch")
    if asked is None:
        return None
    if not isinstance(asked, Mapping) or set(asked) != {"url"}:
        raise ValueError('web_fetch names one page: {"url": "https://..."}.')
    return https_url(asked["url"])


class ClaudeChat:
    """One Claude configuration's Messages API call for `llm_chat`."""

    def __init__(self, config: Mapping[str, Any], *, label: str = "claude", api_key: Optional[str] = None):
        self.config = config
        self.label = label
        self.api_key = api_key
        self._client: Optional[anthropic.Anthropic] = None

    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            timeout = float(self.config.get("timeout_seconds") or 240)
            self._client = anthropic.Anthropic(
                api_key=_text(self.api_key) or _text(self.config.get("api_key")) or None,
                timeout=min(3600.0, max(1.0, timeout)),
                max_retries=int(self.config.get("max_retries", 2)),
            )
        return self._client

    def resolve_model(self, requested: Any) -> str:
        """Return the Claude model that serves a request naming `requested`."""
        default = _text(self.config.get("model")) or DEFAULT_MODEL
        name = _text(requested)
        aliases = self.config.get("model_aliases")
        if isinstance(aliases, Mapping) and _text(aliases.get(name)):
            return _text(aliases[name])
        return name if name.startswith("claude-") else default

    def max_tokens(self, input_data: Mapping[str, Any]) -> int:
        cap = _positive_int(self.config.get("max_tokens")) or DEFAULT_MAX_TOKENS
        floor = min(cap, _positive_int(self.config.get("min_tokens")) or DEFAULT_MIN_TOKENS)
        options = input_data.get("options") if isinstance(input_data.get("options"), Mapping) else {}
        for value in (input_data.get("max_tokens"), input_data.get("max_completion_tokens"), options.get("num_predict")):
            requested = _positive_int(value)
            if requested:
                cap = min(cap, max(requested, floor))
        return cap

    def effort(self, input_data: Mapping[str, Any]) -> str:
        asked = (_text(v).lower() for v in (input_data.get("reasoning_effort"), input_data.get("effort"), self.config.get("effort")))
        effort = next((e for e in asked if e in EFFORTS), DEFAULT_EFFORT)
        # Effort sets how long the model thinks, so what a call costs: `max_effort` lowers a higher ask, never refuses it.
        ceiling = _text(self.config.get("max_effort")).lower()
        if ceiling in EFFORTS and EFFORTS.index(effort) > EFFORTS.index(ceiling):
            return ceiling
        return effort

    def chat(self, input_data: Mapping[str, Any], model: Optional[str] = None) -> Dict[str, Any]:
        from phemacast.core.llm_content import fill, wire_content
        try:
            system, turns = chat_messages(input_data)
            page = page_to_read(input_data)
        except ValueError as exc:
            return {"error": str(exc), "provider": self.label}
        if not turns:
            return {"error": "Prompt is required for llm_chat pulse.", "provider": self.label}
        requested = _text(input_data.get("model"))
        model = model or self.resolve_model(requested)
        request: Dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_tokens(input_data),
            "output_config": {"effort": self.effort(input_data)},
            "messages": [{"role": turn["role"], "content": wire_content(turn["content"], ANTHROPIC_PARTS)} for turn in turns],
        }
        if page:
            if not reads_pages(model):
                return {"error": f"{model} cannot read a link.", "provider": self.label, "model": model}
            from urllib.parse import urlsplit
            request["tools"] = fill(WEB_FETCH_TOOL, {"host": urlsplit(page).hostname.lower(), "url": page})
        if system:
            request["system"] = system
        if self.config.get("fallbacks", True) and model in FALLBACK_MODELS:
            request["betas"] = [FALLBACK_BETA]
            request["fallbacks"] = "default"
        base = {"provider": self.label, "model": model, "requested_model": requested}
        try:
            message = self.client().beta.messages.create(**request)
            # A server tool (reading the page) may pause a long turn; it continues from where it stopped.
            for _ in range(4):
                if message.stop_reason != "pause_turn":
                    break
                request = {**request, "messages": request["messages"] + [{"role": "assistant", "content": message.content}]}
                message = self.client().beta.messages.create(**request)
        except anthropic.AuthenticationError:
            return {**base, "error": "The Anthropic API key is missing or invalid."}
        except anthropic.NotFoundError as exc:
            return {**base, "error": f"Model not available: {exc.message}"}
        except anthropic.RateLimitError:
            return {**base, "error": "Anthropic rate limit reached; retry later."}
        except anthropic.APIStatusError as exc:
            return {**base, "error": f"Anthropic API error {exc.status_code}: {exc.message}"}
        except anthropic.APIConnectionError:
            return {**base, "error": "Could not reach the Anthropic API."}
        except anthropic.AnthropicError as exc:
            return {**base, "error": str(exc)}
        except TypeError as exc:
            # The SDK reports a missing API key as a TypeError when the request is built.
            if "authentication method" not in str(exc):
                raise
            return {**base, "error": "No Anthropic credentials are configured (set ANTHROPIC_API_KEY)."}

        base["model"] = message.model
        if message.stop_reason == "refusal":
            category = getattr(message.stop_details, "category", None) if message.stop_details else None
            return {**base, "error": "Claude declined this request.", "code": "refusal", "category": category}
        # Only the text after the last page read or search is the answer; notes the model wrote before it are not.
        blocks = list(message.content)
        reads = [i for i, block in enumerate(blocks) if block.type in ("web_fetch_tool_result", "web_search_tool_result")]
        text = "".join(block.text for block in blocks[(reads[-1] + 1 if reads else 0):] if block.type == "text")
        if not text:
            return {**base, "error": f"Claude returned no text (stop reason: {message.stop_reason})."}
        logger.info("[%s] llm_chat answered by %s (requested %s)", self.label, message.model, requested or "default")
        return {**base, "response": text, "stop_reason": message.stop_reason,
                "usage": {"input_tokens": message.usage.input_tokens, "output_tokens": message.usage.output_tokens}}


class ClaudePulser(Pulser):
    """Pulser that answers `llm_chat` with the Claude Messages API."""

    @property
    def _claude(self) -> ClaudeChat:
        # A reapplied configuration replaces raw_config, so the call always reads the current one.
        chat = self.__dict__.get("_claude_chat")
        if chat is None:
            chat = self.__dict__["_claude_chat"] = ClaudeChat(self.raw_config)
        chat.config = self.raw_config
        return chat

    @property
    def _client(self):
        return self._claude._client

    @_client.setter
    def _client(self, value):
        self._claude._client = value

    def _anthropic(self) -> anthropic.Anthropic:
        return self._claude.client()

    def resolve_model(self, requested: Any) -> str:
        """Return the Claude model that serves a request naming `requested`."""
        return self._claude.resolve_model(requested)

    def _max_tokens(self, input_data: Mapping[str, Any]) -> int:
        return self._claude.max_tokens(input_data)

    def _effort(self, input_data: Mapping[str, Any]) -> str:
        return self._claude.effort(input_data)

    def fetch_pulse_payload(self, pulse_name: str, input_data: Dict[str, Any], pulse_definition: Dict[str, Any]) -> Dict[str, Any]:
        if pulse_name == "llm_chat":
            return self._handle_llm_chat(input_data or {})
        return super().fetch_pulse_payload(pulse_name, input_data, pulse_definition)

    def _handle_llm_chat(self, input_data: Mapping[str, Any]) -> Dict[str, Any]:
        return self._claude.chat(input_data)
