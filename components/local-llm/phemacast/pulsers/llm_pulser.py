"""
LLM pulser: serves the shared `llm_chat` pulse through the LLM providers its configuration lists.

Each provider is a configuration entry: an id and name, the adapter for its wire format, the environment variable
holding the site's key, its base URL, the models it offers and their prices in points. Adding a provider is a
configuration entry; only a new wire format needs a new adapter. Adapters now: `anthropic-messages` (the Claude
Messages API, run exactly as ClaudePulser runs it) and `openai-chat` (Chat Completions, which OpenAI-compatible
vendors also speak).

Requests never carry provider keys: a call here always runs on the site's key and is priced by the model it uses.
A provider marked `"local": true` is a model server on this computer (an OpenAI-compatible endpoint such as Ollama's
at http://127.0.0.1:11434/v1): it needs no key, only a loopback base URL, and is never published for own-key calls,
since nothing but this pulser can reach it.
A model's price assumes the pulser's limits, so every adapter keeps them: output never exceeds the pulser's
`max_tokens` (or a provider's own lower `max_tokens`), and a provider's `max_effort` lowers a caller's higher effort.
For a viewer who brings their own key, the card publishes each provider as a declarative endpoint
(`meta.llm_providers`), and the viewer's Terminal calls the vendor itself with it; that key never reaches this
pulser or any other agent.
"""

import copy
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

import httpx
from fastapi import HTTPException

from phemacast.agents.pulser import Pulser, _point_cost_from_payload
from phemacast.core.llm_content import content_text, wire_content
from phemacast.pulsers.claude_pulser import (ANSWER_BLOCKS, ANTHROPIC_PARTS, ClaudeChat, chat_messages, page_to_read,
                                             web_fetch_variants)

logger = logging.getLogger(__name__)

LLM_PROVIDERS = "llm_providers"
PROVIDER_SCHEMA = "phemacast:llm-provider/1"
DEFAULT_TIMEOUT_SECONDS = 120
MAX_TIMEOUT_SECONDS = 120
DEFAULT_MAX_TOKENS = 4096
DEFAULT_MAX_INPUT_CHARS = 200_000
ANTHROPIC_VERSION = "2023-06-01"
THINKING = re.compile(r"^\s*<think>.*?</think>", re.DOTALL)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _points(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def _host(url: str) -> str:
    return httpx.URL(url).host.lower() if url else ""


LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _base_url_allowed(entry: Mapping[str, Any], base_url: str) -> bool:
    """Vendors over HTTPS; a local model server only on this computer's loopback."""
    if entry.get("local") is True:
        try:
            url = httpx.URL(base_url)
        except Exception:
            return False
        return url.scheme in ("http", "https") and url.host.lower() in LOOPBACK and not url.userinfo
    return base_url.startswith("https://")


class Adapter:
    """One wire format: how the site calls it, and the endpoint a Terminal runs with a viewer's own key."""

    name = ""

    def endpoint(self, provider: Mapping[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def site_chat(self, pulser: "LLMPulser", provider: Mapping[str, Any], model: str, input_data: Mapping[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class AnthropicMessages(Adapter):
    name = "anthropic-messages"

    def endpoint(self, provider):
        return {"method": "POST", "url": provider["base_url"].rstrip("/") + "/v1/messages",
                "authentication": {"header": "x-api-key"},
                "headers": {"anthropic-version": _text(provider.get("api_version")) or ANTHROPIC_VERSION},
                "body": {"model": "$model", "max_tokens": "$max_tokens", "system": "$system", "messages": "$messages"},
                "text": "content.0.text", "error": "error.message",
                "usage": {"input": "usage.input_tokens", "output": "usage.output_tokens"},
                # Pictures, one page to read, and the answer after it: templates a Terminal fills for a viewer's key.
                "parts": ANTHROPIC_PARTS, "textBlocks": ANSWER_BLOCKS,
                "webFetch": web_fetch_variants([m["id"] for m in provider.get("models") or [] if isinstance(m, dict) and isinstance(m.get("id"), str)])}

    def site_chat(self, pulser, provider, model, input_data):
        chat = pulser._claude_chats.get(provider["id"])
        if chat is None:
            # ClaudeChat never sends more than its config's max_tokens, so that is the pulser's cap, not the provider's.
            config = {**{k: v for k, v in provider.items() if k not in ("models", "prices")}, "model": model,
                      "max_tokens": pulser.token_cap(provider)}
            chat = pulser._claude_chats[provider["id"]] = ClaudeChat(config, label=provider["id"], api_key=pulser.site_key(provider))
        return chat.chat(input_data, model=model)


# Chat Completions writes a picture as an image_url part, either a data URL or a link.
OPENAI_PARTS = {"text": {"type": "text", "text": "$text"},
                "imageData": {"type": "image_url", "image_url": {"url": "data:$mediaType;base64,$data"}},
                "imageUrl": {"type": "image_url", "image_url": {"url": "$url"}}}


class OpenAIChat(Adapter):
    name = "openai-chat"

    def endpoint(self, provider):
        tokens = _text(provider.get("max_tokens_field")) or "max_completion_tokens"
        return {"method": "POST", "url": provider["base_url"].rstrip("/") + "/chat/completions",
                "authentication": {"scheme": "bearer"}, "headers": {},
                "body": {"model": "$model", tokens: "$max_tokens", "messages": "$messages_with_system"},
                "text": "choices.0.message.content", "error": "error.message",
                "usage": {"input": "usage.prompt_tokens", "output": "usage.completion_tokens"},
                "parts": OPENAI_PARTS}

    def site_chat(self, pulser, provider, model, input_data):
        key = pulser.site_key(provider)
        base = {"provider": provider["id"], "model": model, "requested_model": _text(input_data.get("model"))}
        local = provider.get("local") is True
        if not key and not local:
            return {**base, "error": f"No {provider['name']} key is configured for this site."}
        if input_data.get("web_fetch") is not None:
            return {**base, "error": f"{provider['name']} cannot read a link."}
        system, turns = chat_messages(input_data)
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": turn["role"], "content": wire_content(turn["content"], OPENAI_PARTS)} for turn in turns]
        endpoint = self.endpoint(provider)
        tokens = next(k for k, v in endpoint["body"].items() if v == "$max_tokens")
        body = {"model": model, tokens: pulser.max_tokens(input_data, provider), "messages": messages}
        headers = {"Authorization": "Bearer " + key} if key else {}
        try:
            response = pulser.http().post(endpoint["url"], json=body, headers=headers,
                                          timeout=pulser.timeout_seconds(provider))
        except httpx.HTTPError:
            return {**base, "error": f"Could not reach the {provider['name']} API."}
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            error = data.get("error") if isinstance(data, dict) else None
            message = _text(error.get("message")) if isinstance(error, dict) else _text(error)
            return {**base, "error": f"{provider['name']} API error {response.status_code}: {message or response.reason_phrase}"[:400]}
        choice = (data.get("choices") or [{}])[0] if isinstance(data, dict) else {}
        text = _text(((choice or {}).get("message") or {}).get("content"))
        if local:  # a reasoning model on a local server may write its thinking before the answer
            text = THINKING.sub("", text).strip()
        if not text:
            return {**base, "error": f"{provider['name']} returned no text (finish reason: {(choice or {}).get('finish_reason')})."}
        usage = data.get("usage") or {}
        return {**base, "model": _text(data.get("model")) or model, "response": text, "stop_reason": (choice or {}).get("finish_reason"),
                "usage": {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")}}


ADAPTERS: Dict[str, Adapter] = {adapter.name: adapter for adapter in (AnthropicMessages(), OpenAIChat())}


class LLMPulser(Pulser):
    """Pulser that answers `llm_chat` through its configured providers, priced per model."""

    def __init__(self, *args, **kwargs):
        self._claude_chats: Dict[str, ClaudeChat] = {}
        self._http: Optional[httpx.Client] = None
        # apply_pulser_config publishes the providers before the pulser registers.
        super().__init__(*args, **kwargs)

    # --- configuration -------------------------------------------------------------------------------------

    def default_points(self) -> int:
        llm_chat = next((p for p in self.supported_pulses if p.get("name") == "llm_chat"), {})
        return _points(self.raw_config.get("default_points"), _point_cost_from_payload(llm_chat) if llm_chat else 1)

    def provider_entries(self) -> List[Any]:
        """The provider entries before they are checked: the configuration's (a subclass may add its own)."""
        return list(self.raw_config.get("providers") or [])

    def providers(self) -> List[Dict[str, Any]]:
        """The configured providers, each with its adapter, base URL, models and prices."""
        rows = []
        for entry in self.provider_entries():
            if not isinstance(entry, Mapping) or _text(entry.get("adapter")) not in ADAPTERS or not _text(entry.get("id")):
                continue
            base_url = _text(entry.get("base_url"))
            if not _base_url_allowed(entry, base_url):
                continue
            provider = copy.deepcopy(dict(entry))
            provider["id"], provider["name"] = _text(entry["id"]), _text(entry.get("name")) or _text(entry["id"])
            points = _points(entry.get("points"), self.default_points())
            models = []
            for model in entry.get("models") or []:
                model = {"id": model} if isinstance(model, str) else dict(model) if isinstance(model, Mapping) else {}
                if _text(model.get("id")):
                    models.append({"id": _text(model["id"]), "name": _text(model.get("name")) or _text(model["id"]),
                                   "points": _points(model.get("points"), points)})
            if not models:
                continue
            provider["models"] = models
            provider["default_model"] = _text(entry.get("default_model")) if any(m["id"] == _text(entry.get("default_model")) for m in models) else models[0]["id"]
            rows.append(provider)
        return rows

    def provider(self, provider_id: Any = None, model: Any = None) -> Optional[Dict[str, Any]]:
        providers = self.providers()
        wanted = _text(provider_id)
        if wanted:
            return next((p for p in providers if p["id"] == wanted), None)
        name = _text(model)
        if name:
            found = next((p for p in providers if any(m["id"] == name for m in p["models"])), None)
            if found:
                return found
            found = next((p for p in providers if any(name.startswith(prefix) for prefix in p.get("model_prefixes") or [])), None)
            if found:
                return found
        site = self.site_choice()
        return next((p for p in providers if p["id"] == site.get("provider")), providers[0] if providers else None)

    def site_choice(self) -> Dict[str, str]:
        """The model the site offers viewers who don't bring a key."""
        model = _text(self.raw_config.get("site_model"))
        providers = self.providers()
        provider = next((p for p in providers if any(m["id"] == model for m in p["models"])), providers[0] if providers else None)
        if provider is None:
            return {}
        if not any(m["id"] == model for m in provider["models"]):
            model = provider["default_model"]
        return {"provider": provider["id"], "model": model}

    def model_for(self, provider: Mapping[str, Any], requested: Any) -> str:
        name = _text(requested)
        aliases = provider.get("model_aliases") if isinstance(provider.get("model_aliases"), Mapping) else {}
        name = _text(aliases.get(name)) or name
        return name if any(m["id"] == name for m in provider["models"]) else provider["default_model"]

    def price(self, provider: Mapping[str, Any], model: str) -> int:
        return next((m["points"] for m in provider["models"] if m["id"] == model), self.default_points())

    def site_key(self, provider: Mapping[str, Any]) -> str:
        return _text(os.environ.get(_text(provider.get("key_env")))) if _text(provider.get("key_env")) else ""

    def timeout_seconds(self, provider: Mapping[str, Any]) -> float:
        try:
            value = float(provider.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            value = DEFAULT_TIMEOUT_SECONDS
        return min(float(MAX_TIMEOUT_SECONDS), max(1.0, value))

    def token_cap(self, provider: Optional[Mapping[str, Any]] = None) -> int:
        """The most output a site-key call may get: the pulser's cap, or the provider's own if it is lower."""
        cap = _points(self.raw_config.get("max_tokens"), DEFAULT_MAX_TOKENS) or DEFAULT_MAX_TOKENS
        own = _points((provider or {}).get("max_tokens"), 0)
        return min(cap, own) if own else cap

    def max_tokens(self, input_data: Mapping[str, Any], provider: Optional[Mapping[str, Any]] = None) -> int:
        cap = self.token_cap(provider)
        requested = _points(input_data.get("max_tokens"), 0)
        return min(cap, requested) if requested else cap

    def max_input_chars(self, caller: Any) -> int:
        """Prompt size limit for this caller; 0 for the pulser's own owner (its agents, or a local call)."""
        if not isinstance(caller, Mapping) or caller.get("own_owner") is True or str(caller.get("auth_mode") or "") in {"plaza", "direct"}:
            return 0
        user = caller.get("user") if isinstance(caller.get("user"), Mapping) else {}
        owner = self._configuration_owner_id()
        if owner and str(user.get("id") or "").strip() == owner:
            return 0
        return _points(self.raw_config.get("max_input_chars"), DEFAULT_MAX_INPUT_CHARS) or DEFAULT_MAX_INPUT_CHARS

    def http(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(follow_redirects=False, trust_env=False)
        return self._http

    # --- publication --------------------------------------------------------------------------------------

    def provider_publication(self) -> List[Dict[str, Any]]:
        """What a viewer's Terminal needs to call each provider with the viewer's own key: hosts, models, endpoint."""
        rows = []
        for provider in self.providers():
            if provider.get("local") is True:
                continue  # a model on this computer is reached only through this pulser
            endpoint = ADAPTERS[provider["adapter"]].endpoint(provider)
            endpoint["timeoutSeconds"] = int(self.timeout_seconds(provider))
            rows.append({"schema": PROVIDER_SCHEMA, "id": provider["id"], "name": provider["name"],
                         "directAccess": {"hosts": [_host(provider["base_url"])]},
                         "models": [{"id": m["id"], "name": m["name"], "points": m["points"]} for m in provider["models"]],
                         "defaultModel": provider["default_model"], "endpoint": endpoint})
        return rows

    def publish_providers(self) -> None:
        card = dict(self.agent_card or {})
        meta = dict(card.get("meta") or {})
        meta[LLM_PROVIDERS] = self.provider_publication()
        meta["llm_site"] = self.site_choice()
        card["meta"] = meta
        self.agent_card = card

    def apply_pulser_config(self, config_data, *args, **kwargs):
        super().apply_pulser_config(config_data, *args, **kwargs)
        self._claude_chats = {}
        self.publish_providers()

    # --- llm_chat -----------------------------------------------------------------------------------------

    def resolve(self, input_data: Mapping[str, Any]):
        provider = self.provider(input_data.get("provider"), input_data.get("model"))
        if provider is None:
            raise HTTPException(status_code=404, detail="This LLM pulser has no provider for that request.")
        return provider, self.model_for(provider, input_data.get("model"))

    def quote_pulse_data(self, input_data, pulse_name=None, pulse_address=None, ttl_seconds=None, quote_id=None):
        quote = super().quote_pulse_data(input_data, pulse_name=pulse_name, pulse_address=pulse_address, ttl_seconds=ttl_seconds, quote_id=quote_id)
        if (pulse_name or quote.get("pulse_name")) != "llm_chat" or not isinstance(input_data, Mapping):
            return quote
        try:
            provider, model = self.resolve(input_data)
        except HTTPException:
            return quote
        points = self.price(provider, model)
        quote.update(points=points, cost_points=points, provider=provider["id"], model=model)
        quote["pricing"] = {**quote.get("pricing", {}), "points": points}
        quote["cost_calculation"] = {**quote.get("cost_calculation", {}), "points": points}
        return quote

    def fetch_pulse_payload(self, pulse_name: str, input_data: Dict[str, Any], pulse_definition: Dict[str, Any]) -> Dict[str, Any]:
        if pulse_name != "llm_chat":
            return super().fetch_pulse_payload(pulse_name, input_data, pulse_definition)
        data = dict(input_data or {})
        caller = data.pop("_caller", None)
        provider, model = self.resolve(data)
        try:
            system, turns = chat_messages(data)
            page_to_read(data)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        if not turns:
            return {"error": "Prompt is required for llm_chat pulse.", "provider": provider["id"]}
        # A call is priced per model, not per length: another owner's prompt has a size limit (2026-11-14).
        # Pictures are bounded apart (at most two, each under 1 MB of base64), so only text counts here.
        limit = self.max_input_chars(caller)
        size = len(system) + sum(len(content_text(turn["content"])) for turn in turns)
        if limit and size > limit:
            raise HTTPException(status_code=413, detail=f"The prompt is too long for this service ({size} characters; the limit is {limit}).")
        result = ADAPTERS[provider["adapter"]].site_chat(self, provider, model, data)
        if result.get("error"):
            # A failed call is not completed, so its points are not paid.
            logger.warning("[%s] %s %s failed: %s", self.name, provider["id"], model, result["error"])
            raise HTTPException(status_code=502, detail=result["error"])
        result.setdefault("points", self.price(provider, model))
        return result
