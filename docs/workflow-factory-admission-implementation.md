# Workflow factory bounded admission helpers

Task 3 implementation, 2026-10-10. Production integration and the complete Harness
suite remain owned by the coordinating implementation task.

Added `errors.py`, `admission_data.py`, and `schema_validation.py`, plus focused
behavior tests. No factory, graph, engine, storage, public export, or dependency
files were edited for this task.

`snapshot_json` preflights finite plain JSON iteratively before making an owned
copy. It limits expanded values, container depth, cycles, and encoded bytes;
benign aliases become independent owned containers. Byte counting matches default
`json.dumps` ASCII escaping and separators without allocating escaped strings.
Durable document callers must additionally budget their actual indentation.
`parse_bounded_json` checks UTF-8 transport size and raw container depth before
strict decoding, then applies the same value bounds. Duplicate keys, invalid
Unicode, numeric overflow/nonfinite values, and parser recursion become safe
`WorkflowAdmissionError` diagnostics.

Native schema admission uses the agreed version-1 profile keys. It snapshots
approved schemas, checks Draft 2020-12 syntax, visits schema positions, detects
duplicate resolved resource IDs/anchors before registry construction, resolves
static refs in a root-isolated no-retrieval Registry, and rejects dynamic refs,
unsupported dialects, missing targets, and containment/reference cycles. Under
the conservative profile, reference targets must be admitted schema positions;
ignored `const`, `enum`, and `examples` data cannot be promoted to executable
schemas by a pointer. Literal ref-like fields otherwise remain ordinary data.

`admit_schema` returns owned native content; with `profile=None`, it retains the
released YAML external-reference scan and metaschema check without new tree caps.
`evaluate_schema` returns bounded safe issue strings, stops at `max_errors`, and
raises `SchemaEvaluationError` for evaluator failures. Legacy evaluation retains
productive recursion, historical depth, and nested dialect selection. Regex and
combinator CPU remain a host-schema trust responsibility.

Verification used Python 3.12.14 and jsonschema 4.26.0:

```text
.venv/bin/python -m pytest tests/test_admission_data.py tests/test_schema_profile.py -q
55 passed in 0.16s
```

Initial tests failed against the missing APIs before implementation. A subsequent
exact ASCII DEL byte-boundary test failed before its counting correction.
Coverage includes 50-level aliased DAGs, benign ownership, depth/node/byte edges,
Unicode/duplicates/numbers, scoped defs/anchors/local IDs, unused collisions,
literal ref-like data, no cross-root/metaschema resolution, bounded diagnostics,
short-circuit error enumeration, and legacy productive recursion/nested dialects.
`git diff --check` passed. No live model endpoints or callbacks were executed.
Full integration, minimum-jsonschema/Python matrix, and clean-wheel checks are
pending the coordinating task's final verification.

## Shared YAML loader and review corrections

The loader now invokes shared resolved graph/artifact/schema admission after its
trusted path resolution and CLI preparation. Schema admission owns the released
external-reference scan; the loader translates its safe failures into compatible
legacy definition/internal-reference diagnostics. The released identity payload
and defaults are unchanged. An immutable serialized full registry snapshot is
retained outside identity, with fresh mapping reads for subsequent admission;
only demanded descriptors enter the fingerprint.

Review regressions now distinguish schema positions by scoped paths instead of
Python object identity, so singleton boolean literals cannot masquerade as schema
targets. Instance admission failures retain `WorkflowAdmissionError`; evaluator
failures remain `SchemaEvaluationError`. Root resource IDs are applied once,
including relative IDs and their nested resource/anchor scopes.

The new legacy-loader tests capture the unchanged pre-edit fingerprint
`88777fa42b190129c4d28f599ccf35f61f84206630e7eb71315670437c15875e`, retain productive
recursion, historical deep schema/instance trees, nested dialects, larger trusted
schemas and empty legacy read roots/gate property keys. The graph owner restored
the latter two released semantics. An intermediate broader run had 13 failures
from the old incomplete canonical artifact fixture; the coordinator fixed that
fixture. A later broader run had 100 passes and two failures: the then-pending
empty-read-root graph fix and the coordinator's changed legacy sandbox diagnostic.
Final focused verification after those integration fixes:

```text
PYTHONPATH=../prosaic/src:../prosaic-runtime/src:src .venv/bin/python -m pytest tests/test_admission_data.py tests/test_schema_profile.py tests/test_legacy_loader_admission.py tests/test_validation.py tests/test_custom_tools.py tests/test_cli_tools.py tests/test_cli_sandbox.py -q
104 passed in 12.03s
```

`git diff --check` is clean. Full-suite and packaged dependency-chain verification
remain with the coordinator after all integration changes.
