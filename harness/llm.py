import re
from abc import ABC, abstractmethod
from pathlib import Path


class LLMOutputError(Exception):
    pass


def extract_json_block(text: str) -> str:
    """Strip ```json ... ``` fences; fall back to raw text."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    return match.group(1) if match else text.strip()


def load_prompt(name: str) -> str:
    """Load a prompt template from harness/prompts/{name}.md"""
    prompts_dir = Path(__file__).parent / "prompts"
    return (prompts_dir / f"{name}.md").read_text()


class LLMAdapter(ABC):
    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Send a system + user message, return the text response."""
        ...


class AnthropicAdapter(LLMAdapter):
    def __init__(self, model: str, api_key: str | None = None) -> None:
        import anthropic
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def complete(self, system: str, user: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""


class OpenAIAdapter(LLMAdapter):
    def __init__(self, model: str, api_key: str | None = None) -> None:
        import openai
        self.model = model
        self.client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()

    def complete(self, system: str, user: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""


def build_adapter(provider: str, model: str) -> LLMAdapter:
    """Build the right LLM adapter from provider name and model ID."""
    from harness.config import EnvSettings
    env = EnvSettings()

    effective_provider = env.harness_provider or provider

    if effective_provider == "anthropic":
        return AnthropicAdapter(model=model, api_key=env.anthropic_api_key)
    elif effective_provider == "openai":
        return OpenAIAdapter(model=model, api_key=env.openai_api_key)
    else:
        raise ValueError(
            f"Unknown LLM provider: {effective_provider!r}. Use 'anthropic' or 'openai'."
        )
