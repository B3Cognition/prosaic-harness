# Harness 0.9.3

Adds opt-in bounded tool recovery using Runtime 0.9.7 typed outcome evidence.
Complete turn-scoped call identities are validated before recovery; contradictory,
unmatched or malformed events block advancement. Terminal Runtime failures keep
precedence. Existing attempt, tool and token ceilings continue to apply.

ALWAYS require trusted outcomes and existing workflow allowance before another
attempt. NEVER retry an uncertain tool effect automatically.

Preserves the published 0.9.2 lifecycle and original-message retry fixes.
Default workflow identities and conversation bindings remain compatible.
Release qualification uses exact source and immutable artifact bytes, including
installed workflow/conversation and PostgreSQL gates. Store 0.4.0 artifacts are
compatibility witnesses and are not republished. Lab memory remains experimental.
