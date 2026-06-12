"""Tests for LLM adapter retry logic and configuration."""
import pytest
from unittest.mock import MagicMock, patch, call


class TestAnthropicAdapterRetry:
    def _make_adapter(self, retries=3):
        from harness.llm import AnthropicAdapter
        adapter = AnthropicAdapter.__new__(AnthropicAdapter)
        adapter.model = "claude-sonnet-4-6"
        adapter.max_tokens = 4096
        adapter.retries = retries
        adapter.total_input_tokens = 0
        adapter.total_output_tokens = 0
        return adapter

    def _make_response(self, text="ok"):
        block = MagicMock()
        block.type = "text"
        block.text = text
        response = MagicMock()
        response.content = [block]
        response.usage = None
        return response

    def test_retries_on_rate_limit_then_succeeds(self):
        adapter = self._make_adapter(retries=3)
        rate_limit_err = Exception("rate limit exceeded 429")
        good_response = self._make_response("hello")

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [rate_limit_err, rate_limit_err, good_response]
        adapter.client = mock_client

        with patch("time.sleep"):
            result = adapter.complete("sys", "user")

        assert result == "hello"
        assert mock_client.messages.create.call_count == 3

    def test_raises_after_max_retries_on_rate_limit(self):
        adapter = self._make_adapter(retries=2)
        rate_limit_err = Exception("429 rate limit")

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = rate_limit_err
        adapter.client = mock_client

        with patch("time.sleep"), pytest.raises(Exception, match="429"):
            adapter.complete("sys", "user")

        assert mock_client.messages.create.call_count == 2

    def test_no_retry_on_non_retriable_error(self):
        adapter = self._make_adapter(retries=3)
        non_retriable = ValueError("invalid model name")

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = non_retriable
        adapter.client = mock_client

        with patch("time.sleep"), pytest.raises(ValueError, match="invalid model"):
            adapter.complete("sys", "user")

        # Must not retry — only 1 attempt
        assert mock_client.messages.create.call_count == 1

    def test_max_tokens_flows_to_api_call(self):
        adapter = self._make_adapter()
        adapter.max_tokens = 1024
        good_response = self._make_response("result")

        mock_client = MagicMock()
        mock_client.messages.create.return_value = good_response
        adapter.client = mock_client

        adapter.complete("sys", "user")

        _, kwargs = mock_client.messages.create.call_args
        assert kwargs["max_tokens"] == 1024
