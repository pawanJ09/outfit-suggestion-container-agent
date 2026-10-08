# Why these are `.template.json`, not plain `.json`

Unlike the two weather Lambda repos' IAM files (which only needed
`lambda.amazonaws.com` as a principal -- no account-specific values),
AgentCore Runtime's own trust and execution policies, per AWS's
documentation, **require your AWS account ID and region baked into the
ARNs themselves** (`aws:SourceAccount`, `aws:SourceArn` conditions on the
trust policy; resource ARNs scoped to `/aws/bedrock-agentcore/runtimes/
<agent-name>-*` log groups and `workload-identity-directory/default/
workload-identity/<agent-name>-*` on the execution policy).

There's no account-agnostic way to write these as static files committed
to the repo. `deploy.yml` resolves the placeholders at deploy time:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
sed -e "s/__ACCOUNT_ID__/$ACCOUNT_ID/g" \
    -e "s/__REGION__/$AWS_REGION/g" \
    -e "s/__AGENT_NAME__/$AGENT_NAME/g" \
    iam/trust-policy.template.json > /tmp/trust-policy.json
```

(and the same pattern for `execution-role-policy.template.json`), then
passes the resolved files to `aws iam create-role` /
`aws iam put-role-policy`. See `.github/workflows/deploy.yml` for the
exact commands.

If you need to inspect or hand-create the role yourself, run the `sed`
command above locally first rather than copy-pasting the templates
as-is -- the literal `__ACCOUNT_ID__` placeholders will reject as invalid
ARNs if submitted unresolved.
