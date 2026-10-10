# Workflow factory construction implementation

Implemented the assigned Task 4 construction/admission scope on 2026-10-10.
Owned files: `src/prosaic_harness/factory.py`, `graph_admission.py`, package-root
exports, `tests/test_workflow_factory.py`, and this report. Engine, contracts,
schema evaluation, JSON snapshots, errors and loader integration belong to the
other implementation tasks. No commits, publishing or live endpoints were used.

Public APIs are `WorkflowCatalog`, `WorkflowBindings`, `WorkflowPolicy`,
`WorkflowFactory` and `WorkflowAdmissionError`. Native configuration is cloned
without CLI directories, and descriptors use Runtime's pure APIs. Logical
references, canonical/executable artifacts, approved schemas, policy grants,
effective limits and inline/composition permissions receive admission. The
confirmed omitted-tier/default rule is retained.

Model-tier allowlists use existing host Runtime route names rather than catalogue
alias syntax. Route names may contain `/` and Unicode, are 1–64 characters, and
exclude Unicode control/format characters and surrogates. Catalogue, step and tool
aliases retain their existing simple-name restrictions. The complete sorted tier
allowlist remains sealed in policy identity.

Native results have fixed `_NativeWorkflow` origin, `path=None`, empty evidence,
independent request data and an immutable `_admission` record. The record exposes
`original_seal`, `config_json`, `policy`, `tools`, `validators`,
`validator_versions`, and immutable serialized `content_json`. Engine integration
uses `admit_workflow(workflow, runtime=None, validators=None)` and
`_config_from_json(record.config_json)`. Native adapter overrides must be exact
standard `ProsaicRuntime` instances with matching live configuration, relevant
descriptors/capabilities and no retained CLI registrations.

Shared graph checks validate agent input references and use lexical confinement
without `Path.resolve`. Legacy admission requires an absolute YAML path and
runtime reference. It consumes the loader's fresh `_registered_descriptors`
mapping, backed by immutable JSON, and preserves legacy empty read-root and gate
field semantics. Missing native records and caller-recomputed identities cannot
downgrade native results into legacy objects.

Verification:

- Original public factory RED: **19 failed**, all missing factory APIs.
- Expanded construction/provenance RED: **37 failed** before implementation.
- Initial implementation GREEN: **37 passed**.
- Additional malformed mapping/configuration RED: **4 failed / 42 passed**;
  GREEN followed after controlled mapping/feature validation.
- Aggregate-artifact and descriptor-copy ordering RED: **2 failed / 46 passed**;
  aggregate limits now reject before decoding another catalogue artifact, and
  native descriptors are bounded before copying.
- Explicit JSON `inline_agents:null` RED: **1 failed**; the strict envelope now
  rejects it instead of treating it as an omitted mapping.
- Final combined command:
  `PYTHONPATH=../prosaic/src:../prosaic-runtime/src:src .venv/bin/python -m pytest tests/test_workflow_factory.py tests/test_admission_data.py tests/test_schema_profile.py tests/test_legacy_loader_admission.py -q --tb=short`
  completed with **119 passed in 1.03s**, including **49 factory cases**.
- `git diff --check`: clean.

Review correction for Runtime route names: two real route-name cases first failed
against the alias regex (**2 failed / 54 passed**), then passed after the scoped
policy correction. Final factory verification: **56 passed**; the combined
factory/admission/schema/legacy verification after this correction is recorded by
the parent execution ledger.

Independent review also corrected resolved-schema budgets to count each schema
root's bytes, depth and nodes, with only body bytes aggregated. Bounded normalized
step-map keys do not consume schema capacity. Regressions cover the exact four-byte
`true` body, rejection of five-byte `false`, unknown map keys, and nine separately
valid 8,000-element schema roots. Typed resource cardinality is checked before
tuple conversion or JSON snapshots; native validator version mappings receive the
host snapshot bound without executing callbacks. The final three regressions
were **3 failed / 58 passed** before their fixes. Combined verification after all
review corrections completed with **131 passed in 2.19s**, including **61 factory
cases**.

A full suite attempt first reached **256 passed / 51 errors** from sandbox-denied
test-only loopback bindings. Its approved loopback rerun reached **303 passed /
5 failed in 40.35s**, before the parent installed candidate dependencies. All
five failures were subprocess imports of the old installed Core lacking
`validate_artifact_definition`: shipped custom-tool reject (both variants),
fabricated-record rejection, no-live guard and CLI execution from another
directory. Parent owns the subsequent complete suite/build/wheel verification
with installed candidate Core/Runtime packages; this report does not claim a
green final full suite.
