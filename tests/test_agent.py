# import os
from unittest.mock import MagicMock, patch

import pytest

from src import agent


def _bedrock_response(text: str) -> dict:
    return {"output": {"message": {"content": [{"text": text}]}}}


class TestLoadInstructions:
    def test_reads_from_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("OUTFIT_INSTRUCTIONS", "test instructions from env")
        assert agent._load_instructions() == "test instructions from env"

    def test_falls_back_to_local_file(self, monkeypatch):
        monkeypatch.delenv("OUTFIT_INSTRUCTIONS", raising=False)
        text = agent._load_instructions()
        assert "Outfit Suggestion agent" in text

    def test_raises_when_neither_available(self, monkeypatch):
        monkeypatch.delenv("OUTFIT_INSTRUCTIONS", raising=False)
        fake_missing_path = MagicMock()
        fake_missing_path.exists.return_value = False

        with patch("src.agent.Path") as mock_path_cls:
            resolved = mock_path_cls.return_value.resolve.return_value
            resolved.parent.parent.__truediv__.return_value.__truediv__.return_value = (
                fake_missing_path
            )
            with pytest.raises(agent.OutfitRecommendationError):
                agent._load_instructions()


class TestFetchOutfitRecommendation:
    @patch("src.agent.boto3.client")
    def test_success_returns_text(self, mock_boto_client, monkeypatch):
        monkeypatch.setenv("OUTFIT_INSTRUCTIONS", "test instructions")
        mock_client = MagicMock()
        mock_client.converse.return_value = _bedrock_response("Wear a light jacket.")
        mock_boto_client.return_value = mock_client

        result = agent.fetch_outfit_recommendation("68F, sunny, light breeze")

        assert result == "Wear a light jacket."
        mock_client.converse.assert_called_once()
        call_kwargs = mock_client.converse.call_args.kwargs
        assert call_kwargs["modelId"] == agent.MODEL_ID
        assert call_kwargs["system"] == [{"text": "test instructions"}]

    @patch("src.agent.boto3.client")
    def test_bedrock_exception_raises_outfit_error(self, mock_boto_client, monkeypatch):
        monkeypatch.setenv("OUTFIT_INSTRUCTIONS", "test instructions")
        mock_client = MagicMock()
        mock_client.converse.side_effect = RuntimeError("throttled")
        mock_boto_client.return_value = mock_client

        with pytest.raises(agent.OutfitRecommendationError):
            agent.fetch_outfit_recommendation("68F, sunny")

    @patch("src.agent.boto3.client")
    def test_unexpected_response_shape_raises_outfit_error(self, mock_boto_client, monkeypatch):
        monkeypatch.setenv("OUTFIT_INSTRUCTIONS", "test instructions")
        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {"message": {"content": []}}}
        mock_boto_client.return_value = mock_client

        with pytest.raises(agent.OutfitRecommendationError):
            agent.fetch_outfit_recommendation("68F, sunny")


class TestHandlePayload:
    @patch("src.agent.fetch_outfit_recommendation")
    def test_success_returns_recommendation(self, mock_fetch):
        mock_fetch.return_value = "Wear a light jacket."

        result = agent.handle_payload({"inputText": "68F, sunny, light breeze"})

        assert result == {"recommendation": "Wear a light jacket."}
        mock_fetch.assert_called_once_with("68F, sunny, light breeze")

    def test_missing_input_text_returns_error(self):
        result = agent.handle_payload({})
        assert "error" in result

    def test_non_string_input_text_returns_error(self):
        result = agent.handle_payload({"inputText": 12345})
        assert "error" in result

    def test_non_dict_payload_returns_error(self):
        result = agent.handle_payload("not a dict")
        assert "error" in result

    @patch("src.agent.fetch_outfit_recommendation")
    def test_upstream_failure_returns_error(self, mock_fetch):
        mock_fetch.side_effect = agent.OutfitRecommendationError(
            "Bedrock Converse call failed: boom"
        )

        result = agent.handle_payload({"inputText": "68F, sunny"})

        assert "error" in result


class TestInvokeEntrypoint:
    @patch("src.agent.handle_payload")
    def test_invoke_delegates_to_handle_payload(self, mock_handle):
        mock_handle.return_value = {"recommendation": "Wear a light jacket."}

        result = agent.invoke({"inputText": "68F, sunny"}, context=None)

        assert result == {"recommendation": "Wear a light jacket."}
        mock_handle.assert_called_once_with({"inputText": "68F, sunny"})
