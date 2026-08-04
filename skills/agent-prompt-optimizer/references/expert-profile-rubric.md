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

## TeamKit Rules

Good:

- requires command-mediated messaging and artifact publication
- requires command-mediated Context Item, artifact, specialized data snapshot, and human input requests when those actions occur
- uses Topic and Graph as shared coordination state instead of embedding the whole flow in every expert profile
- forbids direct edits to ledgers and canonical shared files
- permits private scratch work in the expert's own workspace

Weak:

- tells the expert to "update the shared files" without naming commands
- lets the expert append to `messages.jsonl` manually
