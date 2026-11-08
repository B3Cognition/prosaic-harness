# Harness 0.9.13.dev0 context-pack candidate

Unpublished development candidate paired with Runtime0.9.19.dev0 and optional
Harness PostgreSQL0.4.2.dev0. Core0.5.0 and recorder0.3.0 remain unchanged.
See [context packs](context-packs.md) and the [runnable Markdown example](../examples/context-packs/workflow.yml).

Opt-in workflows use checkpoint v3, invocation receipt v2 and guard proof v2.
Opt-in conversations use session and receipt wrappers v3. Old record encodings
remain readable; pack-free callers keep their existing identities and payloads.

Drain writers, back up owned data and explicitly migrate using the schema owner
before enabling packs. Runtime roles do not perform DDL. Rollback disables new
pack admission and keeps compatible readers available to settle v3 operations;
never downgrade markers or send old writers into the upgraded namespace.

The linked qualification manifest records exact local artifact hashes and tests.
Hosted CI, including native Intel macOS, remains a separate required promotion
gate. Synthetic correctness does not establish live-model quality or savings.
