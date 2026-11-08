# Reusable context packs for Prosaic Harness

Date: 2026-11-08. Status: proposed for maintainer review; no implementation.

Initial builder feasibility review completed on 2026-11-08. A subsequent maintainer
request removed the proposed requirement to send all guard facts to the model.
The revised design separates authoritative validation facts from model-visible
evidence, with explicit per-guard access and a versioned proof. A subsequent
adversarial review found historical authorization and validator-feedback disclosure
gaps; the contracts below address them along with recovery, identity, and fitting
edge cases. Final independent re-review found no consequential design blockers.
Review evidence is recorded in the [companion review document](2026-11-08-context-packs-review.md). Reviews
establish design clarity, not implementation or model-quality validation.

## Decision and intent

Add an optional evidence-composition API to Harness. A context pack is an
immutable, bounded, source-linked selection of evidence for one agent invocation.
It can contain exact excerpts, structured records, and a small index of additional
evidence available through an explicitly granted read tool. The same pack machinery
serves an ordinary conversation, a workflow specialist, or a standalone host.

Harness chooses and freezes evidence. Runtime remains the sole owner of native
request encoding, token counting, history fitting, and model/tool execution.
Consumers retain retrieval, permissions, domain semantics, and source freshness.
Core keeps its existing Markdown kinds and distribution contracts.

This restores Echelon's useful idea—give each agent the evidence its assignment
needs—without importing Echelon's phase engine, filenames, memory system, or prompt
policies. Modernization means evidence selection, progressive disclosure,
provenance, reproducibility, and measured quality. It does not mean introducing a
mandatory vector database or hiding more inference inside preparation.

The user requested a reusable Harness design grounded in Echelon and current
practice. Choices marked **design choice** below are recommendations from this
review, not preferences already approved by the user. Ask Cerebro is a motivating
consumer, not a source of generic product requirements.

## Reviewed baseline

Local Harness and Runtime working directories lag the releases in the feedback.
The design therefore uses the released GitHub tags **Harness v0.9.12**, **Runtime
v0.9.17**, and Core **0.5.0**, rather than treating the checked-out branches as the
complete product. Existing unrelated working-tree edits must be preserved.

Echelon was reviewed at local clean commit
`ae40bc966a0450996630c3998531d483215821d4`, including:

| Source | What it establishes |
| --- | --- |
| `src/harness/agent_context.py` and `tests/unit/test_agent_context.py` | Selector parsing; journal filters; phase-specific criticality; file/directory rendering; byte limits; omission and budget reports. |
| `src/harness/squad_executors.py` | Executor-owned assembly, per-agent context declarations, and separate bounded/legacy rendering. |
| `src/harness/ralph.py`, especially `_build_context_agent_sections()` and `_write_build_agent_context_files()` | Structured build-section index and materialized role-specific packs. |
| `src/echelon/context_builder.py` and its unit tests | Frozen discovery inputs, prior/current context, memory reconciliation, and prevention of fallback to ambient discovery. |
| `templates/context-pack.md` | Original per-role selection intent, expressed as an application-specific guide. |

These sources are evidence for a redesign, not modules to import or automatically
vendor. No Echelon tests were executed during this design review.

### Keep, replace, leave with consumers

| Echelon behavior | Prosaic decision |
| --- | --- |
| Per-role evidence declarations and deterministic executor assembly | Keep as named host-owned pack specifications. |
| Filtered journals and structured section maps | Keep the underlying idea using bounded records, explicit selectors, and exact locators. |
| Frozen discovery capture with no ambient fallback | Keep; prepare from supplied snapshots only. |
| Omission reports and explicit source indexes | Keep, with strict bounds on indexes as well as bodies. |
| `phase1-why2`, `spec.md`, `state.json`, named specialist profiles | Consumer policy; no special cases in Harness. |
| String expressions mixing paths, comments, and `[phase=...]` filters | Replace with typed declarations and a closed serialized schema. |
| Reading whole files or recursively enumerating directories before applying limits | Replace with bounded capture before composition; no implicit filesystem discovery. |
| Byte/4 token estimates | Never use for admission; reuse qualified Runtime counters. |
| `must_preserve` paths that permit legacy fallback; manifests allowed above a nominal cap | Required evidence must fit or fail. Every encoded structure has a hard bound. |
| Prefix truncation as the general file policy | Select whole evidence units or explicit excerpts; never silently cut a JSON record or a mandatory clause. |
| MemPalace reconciliation and prior-spec ranking | Remain domain adapters; derived evidence retains source links and revision metadata. |

The current published SDK already has `context_assembly_v1`, `ContextPolicy`,
`TokenCounterRegistry`, `ContextSelection`, and cumulative assembly-work records.
Harness persists the frozen history suffix and reports in context-enabled sessions.
Those features fit conversation history; they do not select arbitrary evidence.
[Runtime baseline](https://github.com/B3Cognition/prosaic-runtime/blob/v0.9.17/docs/conversations.md),
[Harness baseline](https://github.com/B3Cognition/prosaic-harness/blob/v0.9.12/docs/conversations.md).

Two integration gaps are material. Ordinary `Conversation.send()` currently builds
a turn with `inputData=None`; it has no public host evidence argument. In workflow
execution, guarded agents use `prepare_turn()`/`turn()`, while ordinary agents use
`run()` and rendered arguments. Context packs must address both gaps explicitly;
adding a helper that returns a large string would not complete the feature.
[Conversation source](https://github.com/B3Cognition/prosaic-harness/blob/v0.9.12/src/prosaic_harness/conversation.py),
[workflow source](https://github.com/B3Cognition/prosaic-harness/blob/v0.9.12/src/prosaic_harness/engine.py).

## Research and what it changes

Research cut-off: 2026-11-08. The following are primary sources. Their results do
not establish that one context strategy is best for all Prosaic models or tasks.

| Source | Observation | Design consequence |
| --- | --- | --- |
| [Anthropic, effective context engineering, 2025-09-29](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents) | Context is curated over an agent's trajectory; retrieval can load relevant material when needed. | Compose at invocation boundaries; support a small initial pack and controlled later reads. |
| [Anthropic, advanced tool use, 2025-11-24](https://www.anthropic.com/research/advanced-tool-use) | Deferred tool discovery and bounded intermediate data reduce upfront context pressure. | Apply progressive disclosure to evidence. Tool discovery itself remains a distinct Runtime capability. |
| [Anthropic, context engineering for Claude 5 generation models, 2026-07-24](https://claude.dev/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models/) | The authors report simplifying instructions and loading richer references as needed. | Do not transplant Echelon's long procedural prompts or assume every model needs identical scaffolding. |
| [Manus, production lessons, 2025-07-18](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) | Stable prefixes, deterministic serialization, and external evidence can help context efficiency. | Keep pack serialization stable and volatile bookkeeping out of model-visible prefixes; make no cache-hit promise. |
| [Chroma Context-1, 2026-03-26](https://www.trychroma.com/research/context-1) | Multi-hop search and selective context editing are useful in the authors' retrieval setting. | Accept evidence gathered through multiple searches; do not make one initial static pack the only possible evidence source. |
| [Recursive Language Models, revision 2026-05-11](https://arxiv.org/abs/2512.24601v3) | The paper explores examining large external inputs programmatically and through recursive calls. | Keep evidence outside the prompt addressable. Recursive inference is a separate orchestration experiment, not a requirement of packs. |
| [ACE, revision 2026-03-29](https://arxiv.org/abs/2510.04618v3) | Incrementally maintained context can avoid information loss from repeated rewriting in the studied tasks. | Keep originals and derivation links. No recursive summary-of-summary replacement of authoritative evidence. |
| [Long-horizon search study, revision 2026-10-25](https://arxiv.org/abs/2606.29718v3) | The authors find failures before the context limit and model-dependent effects from management methods. | Evaluate task completion and evidence use, not merely successful fitting or token reduction. |
| [Attention competition preprint, 2026-11-03](https://arxiv.org/abs/2611.04169v1) | On small open models in retrieval experiments, competing evidence matters substantially. This is recent, limited evidence. | Include distractor and conflicting-revision cases in qualification; do not turn a small-model result into a universal pruning rule. |
| [OpenAI, compaction documentation, accessed 2026-11-08](https://developers.openai.com/api/docs/guides/compaction) | Provider-native compaction may carry opaque encrypted state between requests. | Keep provider state separate from portable evidence packs. Packs neither decode it nor claim to replace it. |

**Design choice:** use deterministic, evidence-preserving composition by default.
Leave retrieval/reranking, learned context editing, and summarization behind host
tools or explicit workflow steps. They may produce candidate evidence; they do
not silently execute inside the pack builder. No new framework dependency.

## Scope and alternatives

The first complete release includes pure composition, Runtime fitting integration,
separate authoritative guard facts, durable conversation and workflow integration,
optional snapshot reads, reporting, and installed-package qualification. Internal
milestones can land separately, but do not advertise the feature as complete after
the pure builder alone.

| Approach | Assessment |
| --- | --- |
| Copy Echelon's assemblers and replace phase names | Fast initial port; retains filesystem assumptions, special cases, and weak budget semantics. Reject. |
| Introduce an autonomous context agent, memory database, and mandatory retriever | Potential research direction; adds inference, effects, and operational requirements to admission. Reject as the generic default. |
| Small typed evidence layer in Harness, backed by existing Runtime admission | Recommended: application-neutral, testable without models, usable with static files or live domain tools. |

Goals: per-agent relevance; exact source references; explicit missing evidence;
bounded computation/storage; repeatable preparation; safe restart; optional loading
of more captured evidence; no changes for consumers that do not opt in.

Non-goals: agent-to-agent calls, a new workflow engine, a universal RAG service,
MCP client implementation, automatic long-term memory, automatic tool selection,
provider-native compaction, multimodal packs, arbitrary executable selectors, or
proving that a model's answer follows from a citation.

## Ownership and execution path

```text
consumer retrieval / explicit file capture / accepted workflow outputs
                             |
                    bounded source snapshots
                             |
          Harness: select -> project -> deduplicate -> freeze
                             |
             ordered candidate packs + omission reports
                             |
        Runtime: native encoding + token/history admission
                             |
         Harness: persist selected pack and pending attempt
                             |
                 Runtime: model / granted tools
                             |
             receipt -> Harness checkpoint adoption
```

| Layer | Responsibility |
| --- | --- |
| Core | Existing prose inspection/resources. No context execution, new artifact kind, or dependency on Harness. |
| Harness | Pack contracts, composition, source bindings, per-step/turn selection, snapshot persistence, recovery, and optional reader construction. |
| Runtime | Exact native payloads, qualified token counters, shared fitting budgets, separated guard input views, continuations, tool grants and execution. No imports of Harness pack types. |
| Host | Authenticate and authorize source capture/use; supply candidates and revisions; choose pack specifications and domain ranking. |
| Integration Lab | Exercise installed public APIs, source freshness, failure/restart cases, and separate real-model evaluations. |

Pack content always enters unprivileged `input_data`/tool results. It is never
appended to the agent's instructions or bundled resources. A policy document inside
a pack is evidence about policy; executing host policy remains in admitted code.
Escaped envelopes preserve structure but cannot guarantee prompt-injection immunity.

## Public contracts

All names in this section are **proposed APIs**. Python uses snake_case; new wire
records use camelCase, closed fields, finite JSON, explicit versions, and bounded
ownership copies. None deserialize Python, imports, callbacks, paths to execute,
or credentials. Pack types live in `prosaic_harness.context_packs` and are exported
from Harness's public package.

### Evidence and source snapshots

`ContextItem` is one indivisible selectable evidence unit:

- `item_id`: stable host ID, unique within a source snapshot.
- `source_alias`, `source_revision`: host-bound source identity and immutable
  revision. Aliases are bounded labels, not URLs to fetch.
- `content`: UTF-8 text or bounded plain JSON; `content_sha256` is computed by the
  SDK from owned content, never accepted as proof from a model.
- `label`: optional bounded host-supplied discovery label (128 UTF-8 bytes);
  content kind is SDK-derived as `text` or `json`. An absent label displays only
  the opaque citation ID, never an invented summary or leaked source path.
- `locator`: `whole`, a UTF-8 byte range `[start,end)`, a JSON Pointer, or a
  host-defined opaque record ID. Byte locators refer to a captured source digest;
  no implicit Unicode or newline normalization.
- `labels`: bounded scalar metadata for exact selection; no free-form query language.
- `derived_from`: optional source/item/digest links for summaries or projections.
  A derived summary is identified as derived; it is not equivalent to the original.

`ContextSnapshot` contains a bounded collection of owned items, source descriptors,
optional per-source ranked item-ID lists, and a private binding to the admitted
host scope. Item IDs are unique within each source alias; selectors always address
the pair `(source_alias, item_id)`. Each source descriptor includes capture outcome
(`complete`, `partial`, or `unavailable`) and revision, so a completed empty lookup
can be distinguished from missing evidence. Ranking lists contain distinct IDs
present in their source; unranked items follow in stable ID order. These lists
are per-invocation host data and participate in snapshot identity. V1 construction takes
already captured values, performs no I/O, and executes no resolver/ranker/model
callbacks. A source helper may turn accepted workflow outputs into items, retaining
their existing IDs, hashes, dependencies, and freshness checks.

V1 does not ship a general directory crawler or remote loader. A file consumer
captures explicitly permitted bytes before construction and supplies the digest,
revision, and locator; later adapters must bound reads/enumeration before allocation.
Cerebro can supply API/database records without manufacturing a filesystem.

There is no universal freshness TTL. Host use-authorization admits a bounded
logical invocation before dispatch and is checked again for each deferred read.
It receives the applicable captured revisions and may reject them; it cannot
replace bytes or return a refreshed snapshot. A new source revision requires
explicit recapture and a new operation. Invocation authorization covers its provider
continuations until its admitted deadline, subject to host cancellation; this is
not a promise of instantaneous revocation during an in-flight request. A new
invocation, including an explicit retry, requires new authorization. Reusing old
evidence in history also requires current use authorization, as specified below.
Inspecting retained evidence requires current read authorization without recapture.

### Pack declarations and bindings

`ContextPackSpec` has a host ID/version and ordered slots. A slot declares:

- a source alias and optional exact item IDs;
- optional label filters: union of values within a field, intersection across
  fields; no regex, glob expansion, SQL, JSONPath, templates, or Python expressions;
- `required` and finite `min_items`/`max_items`; no silent disappearance of a
  required selector or silent clipping when its upper cardinality is exceeded;
- integer priority, with deterministic ties by slot order, then explicit
  slot `item_ids` order, otherwise captured source ranking, otherwise stable item ID;
- a representation: `whole`, explicit UTF-8 range, or explicit JSON Pointer;
- availability: `inline` or `discoverable`. Required slots must be inline.

An optional match over `max_items` fails with `selectionLimit`; the host must narrow
the source/selector. This avoids claiming complete results after an arbitrary cut.
Ranking is not a callback in the builder. A host can supply a pre-ranked list of
item IDs from its own search/reranker; that order is captured in the snapshot.
An explicit ID list is ordered, unique, and authoritative within that slot. Higher
integer priority is kept first; optional removals reverse that resolved order.
Registered specifications remain immutable across turns: query-specific IDs and
retrieval rankings belong in the source snapshot, not in a mutated registered spec.
A host can capture just the requested service in a `service` source and reuse the
same spec for a different service on the next turn. Explicit slot IDs are for
stable host declarations, not a required mechanism for per-question routing.

Single-item slots default to `min_items=1,max_items=1` when required and
`min_items=0,max_items=1` otherwise. A collection slot requires an explicit maximum;
`0 <= min_items <= max_items <= max_captured_items` and `max_items >= 1`.
Optional slots must use `min_items=0`; a positive minimum requires `required=True`.
For a required slot, `min_items=0` permits a completed empty result but still
requires a `complete` source descriptor. A nonempty `partial` source can be selected
only by an explicit `allow_partial=True` declaration; the coverage report and model
envelope must retain that status. `unavailable` never satisfies a required slot.
Invalid representation selectors or cardinality contradictions fail admission.

`ContextPackBindings` registers admitted specs and source aliases, a scope-binding
identity, and a versioned `authorize_use` host callback. Construction and pure
composition do not call it; invocation/deferred-read admission does. Its descriptor
is sealed, its function is never serialized, and failures deny use. All operations
require deadlines/cancellation; callbacks must be bounded trusted host code.

Authorization answers whether a captured selection may be used now. Neither a
pack ID nor a digest grants access. Scope includes application, environment,
tenant, actor or explicit shared-principal policy, and session/run namespace.
Standalone callers must supply an equivalent explicit scope binding.

`ContextPackPolicy` owns finite byte/item/variant/storage limits. It does not
duplicate Runtime's token policy or tool grants.

### Frozen results

`ContextPackCandidates`, returned by `ContextPacker.compose()`, owns the immutable
snapshot/spec, ordered candidate evidence envelopes, and selection reports. It has
a `candidateIdentity` over that complete deterministic plan. `Conversation.send()`
accepts this type; it does not accept an arbitrary final envelope. Runtime chooses
an admitted index. `ContextPacker.select(candidates, index, envelope_digest)` checks
that choice against owned candidate bytes and returns a `PreparedContextPack`;
this helper has no callbacks and does not itself authorize execution.

`PreparedContextPack` owns:

- the immutable bounded source snapshot needed for replay and permitted later reads;
- selected representations, exact content hashes and locators;
- an ordered `input_data` evidence envelope and bounded discovery index;
- an omission report with safe reason codes and declared required-slot coverage;
- a reference binding spec, snapshot, selection, representation/render version,
  and final model-visible envelope identities.

Separate identities have separate meanings. `snapshotIdentity` identifies retained
captured inputs, `packIdentity` identifies a chosen evidence projection, and
Runtime's existing `contextIdentity` identifies the admitted invocation. In the
new separated-input mode it binds both the model projection and private guard
facts; the model input digest remains separately identifiable.
None identifies truth or establishes permission. A source change, different
selection, or renderer version changes the appropriate identity.

Canonical pack JSON is `json-sort-keys-utf8-v1`: sorted keys, UTF-8, compact
separators, finite numbers, no normalization of string values. Arrays retain their
specified order. Unordered collections are sorted before encoding. Reject duplicate
keys and Unicode surrogate values. Timing, dispatch IDs, and diagnostic timestamps
are outside semantic identity; a source capture time matters only if the host
explicitly includes it in source semantics. Content is retained in owned encoded
bytes, not exposed through mutable nested dict aliases.

Identity envelopes exclude their own digest field when hashing. In particular,
the model-visible evidence envelope does not embed a `packIdentity` that hashes
itself: stable citation IDs identify entries, and a private outer reference binds
the final envelope digest. Source-level digests are host capture provenance;
the SDK separately computes hashes over every retained item/representation. An
excerpt hash alone does not verify the uncaptured remainder of a source document.

Deduplicate only identical source alias/identity + source revision + item ID +
source locator + representation locator + content digest within the same admitted
scope. Equal revision strings from different sources never establish identity.
A duplicate retains all slot/citation aliases
and the strictest required status. Never merge evidence solely because text looks
similar; conflicting revisions and independent sources remain distinguishable.

Citation IDs are SDK-derived opaque IDs over this complete evidence identity;
host record IDs alone are not globally unique citations. Source locators identify
the captured unit's provenance; representation locators select within that owned
unit. UTF-8 ranges use byte offsets with strict code-point boundaries and
`0 <= start <= end <= byte_length`. JSON Pointers use RFC 6901 escapes, must resolve
within the owned JSON value, and never execute expressions. A reader may narrow a
permitted representation but cannot widen it to the parent source. Exact JSON
values and UTF-8 bytes are retained without implicit normalization.

## Composition and fitting

### Pure composition

1. Validate/copy the input under capture limits before recursive processing.
2. Resolve each slot only against supplied snapshot items; enforce cardinality.
3. Project exact representations and compute SDK-owned hashes/locators.
4. Deduplicate exact identities while retaining coverage and attribution.
5. Form the mandatory base: required evidence plus a bounded discovery index and
   coverage header. If this cannot meet the pack byte cap, fail before dispatch.
6. Order optional inline units by priority. Starting with the mandatory base, add
   whole units in that order when the resulting encoded evidence envelope fits
   its byte cap. Skip an optional unit that does not fit, report `byteLimit`, and
   consider the next unit; an oversized optional unit does not fail the pack.
   This produces the richest byte-admitted variant. Produce successively smaller
   variants by removing whole lowest-priority units in stable groups, ending at
   the mandatory base. With two to eight allowed variants, group size is
   `ceil(included_optional_count / (max_variants - 1))` when needed; deduplicate
   equal variants. With `max_variants=1`, use the mandatory base only and report
   optional units as omitted by the variant budget. Zero optional units produces
   one variant. No implicit semantic compression or cut inside a unit.
7. Count every encoded variant against total preparation byte/work limits. Reports
   include omitted/deferred unit counts. An index that exceeds its own cap fails;
   it never bypasses a bound to preserve a complete directory listing.

Each variant contains a bounded index of discoverable items: stable citation ID,
short host-supplied label, kind, and byte length. Do not invent summaries. Optional
inline-only items omitted for capacity are reported as unavailable in this
invocation; only explicitly discoverable items can be read later. No hidden full
body is included in a nominally small prompt.

The selection heuristic is deliberately simple and inspectable; it does not solve
global relevance optimization. Better ordering is a host/evaluation decision.
Only byte-admitted candidate envelopes reach Runtime. Complete `input_data`
wrappers, fixed workflow facts, tools and provider framing are checked separately
against actual Runtime input limits; the pack's 48 KiB cap is not a whole-request
budget. Host-reduced aggregate variant-work limits can still fail preparation;
they do not authorize an over-budget fallback.

### One Runtime fitting transaction

The current Runtime API can fit history for one `input_data` value. Repeating
`prepare_turn()` separately for many pack variants would restart work counters and
make fitting behavior hard to recover. **Design choice:** add a small generic
Runtime seam, not a second token oracle in Harness:

```python
# Proposed Runtime API; input variants are data, not Harness pack objects.
prepared = runtime.prepare_turn_variants(
    approved_agent,
    message=message,
    history=committed_history,
    input_data_variants=ordered_variants,  # richest first; mandatory-only last
    context_policy=context_policy,
    token_counters=qualified_counters,
    policy=run_policy,
    limits=turn_limits,
)
```

The capability is `context_input_variants_v1`. All candidates have the same agent,
user message, tools, endpoint, and policies. Only bounded input data varies.
Runtime owns all native encoding/counting and charges all candidates to **one**
existing `ContextWorkState`, including construction, encoding, callbacks, baseline
history checks, and final verification. Caps cannot reset between variants.
An admitted counter must be deterministic for fixed native bytes and its sealed
descriptor, including when it supplies a conservative upper bound; readmission
cannot reproduce a random or time-varying estimate. Qualification tests enforce
this on repeated payloads without claiming a universal production tokenizer.

**Design choice: history first.** Fit the mandatory-only variant with the existing
history policy first, establishing a retained whole-turn suffix. Then try richer
variants in order against that fixed suffix. Optional evidence cannot evict any
additional history. Return the first fitting variant, or the base if no richer
candidate fits. This requires evaluating actual payloads; never assume token counts
are additive or monotonic. A mandatory base that cannot fit fails `contextLimit`.
Before starting an optional trial, retain the existing required headroom for one
execution readmission. If another trial cannot be funded without consuming that
headroom, select the already verified base and report `selectionWorkLimited`.
If a running trial exceeds a work/deadline limit, fail; never return an unverified
candidate or reset the budget. Do not reserve a separate execution readmission
for each trial. Refactor the existing assembler's finalization so the baseline
and rejected variants share one transaction, with one final selection/report and
one final readmission reservation. Calling the current finalizing assembler once
per variant is specifically not a conforming implementation.

The resulting `PreparedTurn` binds the complete source-history digest, retained
suffix, chosen input-variant index/digest, counter descriptor, and final payload.
When private authoritative facts are supplied, it also binds those facts and the
per-guard input-access declarations described below. Those facts are identical for
all variants and never enter the native payload or its token count.
The exact final report describes the selected variant, not the earlier baseline.
Use a new encoding identity (`conversation-turn-v3`) for explicitly profiled pack
inputs, opted-in variant preparation, or separated guard inputs; existing v1/v2
identities and APIs remain
byte-compatible. These changes belong to one proposed encoding profile, rather
than a separate version number for every new option.
Execution readmits the frozen chosen variant/suffix; it never reruns optimization.
Retain cumulative reservations through interruption after the selected pending
attempt is durably saved, as existing context execution does. Runtime must expose
the selected index and owned report publicly so Harness does not inspect private
prepared material.

### Public frozen restoration contract

Define an immutable Runtime `InputVariantSelection` record with version, bounded
ordered candidate digests, selected index/digest, mandatory-base digest, source
history digest, and the final report identity. Its digest algorithm is named in
the record. It is separate from the existing closed version-1 history
`ContextSelection`; do not add fields silently to that record. `PreparedTurn`
exposes `input_variant_selection` and owned `selected_input_data` publicly to the
trusted host. For a single byte-bounded variant, the same selection structure is
used without a token report; history selection remains legacy/full-history.

Add `PreparedTurn.export_frozen_input()` and a generic Runtime restoration seam:

```python
# Proposed host-only APIs. The exported record contains private input data.
frozen = prepared.export_frozen_input()
restored = runtime.restore_turn(
    approved_agent, history=original_portable_history,
    frozen_input=frozen, policy=run_policy, limits=turn_limits,
    context_policy=context_policy, token_counters=qualified_counters,
    workspace=host_workspace,  # None for tools without filesystem/CLI requirements
)
```

The frozen record contains the exact owned current user message and its digest,
selected input-data bytes, optional authoritative facts, input/profile/variant
identities, selected history range, initial/final reports as
applicable, work state, initial native-payload digest/size, and admitted endpoint,
tool, guard, policy and counter descriptors. It refers to source history by digest;
the controller supplies its complete retained portable history separately. It does
not serialize callbacks, credentials, authority, or a live `PreparedTurn` object.
All copies count against storage/JSON limits.
The current message is not part of that earlier portable history and cannot be
recovered from `input_data`; preserve it explicitly without normalization. A host
workspace is supplied separately when needed and readmitted against the original
tool/path policy. The frozen record cannot grant a workspace or filesystem roots.

`restore_turn()` bounds/owns the document, verifies current host bindings, original
agent/history identities and internal cross-bindings, and reconstructs only the
saved selection. It does not call counters, recompute candidates, fetch sources,
discover tools, or run guards. Runtime's normal execution readmission then reserves
work durably before construction/counting and compares the actual reconstructed
native request against the saved digest/report before dispatch. A standalone host
uses the existing checkpoint callback; a durable Harness controller persists every
reservation under its lease. A malformed frozen document or mismatched descriptor
fails before callbacks/effects. Restoring a record is never an authorization grant.

Harness additionally matches the variant record against its saved candidate plan
and selected `PreparedContextPack`. The candidate digests let it validate the saved
selection without rerunning ranking or depending on a renderer's current defaults.
Pack-envelope digests and full Runtime input-data digests are different fields:
Harness assembles each complete `input_data` root from fixed controller/user
facts plus the corresponding `contextPack` envelope, preserving candidate order.
It saves that index mapping and the full-root digests. After Runtime selection,
`ContextPacker.select()` verifies the extracted pack-envelope digest, while the
controller separately verifies the complete selected root and its fixed fields.
A complete-input digest must never be compared as though it were the nested
pack-envelope digest or used to omit a controller field.
The receipt is self-consistent with the same frozen input. This public seam is
required release work; private inspection of Runtime's prepared material is not
an acceptable recovery implementation.

**Design choice: initial fitting is ephemeral.** Before a durable selected attempt
exists, composition and fitting run under one per-call finite work budget, with no
model/tool/source effects. There is no durable `selectionInProgress` state and no
promise to restore CPU work consumed by a process that dies during initial pure
fitting. An explicit repeated host request can restart that initial transaction;
host admission/rate limits bound repeated requests. Do not add an automatic fitting
retry loop. After persistence, all execution/readmission reservations are durable
before counter callbacks. A crash there retains spent/uncertain reservations and
cannot restart the optimization budget. This distinction is part of the contract,
not an implementation shortcut.

Without a qualified counter, pure byte-bounded packs still work: use one chosen
variant and ordinary `prepare_turn()` with existing byte admission. Select the
mandatory base by default; a host may explicitly choose another byte-admitted
variant before calling Runtime, and that choice is part of request identity.
Pack reports state
`countingKind: notCounted`; there is no claim of token fit, no estimated-token
guarantee, and no automatic byte-to-token conversion. Automatic token-based variant
selection requires the new capability and an admitted counter.
`notCounted` is a pack-report status, not a new value in Runtime's existing closed
`ContextAssemblyReport.countingKind`. Byte-bounded pack preparation still exports
the new frozen-input envelope for durable restoration; it does not fabricate a
token report or an admitted counter.
Harness passes the explicit host `input_profile='context-pack-input-v1'` (or the
workflow projection profile) even for one byte-bounded variant, so the new frozen
input/selection contract is available without changing any pack-free call.

Once execution starts, the chosen pack is fixed. Runtime rechecks every tool
continuation against its existing limits, including reader outcomes. It never
silently drops current tool results, replaces required evidence, or reruns the
pack builder mid-turn. Failure retains known usage/effects; it does not trigger an
automatic retry or an unrecorded larger-model escalation.

## Proposed embedding API

```python
# Illustrative proposed Harness API; these imports do not exist yet.
from prosaic_harness import (
    ContextSnapshot, ContextPackSpec, ContextSlot,
    ContextPackPolicy, ContextPacker,
)

# Host retrieved and authorized these records before this pure operation.
snapshot = ContextSnapshot.from_items(captured_items, scope_binding=scope_identity)
spec = ContextPackSpec(
    identity="impact-analysis", version="1",
    slots=(
        ContextSlot(source="service", required=True),
        ContextSlot(source="dependencies", required=True, min_items=0, max_items=64),
        ContextSlot(source="release-notes", required=False, priority=10,
                    availability="discoverable"),
    ),
)
packer = ContextPacker(policy=ContextPackPolicy())
candidates = packer.compose(spec, snapshot)  # no I/O, callbacks, or inference

# Standalone host authorizes use, prepares through Runtime, and persists the
# selected pack/reference before calling runtime.turn(prepared).
```

Here the host captured the requested service as the single `service` item; the
spec stays registered unchanged when the next question names another service.
An empty dependency result is valid only if the slot's minimum is zero and the
captured source explicitly records a completed empty lookup. Missing lookup and
zero dependents are distinct states. Captured evidence may also state incomplete
pagination; generic selection cannot upgrade it into an exhaustive result.

## Conversation integration

Add optional pack bindings to `ConversationBindings` and a host-only argument:

```python
# Proposed API. The HTTP client does not submit a prepared pack or source scope.
reply = chat.send(
    session_id, message_id=message_id, message=user_text,
    expected_revision=revision, context_pack=candidates,
)
```

Bindings allow named spec/version identities and source aliases for the ordinary
agent. The controller verifies the candidates, current use authorization and
scope before fitting. It derives the final envelope itself; caller-provided hashes
are never enough. No arbitrary `input_data` passthrough is added to `send()`.
Existing workflow-owned `inputData.workflow` and structured-choice fields cannot
be overwritten by a pack.

The user message remains separate and unchanged. Turn idempotency binds message,
interaction reference, and pack-candidate identity. Reusing a message ID with
different evidence is a conflict, even when the text matches. Exact replay returns
the original receipt without recapture, composition, inference, or reader calls.
It still requires current access to view the retained answer/evidence.

For conversation packs, the model envelope uses `context-pack-input-v1`. If guards
are present, bindings explicitly opt into the separated-input capability and
audited guard registrations. The authoritative view is
`context-pack-snapshot-v1`: an owned envelope of the complete supplied snapshot's
source descriptors and items. It excludes credentials and executable bindings.
The user message remains the existing separate guard fact. Custom guards can
therefore validate against the full capture without the host inventing workflow
arguments; guard-free conversations need no private-facts copy. The private-facts
cap still applies independently, so a large snapshot can fail this admission.

Interpretation/confirmation is a separate purpose. Ordinary evidence does not
flow into its agent automatically. V1 rejects `context_pack` on an attached
workflow interaction and does not expose interpretation pack bindings. Existing
workflow review facts remain on their current path. A later extension must specify
independent admission and exact confirmation binding; evidence can never constitute
authenticated user consent.

Source-history storage stays complete. Historical inline pack bodies do not get
silently copied into every later user turn; the private per-turn pack snapshot
remains in its receipt/checkpoint, while portable history retains the actual user,
assistant and tool exchanges under existing rules. If a later turn depends on old
evidence, the host must deliberately attach it again or expose a permitted captured
read. Document this behavior prominently to avoid implying automatic memory.

### Authorization of retained and derived history

Persist a bounded `exposureBindings` sidecar per committed turn. It identifies all
pack source aliases/identities, revisions, scope bindings and exact representations
made available to that invocation, plus captured reader disclosures. Conservatively
associate the resulting assistant answer and tool history with that union, including
the exposure bindings of history supplied to the invocation; an answer may derive
information from those inputs. Full private guard facts receive separate validation
use bindings and are not mislabeled as evidence shown to the model. No source text
is duplicated into an exposure record.

Before fitting or dispatching any subsequent turn, authorize reuse of the retained
history exposure union in addition to the new pack and any private validation use.
The same gate applies when `send()` has no `context_pack`, on explicit retries, and
on a new attempt reconstructed from a frozen selection. Otherwise an old reader
result could bypass revocation by reentering the provider request through history.
V1 conservatively checks the whole retained history union before fitting, even
when Runtime may later omit old turns; it does not optimize authorization by
silently discarding denied context. A denied source fails `contextUseDenied` before
provider spend. Stored history is unchanged. Starting a separately admitted new
session is the supported way to continue with a clean history; a future explicit
redaction/migration API would need its own transcript and derivation semantics.

`authorize_use` receives a closed, bounded `ContextUse` descriptor: purpose
(`invocation`, `deferredRead`, `historyReuse`, `validation`, or `retainedRead`), host scope,
operation/session/run identity, admitted deadline, and the applicable source/revision
and representation references. It returns a boolean; exceptions/invalid results
deny use. Its identity/version is sealed. Invocation/validation/history permissions
are acquired once for that logical invocation; deferred reads are rechecked per
call. Authorization callbacks perform no source refresh or model execution. A
host that needs faster revocation also cancels in-flight work; already sent bytes
cannot be withdrawn. Historical outputs of unrelated domain tools remain subject
to their existing host policy; adapters may add their provenance to this sidecar,
but packs cannot claim to infer source rights from arbitrary tool text.

Retained-history viewing and exact reply replay require current read access too.
Use the separate `retainedRead` purpose for returned history, saved replies/status,
and private evidence projections. It can be granted without permitting another
inference invocation, and can be denied without preventing internal settlement.
Internal receipt verification/adoption may settle an already completed operation
under controller ownership without acquiring new inference/use permission; its
public reply is withheld if current read access is denied. A denied retry does not
erase uncertain effects or unresolved receipts. There is no authorization-driven
source recapture, automatic retry, or silent transcript mutation.

## Workflow integration

Add `context_packs` and pack bindings to the trusted `WorkflowFactory`/bindings
surface. An agent step may reference a named spec via a new optional `contextPack`
field in the opted-in workflow schema. Static YAML receives an equivalent optional
declaration; no existing required keys or source syntax change.

Model-proposed workflows may choose only host-advertised spec aliases. They cannot
define source roots, callbacks, permissions, revision policies, or executable
selectors. Factory admission closes and bounds the new fields, seals declarations
and effective bindings in the workflow identity, and rejects unavailable
capabilities before reserving a run.
`describe()` and `proposal_schema()` advertise only explicitly public pack aliases
and bounded host descriptions. They do not expose source snapshots, selectors,
private revisions, scope bindings, feedback diagnostics, or callbacks. Factory
bundle/frozen copies must preserve all pack, guard-access and feedback bindings.

At a step boundary, snapshots come from already frozen run inputs/evidence and
accepted fresh prior outputs. Existing required/optional dependency and binding
checks run first. Selection cannot bypass stale-output checks, remove required
dependencies, lose validation outcomes, or rewrite controller/confirmation facts.
For v1, native steps map existing controller-required facts into a mandatory
`input_data.workflow` envelope; the pack occupies a separate `contextPack` member.

There are two explicit projection profiles:

| Step | Model-visible facts | Private authoritative guard facts |
| --- | --- | --- |
| Existing shared-input guarded step, pack-free | Exact existing `rule_facts(step, original_arguments)` under `workflow`. | No additional channel; existing behavior and proofs remain unchanged. |
| Pack-enabled step, guarded or unguarded | Request, safe controller feedback, human responses, step/version, dependency bindings, undeclared-source arguments, and selected pack evidence. | For guarded steps, complete unchanged `rule_facts(step, original_arguments)`, available only to explicitly registered guards that need it. |

**Design choice: include separated guard inputs in the first complete release.**
Keeping all validation facts in the prompt would prevent packs from reducing
large guarded inputs. Instead, preserve authoritative source data privately while
giving the model the same bounded pack projection used by unguarded specialists.
The fact that a value is available to validation does not mean the model saw it,
is permitted to fetch it, or may cite it.

For all pack-enabled steps, use the new `workflow-pack-input-v1` model projection.
Host bindings explicitly map a source alias to an accepted artifact ID or declared
run-evidence entry. V1 does not project arbitrary request/controller fields. A
mapped body is replaced at its original `workflow.artifacts`/`workflow.sources`
entry by a closed `contextSource` descriptor containing alias, source revision,
and digest. Actual chosen content appears once in `contextPack`; unmapped entries
remain unchanged. The descriptor is present even when optional body content is
omitted. Every required input mapped this way must have a required inline pack
slot; factory admission rejects bindings that lack that coverage. The selected
representation can be an explicit excerpt, not an assertion that the whole body
was provided. Agents opting into this profile must understand that references are
not inline content. This is a new opted-in agent contract, not a rewrite of old
argument semantics.

Pending state and receipts retain `originalArguments` and its existing digest,
the frozen controller validation context described below, and the model
projection/profile/digest and selected pack
reference. Original accepted outputs remain retained separately. Controller
validators receive original arguments; no validator or dependency check is
silently switched to the smaller view. Pack-free records are unchanged. Guarded
pack steps use the separated-input guard contract and new proof below; a projected
model input is never recorded as the complete original guard facts.

Every pack-enabled agent step uses `prepare_turn()`/`turn()` (or the variants seam),
including unguarded steps. Preserve complete authoritative rule facts and terminal
completion precedence. Pack-free steps retain their existing execution paths,
proofs, and fingerprints. Capability checks are conditional, not a blanket
requirement that a tool-free byte-bounded pack enable every new feature:

| Requested behavior | Required Runtime capabilities |
| --- | --- |
| Profiled pack input and public frozen restoration | `conversation_turn_v1`, proposed `frozen_turn_inputs_v1` |
| Token-aware variant fitting | Also `context_assembly_v1`, `context_input_variants_v1`, and a qualified counter |
| Separated guarded inputs | Also `rule_admission_v1`, `guard_input_views_v1`, and audited guard access declarations |
| Captured-evidence reader | Also `tool_context_v1`, the explicitly granted registered reader and existing tool budgets |

The selected adapter/profile must implement the requested semantics, not merely
expose a suggestive name. Unsupported profiles/adapters or acquisition combinations
fail explicitly. No fallback to prompt concatenation, byte-only admission, a
different backend, or weaker validation when the host requested a missing feature.
V1 excludes pack-enabled steps with acquisition agents; use explicit prior
retrieval/tool steps instead. Tool-only and human/gate steps do not get packs.
Admission also rejects `{{args}}` interpolation in pack-enabled agent bodies or
resources, matching Runtime's conversational rule. Consumers migrate those agents
to role-separated input explicitly; Harness never rewrites their prose silently.
Pack-enabled steps with `require_reads` are also rejected in v1: a supplied pack
is not a Runtime file-read receipt. Explicit source/tool steps are the supported
alternative. Existing guarded/terminal-tool incompatibilities remain enforced;
this feature does not relax them.

An output binding for a pack-enabled invocation additionally binds its pack
identity and captured source-revision set. If an accepted upstream dependency is
invalidated, the pack is stale under the same dependency rules as the output.
Refreshing sources/replanning creates a new invocation; uncertain effects retain
the existing explicit-retry contract.

## Separate guard facts from model evidence

The released implementation supplies one `input_data` value to both the model and
`GuardContext`. Workflow proof v1 hashes that same complete `rule_facts()` value.
This is an implementation coupling, not a requirement that all validation facts
consume prompt tokens. The new mode separates these views without changing the
meaning of the old one.
[Guard context](https://github.com/B3Cognition/prosaic-runtime/blob/v0.9.17/src/prosaic_runtime/rule_types.py),
[rule hooks](https://github.com/B3Cognition/prosaic-runtime/blob/v0.9.17/src/prosaic_runtime/rule_hooks.py),
[workflow proofs](https://github.com/B3Cognition/prosaic-harness/blob/v0.9.12/src/prosaic_harness/workflow_rules.py).

### Runtime seam and access declarations

Add the generic optional Runtime preparation argument `authoritative_input_data`
to both `prepare_turn()` and the proposed `prepare_turn_variants()`. Harness owns
its construction from unchanged accepted workflow arguments. It is bounded owned
plain JSON, never a callback, path, model proposal, user-supplied HTTP field, or
extra tool grant. Standalone Runtime hosts may use the same generic seam without
importing Harness. The capability is `guard_input_views_v1`.

`input_data` remains exactly the initial data sent to the model, and
`GuardContext.input_data` keeps that meaning. Add a separate lazy, per-check owned
`GuardContext.authoritative_input_data` property. Do not repurpose `input_data` to
return private facts: doing so would silently weaken guards that check what the
model has actually seen. `user_message`, proposed tool arguments, current tool
results, and answer draft retain their existing observed-execution semantics.

Add a host-only `input_access` declaration to `Guard` registrations:

| Access | Behavior |
| --- | --- |
| `shared` (legacy default) | Existing shared-input execution only. Cannot run in separated-input mode until explicitly re-registered for an audited access mode. |
| `model` | Can read `input_data` and existing observed turn facts; private authoritative property access faults the guard. |
| `authoritativeAndModel` | Can read both input views; intended for validation against complete captured facts or explicit comparisons of the two views. |

Admission validates every active guard, including host-required guards, before
effects. A `shared` guard in separated mode fails admission; it is never skipped
or automatically assigned to the private channel. Re-registering a custom guard
requires auditing its assumptions and bumping its version where its behavior
changes. Nondefault access declarations participate in both Runtime and Harness
guard descriptors, rule fingerprints, binding snapshots, and readmission. Default
registrations omit new fields from their legacy identity material, preserving old
identities and receipts. Harness's registration-copy helper must preserve the new
declaration instead of silently dropping it.

Qualify opt-in `model` registrations for the shipped generic guards:

- `args_reference_seen_ids` continues using only the actual model input, current
  user message, and observed tool results. A guessed ID present only in private
  facts must still be refused. An ID actually disclosed through a granted reader
  outcome can subsequently count under the existing tool-result rules.
- `value_in_tool_output` still checks actual observed tool outputs. Private source
  records are not injected into its evidence set and inline pack data does not
  magically become a tool output.
- `strict_json` and `no_wrapped_links` keep their existing draft checks/repairs;
  neither needs private facts.

No Core tag syntax is added: the host selects these access modes in Python. An
agent, pack item, or model-proposed workflow cannot expand them.

### Private-fact validation does not disclose private facts

V1 registrations with `authoritativeAndModel` access are **fail-only**: admit them
only with `action=fail`, `fixes=False`, and `echo_values=False`. Their verdict's
raw reason, refused values, and any fixed value never enter provider messages,
tool outputs, public errors, or public event metadata. A failure emits only an
SDK-produced safe code and an admitted rule reference. Invalid repair/retry
bindings fail admission rather than degrading at execution time.

This restriction applies to any guard granted private-fact access, even if a
particular callback happens not to read the private property. Model-only guards
retain existing bounded fix/retry behavior. This prevents ordinary guard repair
or tool-stage retry feedback from becoming an accidental private-data channel;
it does not sandbox arbitrary trusted Python callbacks.

The same projection boundary applies to controller feedback through the concrete
safe-feedback contract below. Existing controller/human facts are not silently
discarded to make a pack fit. Authorization and confirmation remain independent
of guard success.

Private facts can validate a draft without being sent to the model; they cannot
make an underinformed task solvable. If generating the required answer needs a
fact, the host must select it as required evidence, provide an explicitly derived
source-linked value, or grant an authorized read. Missing model-needed evidence
may fail coverage or fail a guard; there is no automatic retry with a larger or
more revealing pack. A separately authorized new invocation can attach more
evidence after the prior outcome is resolved.

### Bind both views, preserve full validation

All variants share one immutable authoritative-facts value. Runtime bounds and
owns it once before candidate processing and retains it privately in prepared
material. Provider encoders, token counters, history projection, tool handlers,
reader allowlists, and model-visible reports receive no extra access to it. A
guard can see only its declared views. Private data is excluded from token counts
because it is not sent, but its storage, encoding, decoding, guard computation,
and wall-time costs remain bounded.

Runtime's optional host profile labels `authoritative_input_profile` and
`input_profile` are bounded inert version identifiers sealed in preparation, with
no behavior selected by interpreting their text. Harness supplies
`authoritativeInputProfile: workflow-guard-input-v1` for the unchanged complete
facts and `modelInputProfile: workflow-pack-input-v1` for the selected projection.
Runtime computes separate canonical `authoritativeInputDigest` and
`modelInputDigest`, and binds them with the effective access declarations in
`inputViewsIdentity`. Harness retains its existing original-facts digest as well;
the existing workflow hash and new canonical Runtime hash are distinct named
algorithms, not interchangeable hashes of the same bytes.

The v3 `PreparedTurn.contextIdentity` seals the model context, private facts, and
guard bindings together. Changing only omitted private facts may leave the native
provider payload unchanged, but must change the prepared invocation identity and
force readmission. There is no public deserializer that grants authority from
these digests. Existing v1/v2 shared-input identities stay unchanged.

Guarded pack steps add closed **`workflow_rules_v2`** proof metadata, rather than
relabeling a projected call as proof v1. It binds the original full facts digest,
both input profiles/digests, `inputViewsIdentity`, pack identity, Runtime context
identity, and the evaluated rule receipt. Runtime supplies computed input-view
bindings in private turn evidence; Harness recomputes the expected original and
selected views from the saved controller state/pack before accepting the result.
An envelope containing caller-supplied hashes alone cannot satisfy that check.
The complete original facts remain available to authoritative validators and
guards, while model-only checks evaluate actual observed input. No v1 rule proof
is accepted as a replacement for a required v2 pack proof.

Persist both complete input values and their binding in the pending attempt
before dispatch, within its opt-in record version. After execution, the completed
receipt binds the same values; no completed receipt is invented before execution.
On restart,
restore those exact bytes and access declarations; do not reconstruct private facts
from a newly queried database or the smaller pack. Changed bindings, missing facts,
or a mixed-view proof fail closed. Receipt adoption does not rerun guards.

The proposed private-facts limit is 2 MiB encoded, depth 32, and 65,536 JSON nodes,
host-reducible and independently admitted from provider input bytes. It does not
increase checkpoint/receipt limits; every retained copy counts. Shared source
storage can be optimized internally only when exact bytes and both identities
remain reconstructable. A large private fact set can fail a storage/work limit,
even when the model's pack fits its token window.

### Safe controller feedback and repeatable validation

The released controller joins arbitrary validator issue strings, stores them in
`feedback`, emits `validation_failed.message`, and forwards them on the next
attempt. That legacy behavior would disclose facts omitted from a pack, even when
Runtime's private guards are fail-only. Pack-enabled workflows therefore use a
new sealed **`safe-feedback-v1`** policy for the whole run, including pack-free
steps within that opted-in run.

By default, issue strings and exception details never enter model input, public
events, public interaction errors, or retry instructions. Reducer-owned closed
codes identify `validationFailed`, `schemaViolation`, `humanResponseInvalid`,
`gateInputInvalid`, or `validatorFault`, with bounded aggregate issue counts.
`validation_feedback` retains the outcome/code instead of losing the failure.
An ordinary failed-check event uses the SDK's generic constant message and code.
Validator-provided text is not trusted as an error code or a safe message.

Add optional host `WorkflowBindings.feedback_catalog`: a bounded mapping from
registered validator/check aliases to static remediation text. Values are at most
512 UTF-8 bytes each, 64 entries and 32 KiB total; aliases must name admitted
bindings. The map is copied and sealed in workflow identity. Text is host-authored,
source-independent configuration, with no interpolation, exception text, template
evaluation, issue-string classification, callbacks, or runtime record values.
A failed bound check may include its admitted constant remediation text. Without
an entry, the generic code/message is the complete feedback; absence never enables
raw issue strings. Dynamic declassification is outside v1.

Apply this at the point results leave a check, not merely in the pack renderer:
agent/check-step validators, schema diagnostics, human-response validation, gate
errors, `validation_failed` events, observer projections, public status/replies and
subsequent attempts all use it. Private diagnostics may retain bounded raw issues
in private controller evidence under reserved state capacity; default behavior may
discard them. They are never stored in the model-facing feedback field. A
private-source sentinel returned by any validator must not escape through public
events before the next pack is composed. Existing public replies can still reveal
the intentionally disclosed success/failure outcome; this is not a zero-information
secrecy claim or a sandbox for trusted Python code.

Keep the released controller's recovery boundary: the Runtime receipt is durable
before Harness schema/controller validators run. Adopting a saved receipt may run
those validators again. It never reruns Runtime guard hooks, inference, or tools.
V1 does not add a second durable validation-result journal or promise exactly-once
validator execution. For opted-in runs, add sealed host
`WorkflowBindings.repeatable_validators`, an explicit set of all used validator
aliases attested as deterministic, read-only, and repeatable against supplied
snapshots. Admission rejects missing attestations. This does not statically prove
Python purity: hosts must move live retrieval, inference, writes, or time-sensitive
checks into explicit steps with their own receipts. Revalidation uses the saved
complete original facts, never refreshed external state. Both new binding fields
are preserved by frozen factory/bundle copies and absent from pack-free identities
when not enabled.

For each invocation, freeze the existing `CheckContext` shape separately as
`controllerValidationContext`: step, request, the complete accepted artifacts and
bindings visible to that check, declared evidence, and authenticated human responses.
It is not merely `rule_facts(originalArguments)`, which can contain a narrower
artifact subset. Save it or exact reconstructable references to retained immutable
values in the pending record before dispatch, and bind them in the completed
receipt after execution. Validators still receive
their existing `check(output, CheckContext)` API, reconstructed from those frozen
values; they are not handed a new argument shape or live mutable run state.
Terminal-enabled pack-free steps retain their separately admitted terminal context.
Every encoded occurrence/reference and resolved value is bounded, identity-bound,
and included in capacity admission. A missing referenced value fails recovery;
it never prompts a live lookup or a smaller substitute context.

## Progressive disclosure

V1 includes an optional `ContextPackReader` that creates a normal versioned
`CustomTool` named `read_context_item` from the **selected pack's admitted
discoverable allowlist**. It reads retained snapshots only, with no filesystem,
network, vector-store, or cross-pack lookup. Registration and ordinary tool grants
are explicit. A discovery index is never emitted unless the reader is granted;
otherwise the consumer must choose inline evidence or mark it unavailable.

Arguments contain a citation/item ID and an optional bounded range within a
captured text item. JSON items return whole bounded values or an admitted JSON
Pointer; no arbitrary query execution. A result includes item/source revision,
snapshot digest, exact returned range/pointer, content digest, and continuation
availability. Text pages split on UTF-8 boundaries. A partial page is never labeled
as the complete document. Discovery labels are source data, not instructions.
The allowlist seals the permitted representation, not just its parent item ID:
an excerpt cannot be expanded beyond its admitted range, and a JSON Pointer cannot
be widened to its parent object. Retaining extra source bytes for private recovery
does not make those bytes available to the agent.

The tool is dispatched through Runtime's current contextual-tool path and bound to
the controller-reserved invocation scope. Implement it as a stable host registration
with an invocation-scoped snapshot lookup; do not change the model's tool schema
or implementation identity after Runtime preparation. Activate the selected frozen
allowlist before dispatch; clear the transient binding on completion. Durable
reconstruction uses the pending attempt, never an ambient process-global pack.
Concurrent invocations must not see each other's snapshot bindings.

Every call verifies the operation scope, current host authorization, selected pack
identity, and allowlist membership. Normal tool argument/result limits, call
budgets, events, evidence and cancellation apply. Defaults cap each returned body
at 16 KiB and the complete encoded result at 24 KiB. The stable tool registration
declares that encoded result bound; reserve full framework/tool-message overhead
as well. JSON escaping and provenance metadata count. Text paging narrows the
returned UTF-8 range until both limits fit, with an exact next offset; a JSON value
that cannot fit is refused with a safe `contextReadLimit` and requires a narrower
admitted pointer, never prefix-truncated JSON. The host can reduce these limits
within the admitted tool contract. A reader
never expands a tool grant and cannot load another tenant's pack by knowing its
hash. Previously recorded tool results are history, not permission to read again.

This supports fetching more **captured** context. Genuinely new evidence uses
ordinary authorized domain tools and appears as recorded tool outcomes. It does
not mutate the initial pack. A subsequent turn/step may deliberately compose a new
snapshot from those outcomes. Citations distinguish initial pack items from later
tool evidence. Dynamic in-turn repacking and recursive subagents are deferred.

## Durability, recovery, and bounded resources

Persist the selected pack's complete bounded source snapshot, selected projection,
spec/binding identities, omission/coverage report, and Runtime selection/work state
with the pending attempt **before the provider dispatch marker**. The receipt binds
the same data. A storage digest alone without retained reconstructable bytes is
insufficient. Reserve receipt/snapshot capacity before dispatch, including failure
evidence and the maximum admitted reader outcomes.

**Design choice:** v1 stores snapshots inside existing owned checkpoint/receipt
documents. No additional database service or blob-store protocol. Duplicated bytes
count in every applicable quota; do not claim physical deduplication from equal
hashes. Capacity admission may reject a pack even if its prompt fits. An external
content-addressed store can be a later optional adapter with explicit retention and
transaction semantics; it is not necessary to use packs.

Use explicit new versions for the separate record families:

| Family | Released baseline | Pack-enabled contract |
| --- | --- | --- |
| Conversation session and conversation receipt | Matching versions 1 or 2 | Both version 3; do not combine session v3 with receipt v2. |
| Workflow checkpoint and workflow invocation receipt | Checkpoint v2 and receipt v1 | Checkpoint v3 and invocation receipt v2. |
| Prepared Runtime turn encoding | `conversation-turn-v1` / `conversation-turn-v2` | `conversation-turn-v3` for profiled/variant/separated inputs. |
| Workflow rule proof metadata | `workflow_rules_v1` | `workflow_rules_v2` only for guarded pack calls. |

Verify these unallocated new numbers again against the eventual implementation
base before release. Conversation receipt v2 already exists in v0.9.12 and
requires equality with its session version; it cannot stand for this new feature.
In an opted-in session, every receipt uses the session's v3 wrapper, including
ordinary turns without a pack and interpretation turns; the inner turn encoding
may remain v1/v2 for those purposes, with absent pack fields explicitly null.
Opted-in workflow runs use the v2 receipt wrapper for all their invocations;
pack-free steps retain their existing payload/execution and rule-proof semantics.
Entirely pack-free sessions/workflows retain their old record families unchanged.
New fields never get silently
added to closed legacy documents. Memory/file/PostgreSQL backends advertise
`context_packs_v1` only after their validators and initialization support it.
Existing namespaces need an explicit drained-writer capability/storage migration;
readiness never migrates or rewrites old records. Preserve v1/v2 session and old
workflow/receipt readers byte-compatibly. A new pack-enabled session/run cannot be
opened by an old writer. Schema migration and feature-version negotiation are
required release work, even though no new storage methods are needed.

Recovery rules:

| Observed state | Action |
| --- | --- |
| No durable pending attempt | An explicit host request may restart bounded initial composition/fitting from supplied bytes. No automatic retry or source recapture; pre-persistence CPU work is not crash-durable. |
| Frozen pending attempt, dispatch not started | Readmit current bindings/authorization; reconstruct exactly the saved pack/suffix with cumulative fitting reservations. No reselection. |
| Durable Runtime receipt | Verify and adopt it; never rerun retrieval, counters, readers, model calls, or effects. |
| Dispatch started but completion uncertain | Existing `needsResolution` behavior and acknowledged retry; a pack hash cannot prove no effect occurred. |
| Missing/corrupt snapshot or changed renderer/bindings | Explicit bounded failure; never fall back to current files, a different pack, or a fresh search. |
| Source revision revoked or new use denied | No new dispatch/read. Viewing retained private evidence follows current host access policy. |

Runtime guard evaluation has already settled in a Runtime receipt. Harness's
deterministic controller validation/adoption is a separate phase and can repeat
on crash recovery under `repeatable_validators`; it consumes saved original facts
and always applies `safe-feedback-v1`. No receipt-adoption promise implies that
arbitrary host validators run exactly once.

Retries use the saved snapshot and selection. Explicit refresh requires a new
message/operation ID after uncertainty has been resolved; it cannot reuse an old
idempotency identity with different evidence. No automatic deletion of unresolved
pack evidence for capacity admission.
Distinguish recovery of the same attempt from an acknowledged new retry attempt:
recovery never replenishes fitting/execution work. An explicit retry may allocate
fresh execution/readmission allowance as the released controller already does,
retaining the saved initial preparation charges/report and exact selection. It
uses a new attempt ID, current authorization and the existing per-turn/run aggregate
attempt/provider/tool quotas. Old spent/uncertain resources remain in the old
attempt's ledger. No new candidate optimization occurs. Frozen input has immutable
selection material and a separately checkpointed work state; restoring it uses the
saved current work for recovery, or the explicitly admitted new-attempt work for
retry, never an unvalidated reset supplied by a client.

Recommended initial limits, all host-reducible, are **design choices**, not measured
optima:

| Resource | Default |
| --- | --- |
| Source aliases / slots / captured items | 16 / 32 / 128 |
| One captured item / total captured content | 256 KiB / 2 MiB |
| Complete encoded snapshot, including metadata | 3 MiB |
| Inline evidence envelope, including index | 48 KiB |
| Discovery index | 8 KiB and 128 entries |
| Candidate variants / cumulative encoded variant data | 8 / 512 KiB |
| Labels per item / JSON depth / aggregate JSON nodes | 16 / 32 / 16,384 |
| Pure composition active time | 250 ms cooperative deadline |
| Deferred reader returned body | 16 KiB per tool call |
| Complete encoded reader result | 24 KiB per tool call, plus reserved framework overhead |

Runtime's existing request bytes, token capacity, shared candidate-work/time limits,
output reservation, and tool/provider-call caps apply in addition. Pack budgets
never increase them. Byte-bounded mode still counts provider framing through
ordinary Runtime admission. Existing session/run/receipt quotas are authoritative;
the defaults above do not guarantee a pack fits every configured store. Enforce
limits before large copies, sorts, projections, or nested encodings; trusted Python
callback deadlines are cooperative, not a sandbox or hard preemption guarantee.

Admission computes actual aggregate record bytes/nodes for the selected snapshot,
original arguments, private guard facts, frozen input, model projection and reports,
including each duplicate occurrence. It then reserves controller metadata growth,
safe feedback, output and failure evidence, and the maximum allowed tool-outcome
envelopes using the sealed tool/provider limits. A per-item cap is not a reservation
for all maxima at once. Reject `contextSnapshotLimit` before dispatch when that
record cannot fit the existing state/receipt/aggregate quotas; never discover the
shortfall only after an effect. Do not raise existing store limits implicitly.

Qualification must include a useful pack-enabled guarded workflow under unchanged
default workflow receipt/state limits (1 MiB / 4 MiB): at least 16 captured items,
32 KiB encoded snapshot, 64 KiB private facts, 16 KiB model evidence and two
reader calls admitted with their full declared result bounds, plus ordinary result
and failure headroom. Check those sizes against built artifacts rather than merely
adding raw content lengths. Test maximum-cap rejection separately; large configured
ceiling values are not a claim that every default store admits them simultaneously.

## Reports, errors, and evidence quality

Private reports enumerate selected/deferred/omitted IDs, coverage, locators,
revisions, deduplication, byte totals and reasons. Public projection is aggregate
counts and safe reason codes by default; source labels, paths, item IDs and hashes
can themselves disclose private information. Existing observers receive bounded
`context_pack_prepared` and `context_pack_selected` summaries, without raw content.
Do not emit durable-success events before receipt/checkpoint adoption.

Suggested closed admission codes: `invalidContextPack`, `contextScopeMismatch`,
`contextBindingMismatch`, `requiredContextMissing`, `selectionLimit`,
`contextSnapshotLimit`, `contextPackLimit`, `contextCapabilityMissing`,
`contextUseDenied`, and `contextSnapshotUnavailable`. Token/provider input failures
retain Runtime's existing `contextLimit` and safe limit identifier. Decoder errors
and authorization exceptions never expose source content or callback details.

Coverage is mechanical: required declared slots and selected item representations
are present. It does not establish that the host retrieved every dependency or
that an answer is true. Answer checks remain existing guards/validators. A future
generic citation-membership guard may validate that cited item IDs/ranges were
provided; semantic entailment remains a separate evaluated check.

## Qualification and acceptance

Contract tests must demonstrate:

1. Pure construction/composition makes zero source, authorization, model, tool,
   filesystem or network calls; malformed snapshots never trigger ambient fallback.
2. Exact selector semantics, empty-versus-missing results, strict cardinality,
   deterministic ordering, stable hashes and immutable nested input ownership.
3. Required content and index bounds fail before effects; no silent truncation of
   JSON/UTF-8 or merging of independent/conflicting evidence.
4. Actual OpenAI-compatible and native Anthropic payload fitting through one shared
   work budget; fixed history suffix for optional variants; non-additive counter
   fixtures; overflow and counter/deadline exhaustion fail before dispatch.
5. Pack-free old identities/checkpoints remain unchanged; unsupported native
   profiles/adapters/acquisition combinations reject without fallback.
6. Conversation duplicate IDs with changed evidence conflict; exact replay uses
   the original receipt; old evidence is not accidentally reattached as new input.
7. Workflow dependency freshness, guarded proof construction, feedback, terminal
   tools and human decisions retain their existing semantics.
8. Concurrent readers remain invocation/scope isolated; revoked use, foreign IDs,
   oversized reads and forged references fail without source access.
9. Failure injection at snapshot save, dispatch marker, tool outcome, receipt and
   checkpoint boundaries on memory/file/PostgreSQL storage preserves uncertainty
   and never repeats completed work automatically.
10. Snapshot/receipt/state quota exhaustion, legacy migration, old-writer exclusion,
    source mutation after capture, and renderer drift all have bounded outcomes.
11. A full authoritative source larger than the configured model-input budget can
    validate a smaller selected pack: valid drafts pass and invalid drafts fail
    against the complete retained facts. A private sentinel must be absent from
    every provider request, counter input, tool argument, and public event.
12. `args_reference_seen_ids` rejects an ID present only in private facts; it can
    accept an appropriately shaped ID after actual authorized disclosure. Private
    facts never widen tool permissions, reader allowlists, or answer evidence.
13. Legacy/default `shared` guards reject separated-input admission; audited
    `model` guards cannot access private facts; authoritative guards cannot bind
    repair/retry actions or disclose refused/fixed values through normal outputs.
14. Changing only an omitted authoritative value changes the invocation/v2 proof
    binding even when the provider payload stays identical. Swapped view digests,
    private-facts omission, changed access descriptors, and v1 proof substitution
    fail before result adoption. Exact receipt recovery does not rerun Runtime
    guards; repeatable Harness controller validators may run again on saved facts.
15. Revoking a source after a committed reader turn blocks the next provider
    invocation even with no new pack, including retries. No history is silently
    pruned; denied viewing and effect reconciliation stay separate.
16. Validators returning private sentinels, exceptions, human-response errors,
    schema failures and gate errors produce only safe codes/static catalog text
    in public events and later model input. Private diagnostics stay private even
    when recovery repeats controller validation.
17. Independent sources with equal revision/content remain distinct; ranked input
    changes do not require mutating a registered spec; completed empty and partial
    sources preserve their declared coverage semantics.
18. Oversized optional evidence is omitted rather than failing a fitting base;
    `max_variants=1`, exact JSON/UTF-8 boundaries, encoded reader expansion, shared
    final readmission headroom, and public frozen restoration have explicit tests.
19. Conversation v3 receipts match v3 sessions, opted-in workflow receipt v2 is
    distinct, and legacy v1/v2 namespaces/records reject incompatible writers.

Integration Lab adds an installed-package lane with two different domains: service
impact analysis and a document-review specialist. Use public exports only, not
private imports or sibling source paths. A source revision changing after capture
must not change the old invocation; an explicit refreshed invocation must expose
the new revision. Include a tool-free inline-only path and a reader-enabled path.

Real-model evaluation is separate and explicitly opted in. Compare unchanged
baseline input, static packs, and packs plus progressive reads on the same held-out
cases/model settings. Record answer correctness, required evidence recall, citation
validity, unsupported claims, stale/conflicting-source mistakes, false certainty
on missing/incomplete evidence, unnecessary/duplicate reads, input tokens, latency,
and total preparation/retrieval/inference cost. Include a distractor-heavy case,
multi-hop dependencies, absent evidence, and a contradictory old revision.

Do not advertise improved answer quality from synthetic fitting tests. Consumer
adoption requires no new missing-evidence errors on its preregistered required-fact
cases and a declared quality/cost tradeoff on its own representative set; there is
no invented universal percentage gain. Pin prompts, specs, candidate inputs,
source digests, model settings, and released package bytes in the evaluation record.

Run repository full suites with `.venv/bin/python -m pytest`, build with
`.venv/bin/python -m build`, and extend the existing installed-wheel conversation,
workflow and PostgreSQL release gates. Qualify both legacy and opted-in consumers.
No live inference is needed for contract/recovery tests.

## Delivery order and remaining builder discretion

These are dependency milestones for a later implementation plan, not authorization
to implement or publish this design:

1. Harness immutable contracts, bounded pure packer, exact selectors and reports.
2. Runtime generic input-variant preparation and shared work/recovery semantics.
   Include `guard_input_views_v1`, access-aware guard descriptors, bounded private
   facts, safe fail-only authoritative checks, and computed input-view evidence.
3. Conversation bindings, host pack argument, opt-in durable records and stores.
4. Workflow admission and turn-path integration, preserving guards/dependencies.
   Include the v2 guarded-pack proof and complete original-facts validation with
   the smaller common model projection; this is not deferred follow-up work.
5. Invocation-scoped reader and complete installed-package qualification.
6. Opt-in consumer evaluation and user documentation before general release.

No Core format migration, Echelon import, new repository, or mandatory retrieval
dependency is planned. Final release version numbers and dependency floors are
chosen after the implementation lands against current release branches.

The builder may choose module splits, internal data structures, exact safe-code
mapping to existing errors, and fixture layout. They may tune default limits only
with recorded boundedness/storage evidence. They must not replace the declared
history-first policy, add implicit inference/I/O to preparation, turn evidence
into privileged instructions, change old fingerprints, or defer storage/recovery
while calling the first release complete.

Potential later experiments: host reranking adapters, source-specific freshness
helpers, richer structural chunking, explicit summary-producing workflows,
content-addressed retention, model-specific ordering policies, evidence-coverage
validators, and native compaction interop. Each needs its own measurable consumer
benefit and compatibility contract. None is prerequisite for restoring packs.
