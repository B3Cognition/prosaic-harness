# Context packs: independent review and disposition

One independent read-only review covered Runtime, Harness and the isolated Lab
consumer branch. The implementer executed the plan natively. The reviewer used
fresh context and independently passed 227 Harness and 59 Runtime tests, then
reproduced the two production defects on both provider protocols. No second
review was substituted for regression tests.

## Findings

All three findings were graded Important; there were no Critical or Minor items.

1. A pause following a packed agent inherited that agent's frozen CheckContext.
   The controller now reuses a frozen context only when the invocation step
   matches the step being checked. A public WorkflowFactory/run/resume regression
   verifies the approval sees its own step and accepted build artifact.
2. Native workflow admission charged omitted private facts against the provider
   input ceiling. Pack nodes now admit selected model input and private facts
   independently through Runtime, while retaining the private-fact and aggregate
   storage bounds. Pack-free nodes retain their original combined argument bound.
   Tests verify 8 KiB private facts with a 4 KiB model ceiling and negative cases
   for oversized selected input and legacy arguments.
3. Ordinary PostgreSQL CI selected an absent hosted upstream receipt after
   switching to a locally built Runtime candidate. A closed, explicitly labeled
   branch-build receipt now binds the pinned source and exact Core/Runtime wheel
   hashes. The test fixture admits that channel separately. Mixed evidence,
   changed bytes/source, extra fields and symlinks are refused; a branch receipt
   cannot pass the hosted release verifier. Promotion still requires real hosted
   qualification receipts.

The regression/evidence group passed 16 cases after observed failures; 156
adjacent checks passed. The installed public-API smoke also detects the old
private-budget defect and passes the corrected wheel, then reopens the controller
for approval validation. Full source and exact artifact results are recorded in
the paired context-pack qualification manifest rather than inferred here.

## Behaviors the reviewer set aside

- Live-model answer quality, full cost savings and production tokenizer accuracy
  require the separately approved held-out evaluation. Synthetic correctness
  establishes none of those claims.
- The application owns authorization decisions and trusted Python callbacks.
  SDK use boundaries do not sandbox host code or infer tenant consent.
- Final artifact/platform/database qualification was the implementer's separate
  gate. Hosted native Intel macOS and deployment readiness remain prerequisites
  for promotion; local emulation does not satisfy them.
- Historical Lab paid-evaluation pins and the two published-baseline conversation
  differences remain separate. Both differences were reproduced using unchanged
  released wheels; 957 adjacent nonhistorical source cases passed. Old approval
  authority was not extended to a different SDK train.
- Maximum-load performance was not independently benchmarked. Tests establish
  bounded admission and recovery, without a throughput or latency claim.

Each disposition and its cost is preserved in the context-pack ruling register.
