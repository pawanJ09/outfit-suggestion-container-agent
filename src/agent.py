"""
outfit-suggestion-container-agent (Style 3: Bedrock AgentCore)

Pure-reasoning agent in the Agentic Weather App, hosted on AgentCore
Runtime. Given a weather summary as input, calls Bedrock's Converse API
directly and returns a short clothing recommendation. No tools, no
Gateway, no MCP client -- this agent never calls anything else to finish
its job, so there's no Reason -> Act -> Observe loop here, just a single
Bedrock call per invocation.

Named "-container-agent" (rather than reusing the Style 2 repo's exact
name, outfit-suggestion-agent) specifically so the two repos never
collide on AWS resource names -- ECR repository, IAM role, and AgentCore
Runtime name here vs. Lambda function and role name there. Same
component, same reasoning task, deliberately different identifiers.

This is the Style 3 rebuild of the same component that exists as a plain
Lambda in Style 2 (weather-orchestrator-agent calls it there via
boto3 lambda.invoke()). The reasoning task is identical --
config/instructions.txt is carried over unchanged -- only the hosting
model changed: instead of a Lambda zip, this ships as a container to
AgentCore Runtime, invoked via invoke_agent_runtime() by the
Orchestrator Runtime, per Style 3's architecture (direct agent-to-agent
call, no Gateway involved for this particular edge).

AgentCore Runtime contract (handled by the bedrock_agentcore SDK, not
hand-rolled here):
    - Exposes POST /invocations and GET /ping on 0.0.0.0:8080
    - The @app.entrypoint-decorated function receives the parsed JSON
      payload plus a RequestContext (session id, headers, etc)
    - Whatever the entrypoint returns is JSON-serialized back to the caller

Expected payload shape: {"inputText": "<plain-text weather summary>"}
-- same field name Style 2 used, so the Orchestrator's tool-call shape
for get_outfit_suggestion doesn't need to change across styles.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import RequestContext

app = BedrockAgentCoreApp()

# Placeholder -- confirm the current Claude Haiku model ID available to
# Bedrock in your region with `aws bedrock list-foundation-models
# --query "modelSummaries[?contains(modelId, 'haiku')]"` before deploying.
# Carried over from the Style 2 version of this component; same caveat
# applies since this still can't be verified live from here.
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

MAX_TOKENS = 300
TEMPERATURE = 0.4


class OutfitRecommendationError(Exception):
    """Raised when Bedrock can't be reached or returns an unusable response."""


def _load_instructions() -> str:
    """
    Primary path, both in the deployed container and locally:
    config/instructions.txt, read straight off disk. Unlike the Lambda
    repos, there's no zip-with-just-handler.py constraint here -- the
    Dockerfile COPYs the whole repo (src/ and config/ as siblings) into
    the image, so this file is simply present at runtime, in the
    container exactly as it is in the repo.

    Override path: if OUTFIT_INSTRUCTIONS is set (optionally passed via
    create-agent-runtime's --environment-variables), it takes precedence
    over the file -- useful for testing a prompt change against the live
    runtime without rebuilding and redeploying the image.
    """
    env_value = os.environ.get("OUTFIT_INSTRUCTIONS")
    if env_value:
        return env_value

    local_path = Path(__file__).resolve().parent.parent / "config" / "instructions.txt"
    if local_path.exists():
        return local_path.read_text()

    raise OutfitRecommendationError(
        "No OUTFIT_INSTRUCTIONS env var set and config/instructions.txt not "
        "found locally. In the deployed container, OUTFIT_INSTRUCTIONS "
        "should always be set -- if you're seeing this in production, the "
        "image was built without it."
    )


def fetch_outfit_recommendation(input_text: str) -> str:
    """Call Bedrock's Converse API with the system prompt + weather text."""
    instructions = _load_instructions()
    client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))

    try:
        response = client.converse(
            modelId=MODEL_ID,
            system=[{"text": instructions}],
            messages=[{"role": "user", "content": [{"text": input_text}]}],
            inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": TEMPERATURE},
        )
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: any
        # botocore/boto3 exception here means "Bedrock call failed," and
        # the caller only needs to know that, not which specific
        # exception class botocore raised.
        raise OutfitRecommendationError(f"Bedrock Converse call failed: {exc}") from exc

    try:
        return response["output"]["message"]["content"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise OutfitRecommendationError(f"Bedrock response had an unexpected shape: {exc}") from exc


def handle_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    The actual business logic, factored out of the @app.entrypoint
    function so it can be unit tested directly -- calling through
    BedrockAgentCoreApp's HTTP layer in tests would mean spinning up a
    real server, which buys nothing for a function this simple.
    """
    input_text = payload.get("inputText") if isinstance(payload, dict) else None
    if not input_text or not isinstance(input_text, str):
        return {"error": "Missing or invalid 'inputText' in the request"}

    try:
        recommendation = fetch_outfit_recommendation(input_text)
    except OutfitRecommendationError as exc:
        return {"error": str(exc)}

    return {"recommendation": recommendation}


@app.entrypoint
def invoke(payload: dict[str, Any], context: RequestContext | None = None) -> dict[str, Any]:
    return handle_payload(payload)


if __name__ == "__main__":
    app.run()
