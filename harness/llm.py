import re
import time
from abc import ABC, abstractmethod
from pathlib import Path


class LLMOutputError(Exception):
    pass


def extract_json_block(text: str) -> str:
    """Strip any fenced code block (```json, ```diff, ``` etc.); fall back to raw text."""
    match = re.search(r"```[a-z]*\s*(.*?)\s*```", text, re.DOTALL)
    return match.group(1) if match else text.strip()


def load_prompt(name: str) -> str:
    """Load a prompt template from harness/prompts/{name}.md"""
    prompts_dir = Path(__file__).parent / "prompts"
    return (prompts_dir / f"{name}.md").read_text()


def _is_retriable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "rate limit" in msg
        or "429" in msg
        or "529" in msg
        or "overloaded" in msg
        or "too many requests" in msg
    )


class LLMAdapter(ABC):
    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Send a system + user message, return the text response."""
        ...


class AnthropicAdapter(LLMAdapter):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        max_tokens: int = 4096,
        retries: int = 3,
    ) -> None:
        import anthropic
        self.model = model
        self.max_tokens = max_tokens
        self.retries = retries
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

    def complete(self, system: str, user: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                if hasattr(response, "usage") and response.usage:
                    self.total_input_tokens += getattr(response.usage, "input_tokens", 0)
                    self.total_output_tokens += getattr(response.usage, "output_tokens", 0)
                for block in response.content:
                    if block.type == "text":
                        return block.text
                return ""
            except Exception as exc:
                last_exc = exc
                if attempt == self.retries - 1 or not _is_retriable(exc):
                    raise
                time.sleep(2.0 ** attempt)
        raise last_exc  # unreachable but satisfies type checker

    def usage_summary(self) -> dict:
        return {"input": self.total_input_tokens, "output": self.total_output_tokens}


class OpenAIAdapter(LLMAdapter):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        max_tokens: int = 4096,
        retries: int = 3,
    ) -> None:
        import openai
        self.model = model
        self.max_tokens = max_tokens
        self.retries = retries
        self.client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()

    def complete(self, system: str, user: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                return response.choices[0].message.content or ""
            except Exception as exc:
                last_exc = exc
                if attempt == self.retries - 1 or not _is_retriable(exc):
                    raise
                time.sleep(2.0 ** attempt)
        raise last_exc


def build_adapter(provider: str, model: str, max_tokens: int = 4096, retries: int = 3) -> LLMAdapter:
    """Build the right LLM adapter from provider name and model ID."""
    from harness.config import EnvSettings
    env = EnvSettings()

    effective_provider = env.harness_provider or provider

    if effective_provider == "anthropic":
        return AnthropicAdapter(
            model=model, api_key=env.anthropic_api_key,
            max_tokens=max_tokens, retries=retries,
        )
    elif effective_provider == "openai":
        return OpenAIAdapter(
            model=model, api_key=env.openai_api_key,
            max_tokens=max_tokens, retries=retries,
        )
    else:
        raise ValueError(
            f"Unknown LLM provider: {effective_provider!r}. Use 'anthropic' or 'openai'."
        )
