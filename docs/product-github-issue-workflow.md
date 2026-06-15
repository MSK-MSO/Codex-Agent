# Product GitHub Issue Workflow

Use this workflow when a Teams user reports a bug or suggests a feature for a
supported MSK-MSO product and asks the agent to open, file, or track it in
GitHub.

## Product Routing

Choose the target GitHub repository from the product named in the report:

- `msk-vault`: `MSK-MSO/msk-vault`
- Medplum EHR: `MSK-MSO/medplum-ehr`
- PACS: `MSK-MSO/sdn-pacs`
- RCM: `MSK-MSO/mskmso-rcm`
- PDF Tool / MSK MSO PDF Tools: `MSK-MSO/msk-mso-pdf-tools`

If the report clearly names a legacy or adjacent repository, use the explicitly
named repository instead and mention that routing in the Teams reply. If the
product is ambiguous, ask one short clarifying question before filing.

## Duplicate Check

Before opening a new issue, search existing open and closed GitHub issues in the
target repository for the same bug or feature.

If a matching issue already exists:

1. Do not open a duplicate issue unless the reporter provides clearly distinct
   scope or new evidence that warrants a separate issue.
2. Reply to the reporter with the existing issue link and current state, such as
   open, closed, in progress, blocked, pending human review, or any repository
   project/status state available.
3. Include a brief note about whether the new report appears to match the
   existing issue and any useful next step.
4. If the report includes new useful evidence, add it to the existing issue as a
   comment when appropriate and safe.

## Bug Reports

Open a GitHub issue in the target repository with these required sections:

- Product: the affected product.
- Reporter: the name of the person who reported the bug.
- Description: a concise summary of the bug.
- Steps to reproduce: numbered steps when available; otherwise `Not provided`.
- Expected behavior: what the reporter expected to happen.
- Actual behavior: what actually happened.

Include these optional sections when available:

- Error logs: pasted logs, screenshot text, stack traces, request IDs,
  timestamps, console errors, or network errors.
- Additional context: environment, browser, user role, affected account, recent
  changes, screenshots, frequency, workaround, impact, or severity.

## Feature Ideas

Accept feature ideas for supported products as GitHub issues too.

For minor features, UI improvements, and general quality-of-life requests:

1. Open a GitHub issue directly when the request is understandable and no
   matching issue already exists.
2. Include the product and reporter name.
3. Use the repository's existing enhancement, UI, or QOL labels when available.
4. Include a concise description, user benefit, and any relevant context.

For big features:

1. Question the user with the attached `Grill-me` skill when it is available.
2. If `Grill-me` is not available, ask concise challenge questions covering the
   user/problem, desired outcome, why existing workflows are insufficient, scope
   boundaries, priority, risks, constraints, and dependencies.
3. Open a GitHub issue only after enough detail is collected to make it
   reviewable and no matching issue already exists.
4. Mark the issue as pending human review using the repository's label, project,
   or status conventions when available. If there is no convention, include
   `Pending human review` clearly in the issue body.

## General Procedure

1. Identify whether the report is a bug, minor feature/QOL/UI improvement, or
   big feature.
2. Identify the product and target repository from the report.
3. Identify the reporter from the Teams sender, or from the message text if
   someone is reporting on behalf of another person.
4. Search existing open and closed GitHub issues in the target repository for the
   same bug or feature.
5. If a matching issue exists, report the link and current state to the reporter
   instead of creating a duplicate.
6. Extract relevant details from the message and attachments.
7. If a bug report is missing a required field but enough detail exists to file
   a useful issue, file it and mark missing fields as `Not provided`.
8. If a minor feature request is understandable, file it directly.
9. If a big feature request is vague or broad, use Grill-me questioning before
   filing.
10. Keep PHI, credentials, tokens, and secrets out of GitHub issues. If sensitive
   material is present, summarize only non-sensitive facts and state that
   sensitive details were omitted.
11. Reply in Teams with the created issue link and a short summary of what was
   filed, or with the existing issue link and current state when no new issue was
   created.

## Bug Issue Template

```markdown
## Product
<product>

## Reporter
<name>

## Description
<summary>

## Steps to reproduce
1. <step>

## Expected behavior
<expected>

## Actual behavior
<actual>

## Error logs
<optional or Not provided>

## Additional context
<optional or Not provided>
```

## Feature Issue Template

```markdown
## Product
<product>

## Reporter
<name>

## Feature type
<Minor UI/QOL | Enhancement | Big feature pending human review>

## Description
<summary>

## User benefit
<who benefits and how>

## Proposed behavior
<what should change>

## Scope / constraints
<for big features, include Grill-me answers or Not provided>

## Additional context
<optional or Not provided>
```
