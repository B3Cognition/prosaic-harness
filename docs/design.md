# Prosaic Harness v0.1

The working-tree revision supersedes the initial limitations below. See
[hardening.md](hardening.md) for v2 recovery, validators, bindings, budgets and
the coordinated Runtime release setup.

Prosaic defines agents; Prosaic Runtime executes one invocation; this harness
owns sequencing, validation, limits, evidence, and recovery. Echelon inspired
the separation of deterministic control from agent output. No Echelon modules,
state formats, or result markers are dependencies.

Workflows are YAML maps of agent, gate, pause, and finish steps. Agent results
are JSON validated against local JSON Schema. Gates compare a selected field
to a literal. All transition targets are declared; no expression evaluation.
Loops are ordinary graph edges bounded by visits and a whole-run call limit.
Human choices are named values declared by the pause step. No automatic agents
spawn agents. V0.1 exposes read tools only; filesystem writes are controller-owned.

A run has one locked atomic run.json authority and one durable receipt per
invocation. The pending invocation is saved before contacting the runtime.
Its receipt is saved before advancing state. Resume adopts a saved receipt;
an invocation without a receipt is interrupted and needs explicit retry consent.
That retry consumes another call slot. Model calls have no exactly-once guarantee.
There are no external publication effects in v0.1. Checkpointing a result before
advancing state avoids silently losing accepted work. Local run history records
transitions and pause decisions; receipts contain output, usage, and events.

Workflow content, resolved schemas, runtime configuration, and inspected prose
are fingerprinted. Resume rejects changed definitions. Runtime credentials are
read from the environment or configured secret file, never copied into run state.
Inputs, agent outputs, and model events can contain sensitive information; the
run directory is evidence with the same confidentiality needs as the inputs.

Delivery is a public Apache-2.0 Python repository, first-run documentation,
single-agent and review/repair blueprints, offline controller tests, and a live
TokenProxy demonstration. Echelon remains unchanged. Provider adapters and
domain-specific checks can be introduced later through explicit interfaces.
