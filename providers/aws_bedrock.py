import asyncio
import json
import logging
from typing import AsyncGenerator

from .base import BaseProvider
from config import config

logger = logging.getLogger(__name__)


class AWSBedrockProvider(BaseProvider):
    """AWS Bedrock provider — Claude, Titan, Llama via AWS."""

    def __init__(self):
        import os
        cfg = config.providers.get("aws_bedrock")
        self._region      = os.environ.get("AWS_DEFAULT_REGION")     or cfg.get("region", "us-east-1")
        self._access_key  = os.environ.get("AWS_ACCESS_KEY_ID")      or cfg.get("access_key_id", "")
        self._secret_key  = os.environ.get("AWS_SECRET_ACCESS_KEY")  or cfg.get("secret_access_key", "")
        self._default_model = os.environ.get("BEDROCK_MODEL")        or cfg.get("model", "anthropic.claude-3-5-sonnet-20241022-v2:0")
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._region,
                aws_access_key_id=self._access_key or None,
                aws_secret_access_key=self._secret_key or None,
            )
        return self._client

    @property
    def name(self) -> str:
        return "aws_bedrock"

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[dict, None]:
        client = self._get_client()

        # separate system from messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        conv_msgs = [m for m in messages if m.get("role") != "system"]
        system_text = "\n\n".join(m.get("content", "") for m in system_msgs)

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 8096,
            "messages": conv_msgs,
        }
        if system_text:
            body["system"] = system_text
        if tools:
            body["tools"] = [self._convert_tool(t) for t in tools]

        def _invoke():
            if stream:
                return client.invoke_model_with_response_stream(
                    modelId=self._default_model,
                    body=json.dumps(body),
                )
            return client.invoke_model(
                modelId=self._default_model,
                body=json.dumps(body),
            )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _invoke)

        full_text = ""
        if stream:
            # Track tool_use blocks across streaming events
            tool_blocks: dict[int, dict] = {}
            current_block_idx: int | None = None
            current_block_type: str | None = None

            for event in response["body"]:
                chunk = json.loads(event["chunk"]["bytes"])
                t = chunk.get("type", "")

                if t == "content_block_start":
                    block = chunk.get("content_block", {})
                    idx = chunk.get("index", 0)
                    current_block_idx = idx
                    current_block_type = block.get("type")
                    if current_block_type == "tool_use":
                        tool_blocks[idx] = {
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "arguments": "",
                        }

                elif t == "content_block_delta":
                    delta = chunk.get("delta", {})
                    delta_type = delta.get("type")
                    if delta_type == "text_delta":
                        text = delta.get("text", "")
                        full_text += text
                        yield {"type": "text", "content": text}
                    elif delta_type == "input_json_delta" and current_block_idx in tool_blocks:
                        tool_blocks[current_block_idx]["arguments"] += delta.get("partial_json", "")

                elif t == "content_block_stop":
                    if current_block_idx in tool_blocks:
                        tc = tool_blocks.pop(current_block_idx)
                        try:
                            args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                        except json.JSONDecodeError:
                            args = {"raw": tc["arguments"]}
                        yield {
                            "type": "tool_call",
                            "id": tc["id"],
                            "name": tc["name"],
                            "arguments": args,
                        }
                    current_block_idx = None
                    current_block_type = None

                elif t == "message_stop":
                    break
        else:
            result = json.loads(response["body"].read())
            for block in result.get("content", []):
                if block.get("type") == "text":
                    full_text += block["text"]
                    yield {"type": "text", "content": block["text"]}
                elif block.get("type") == "tool_use":
                    yield {
                        "type": "tool_call",
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "arguments": block.get("input", {}),
                    }

        yield {"type": "done", "content": full_text}

    def _convert_tool(self, tool: dict) -> dict:
        """Convert OpenAI-style tool schema to Anthropic/Bedrock format."""
        fn = tool.get("function", tool)
        return {
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        }

    async def count_tokens(self, messages: list[dict]) -> int:
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return sum(len(enc.encode(str(m.get("content", "")))) for m in messages)
        except Exception:
            return sum(len(str(m.get("content", ""))) // 4 for m in messages)

    async def is_healthy(self) -> bool:
        try:
            import boto3
            client = boto3.client(
                "bedrock",
                region_name=self._region,
                aws_access_key_id=self._access_key or None,
                aws_secret_access_key=self._secret_key or None,
            )
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: client.list_foundation_models(maxResults=1))
            return True
        except Exception as e:
            logger.debug(f"aws_bedrock health check failed: {e}")
            return False

    def get_available_models(self) -> list[str]:
        return [self._default_model]
