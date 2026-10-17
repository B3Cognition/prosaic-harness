# Bounded tool recovery

`WorkflowPolicy(bounded_tool_recovery=True)` requires Runtime capabilities
`tool_outcomes_v1` and `bounded_tool_recovery_v1`. The default remains false and
is omitted from legacy policy identities. Enabling it changes the sealed identity.

ALWAYS correct only validated pre-dispatch argument failures or a missing required
tool within existing workflow attempts and resource caps.
NEVER interpret handler error strings or model dictionaries as recovery authority.

ALWAYS block missing, malformed, foreign-version or uncertain completion evidence.
NEVER automatically repeat a callback after denial, controlled failure, an
interrupted request or an unknown effect. Reconcile effects outside this policy.

ALWAYS use successful required-tool evidence already present in the invocation.
NEVER repeat that tool solely because an earlier argument request was rejected.

Feedback uses fixed `toolRecovery` categories and declared tool aliases; exception
messages, arguments and result contents do not enter corrective feedback. Existing
receipt-only recovery and durable accounting remain authoritative.
