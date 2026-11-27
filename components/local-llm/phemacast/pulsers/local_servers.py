"""The usual model servers on this computer and the address of each: data alone.

`phemacast.pulsers.local_models` asks these servers; a build that only describes them, such as Local LLM's settings in
scripts/build_components.py, reads them from here, without the pulser's libraries (Anthropic's SDK, httpx, FastAPI).
"""
from __future__ import annotations

from typing import Any, Mapping

# Each server's usual address on this computer.
KNOWN_SERVERS = (
    {'id': 'ollama', 'name': 'Ollama', 'port': 11434},
    {'id': 'lmstudio', 'name': 'LM Studio', 'port': 1234},
    {'id': 'vllm', 'name': 'vLLM', 'port': 8000},
    {'id': 'llamacpp', 'name': 'llama.cpp', 'port': 8080},  # also llamafile, LocalAI and mlx_lm.server by default
    {'id': 'jan', 'name': 'Jan', 'port': 1337},
    {'id': 'gpt4all', 'name': 'GPT4All', 'port': 4891},
    {'id': 'textgen', 'name': 'Text Generation WebUI', 'port': 5000},  # also TabbyAPI; macOS AirPlay answers 403 here
    {'id': 'koboldcpp', 'name': 'KoboldCpp', 'port': 5001},
    {'id': 'xinference', 'name': 'Xinference', 'port': 9997},
    {'id': 'docker', 'name': 'Docker Model Runner', 'port': 12434, 'path': '/engines/v1'},
    {'id': 'sglang', 'name': 'SGLang', 'port': 30000},
    {'id': 'exo', 'name': 'exo', 'port': 52415},
)


def default_url(known: Mapping[str, Any]) -> str:
    """A known server's usual address on this computer."""
    return f"http://127.0.0.1:{known['port']}{known.get('path', '/v1')}"
