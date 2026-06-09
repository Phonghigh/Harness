import importlib.resources
import re
from abc import ABC, abstractmethod

from harness.config import EnvSettings, HarnessConfig


class LLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class LLMAdapter(ABC):
    @abstractmethod
    def complete(self, system: str, user: str) -> LLMResponse: ...


class AnthropicAdapter(LLMAdapter):
    def __init__(self, model: str, api_key: str) -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str) -> LLMResponse:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return LLMResponse(content=msg.content[0].text)


class OpenAIAdapter(LLMAdapter):
    def __init__(self, model: str, api_key: str) -> None:
        import openai
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str) -> LLMResponse:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return LLMResponse(content=resp.choices[0].message.content)


def load_prompt(name: str) -> str:
    """Load a prompt template from harness/prompts/<name>.md"""
    pkg = importlib.resources.files("harness.prompts")
    return (pkg / f"{name}.md").read_text(encoding="utf-8")


def split_prompt(template: str) -> tuple[str, str]:
    """Split a prompt template into (system, user_template) at ---USER--- marker."""
    parts = template.split("---USER---", 1)
    system = parts[0].strip()
    user_template = parts[1].strip() if len(parts) > 1 else ""
    return system, user_template


def extract_json_block(text: str) -> str:
    """Strip ```json ... ``` fences; fall back to raw text."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def get_adapter(config: HarnessConfig, env: EnvSettings) -> LLMAdapter | None:
    """Return the configured LLM adapter, or None if no API key is available."""
    provider = env.harness_provider or config.llm_provider
    if provider == "anthropic":
        if not env.anthropic_api_key:
            return None
        return AnthropicAdapter(config.llm_model, env.anthropic_api_key)
    if provider == "openai":
        if not env.openai_api_key:
            return None
        return OpenAIAdapter(config.llm_model, env.openai_api_key)
    return None
