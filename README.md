# outfit-suggestion-container-agent

Pure-reasoning **agent** in the Agentic Weather App (Style 3: Bedrock
AgentCore). Given a weather summary as input, calls Bedrock's Converse API
directly and returns a short clothing recommendation. No tools, no
Gateway, no MCP client -- the "Act" step *is* the Bedrock call, a single
call per invocation, not a Reason -> Act -> Observe loop, since this
component never needs anything else to finish its job.

Runtime: **AgentCore Runtime** (container, not Lambda) · Python **3.14**
· Dependencies: `bedrock-agentcore`, `boto3`

## Why this one's a container, not a Lambda

Unlike the two weather tools (`current-weather-tool-lambda`,
`forecast-weather-tool-lambda`), which are plain Lambda functions
registered as Gateway targets, this component and the Orchestrator are
genuine **agents** per Style 3's architecture -- they run on **AgentCore
Runtime**, which requires an ARM64 Docker container, not a zip upload.
The Orchestrator calls this agent directly via `invoke_agent_runtime()`,
with no Gateway involved for this particular edge (only the two
deterministic weather tools go through Gateway).

## This repo's relationship to the Style 2 version

This is the Style 3 rebuild of the same reasoning task that exists as a
plain Lambda in a separate repo, `outfit-suggestion-agent` (Style 2). The
two repos are **deliberately named differently** -- this one as
`outfit-suggestion-container-agent` -- specifically so their AWS
resources (ECR repository, IAM role, AgentCore Runtime name here vs.
Lambda function and role name there) never collide, even though they
implement the same component in two different architectures and could
otherwise be deployed into the same AWS account side by side.

The reasoning task itself is identical: `config/instructions.txt` is
carried over unchanged. Only the hosting model changed -- Lambda zip vs.
AgentCore Runtime container -- which is why `src/agent.py`'s business
logic (`fetch_outfit_recommendation`, `_load_instructions`) reads almost
identically to Style 2's `src/handler.py`; what's different is the outer
layer: `BedrockAgentCoreApp`'s `@app.entrypoint` instead of a Lambda
`lambda_handler`, and no `{"statusCode": ..., "body": ...}` envelope --
AgentCore Runtime JSON-serializes whatever the entrypoint returns
directly back to the caller.

## The AgentCore Runtime contract (handled by the SDK, not hand-rolled)

Per AWS's documented requirements, every AgentCore Runtime container
must:

- Expose `POST /invocations` and `GET /ping` on `0.0.0.0:8080`
- Be built for **ARM64** -- AgentCore Runtime does not support x86_64
  containers

`BedrockAgentCoreApp` (the `bedrock_agentcore` SDK) handles both HTTP
endpoints automatically -- `src/agent.py` only has to define the
`@app.entrypoint`-decorated function and call `app.run()`. The Dockerfile
handles the ARM64 + port 8080 requirements.

## Repo layout

```
src/agent.py                   BedrockAgentCoreApp + entrypoint + Bedrock Converse client
tests/test_agent.py            Unit tests (mocked Bedrock calls, no real network calls)
config/instructions.txt        System prompt, carried over from Style 2 unchanged
Dockerfile                     ARM64 container, ships src/ + config/ as siblings
requirements.txt               Runtime deps baked into the image
requirements-dev.txt           Dev-only deps (ruff, pytest) -- never shipped in the image
iam/                            Trust + execution role templates -- see iam/README.md for
                                why these are .template.json, not static files
.github/workflows/             CI (lint+test+coverage) and Deploy (build, push to ECR,
                                create/update AgentCore Runtime, wait for READY, smoke-test)
Makefile                       make check / make build / make run -- see below
```

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
make install
make check    # ruff format + ruff check + pytest --cov (90% floor)
```

Or run the pieces individually: `make format`, `make lint`, `make test`.

## Manual test (no AWS needed for the business logic)

```bash
python3 -c "
from src.agent import handle_payload
print(handle_payload({'inputText': '68F, sunny, light breeze, 10% chance of rain'}))
"
```

This makes a real call to Bedrock (your AWS credentials need
`bedrock:InvokeModel` for `MODEL_ID` in `src/agent.py`). `handle_payload`
is the business logic factored out of the `@app.entrypoint` function
specifically so it's testable this way, without needing a running HTTP
server.

## Running the full container locally

```bash
make build                 # docker buildx build --platform linux/arm64
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_SESSION_TOKEN=...
make run                   # runs on localhost:8080
```

Then in another terminal:

```bash
curl http://localhost:8080/ping

curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"inputText": "68F, sunny, light breeze, 10% chance of rain"}'
```

## Configuring the project

Nothing to configure by hand beyond AWS credentials with Bedrock access
-- `config/instructions.txt` ships baked into the container image (see
`src/agent.py`'s docstring for why this is the primary path, with
`OUTFIT_INSTRUCTIONS` as an optional override for testing prompt changes
without a rebuild).

## AWS setup: fully automatic, first run included

The deploy workflow bootstraps the ECR repository, execution role, and
agent runtime itself.

On the **first** push to `main`, the `deploy` job:

1. Creates the `outfit-suggestion-container-agent` ECR repository if it doesn't exist.
2. Cross-builds the image for **ARM64** using QEMU (GitHub's runners are
   x86_64) and pushes it, tagged both `latest` and with the commit SHA.
3. Checks whether `outfit-suggestion-container-agent-role` exists. If not, creates
   it from `iam/trust-policy.template.json` +
   `iam/execution-role-policy.template.json`, with your AWS account ID
   and region substituted in -- see `iam/README.md` for why these can't
   be static files.
4. Checks whether an agent runtime named `outfit-suggestion-container-agent`
   already exists (`list-agent-runtimes`, filtered client-side by name,
   since there's no server-side name lookup). If not, calls
   `create-agent-runtime`; if it does, calls `update-agent-runtime` with
   the new image.
5. **Polls `get-agent-runtime` until status is `READY`** before smoke
   testing. There's no `aws ... wait` subcommand for this resource (unlike
   the Lambda repos' `function-active-v2`), so this is a hand-rolled
   polling loop -- same underlying race this project hit before with
   Lambda's `ResourceConflictException`: invoking a runtime that's still
   `CREATING`/`UPDATING` fails, so the wait step avoids that entirely.
6. Smoke-tests the live agent with `invoke-agent-runtime` and fails the
   deploy if the response doesn't contain `recommendation`.

On every **subsequent** push, the same flow runs `update-agent-runtime`
instead of `create-agent-runtime` once it finds the existing runtime by
name.

## GitHub Actions setup

- **`ci.yml`** -- lint (`ruff check`), format check (`ruff format --check`),
  tests with a 90% coverage floor. Runs on PRs, non-`main` pushes, and as
  a reusable `workflow_call` from `deploy.yml`.
- **`deploy.yml`** -- on push to `main` (or manual dispatch): reruns CI as
  a gate, builds and pushes the ARM64 image, creates-or-updates the IAM
  role and agent runtime, waits for `READY`, then invokes the **live
  deployed agent** and checks the response.

### Required repo secret

| Secret | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | ARN of an IAM role GitHub assumes via OIDC (trust policy scoped to this repo) |

That role needs permissions covering: ECR (create repository, push
images), IAM (create/read the execution role, `iam:PassRole` to AgentCore),
and `bedrock-agentcore-control`/`bedrock-agentcore` actions
(`CreateAgentRuntime`, `UpdateAgentRuntime`, `GetAgentRuntime`,
`ListAgentRuntimes`, `InvokeAgentRuntime`). This is broader than the
Lambda repos' deploy roles, since there's a container registry and a
different control plane involved -- see AWS's [IAM Permissions for
AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html)
docs for the full reference policy if you want to scope this down further
than a broad `bedrock-agentcore-control:*`/`bedrock-agentcore:*` grant.

## Next component

The AgentCore Gateway itself -- this is what wires `current-weather-tool-lambda`
and `forecast-weather-tool-lambda` in as live MCP tools. After that: the
Orchestrator agent, also on AgentCore Runtime, which is the one component
that calls both the Gateway (for weather data) and this agent directly
via `invoke_agent_runtime()` (for outfit suggestions).
