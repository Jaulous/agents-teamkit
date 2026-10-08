# Expert Profile Rubric

Use this rubric to review and improve expert profiles.

## Identity

Good:

- states the business role
- names the domain
- avoids vague "helpful assistant" language

Weak:

- describes broad intelligence instead of a job
- mixes multiple unrelated responsibilities

## Responsibility Boundary

Good:

- lists what the expert owns
- lists what the expert does not own
- names the next expert for downstream work

Weak:

- says "handle the task" without boundary
- lets multiple experts make the same final decision

## Inputs And Outputs

Good:

- names expected inputs
- names exact output sections or fields
- states what to do when inputs are missing

Weak:

- says "analyze the case" with no deliverable

## Collaboration

Good:

- says when to ask another expert
- says what information to include in the message
- uses business reasons for handoff
- distinguishes required replies from optional notifications

Weak:

- relies on the expert to improvise all coordination
- says only "collaborate with other experts when needed"

## Human Input

Good:

- marks conditions that require human decision
- preserves policy conflict and evidence gap triggers

Weak:

- allows the agent to resolve ambiguous business authority on its own

## Evidence

Good:

- requires citations to managed Context Items, published artifacts, external data snapshots, or human decisions
- distinguishes facts from assumptions

Weak:

- allows unsupported final claims

## Protocol Boundary

Good:

- keeps the profile free of protocol commands; collaboration is described as business routes (who, when, what to hand over)
- relies on the adapter-injected protocol for messaging, artifacts, human input, and ledger rules
- permits private scratch work in the expert's own workspace

Weak:

- carries a `TeamKit Rules` section or copies command lists into the profile (adapters strip it and it drifts from the platform)
- embeds the whole global process instead of the expert's own responsibilities

