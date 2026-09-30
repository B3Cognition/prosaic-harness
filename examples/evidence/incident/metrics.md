# Fictional incident metrics

These values describe the timeline document's test window. They are a small,
uncontrolled sample. Percentages must identify their denominator and outcome
boundary. A server's eventual completion and a client's receipt are different
events; one must not silently replace the other.

- S103: Client-visible failures totaled 84 of 2,400 request attempts.
- S104: Of those 84 client-visible failures, 60 were timeouts and 24 were explicit errors.
- S105: The dashboard displayed 99% success by excluding timeouts from its denominator.
- S106: Server telemetry recorded eventual completion for 38 timed-out attempts; client delivery was not verified.
- S110: Correctness was not scored for the returned drafts.

## Measurement notes

The test driver counted request attempts, not unique users or business actions.
No deduplication analysis was performed. The aggregate therefore does not
support a statement about how many people were affected. Do not label the
attempt count as a user count. Similarly, no source connects a successful HTTP
response with a correct, useful, or accepted draft.

The client-visible failure count includes timeouts and explicit errors. A timeout
is a failed observation at that client boundary even if the server later records
completion. The telemetry for late completion does not include acknowledgements
from the client. It must not be subtracted from the failure count to manufacture
a higher client success rate. Late completion may suggest a useful investigation
into latency or cancellation, but the cause remains unconfirmed.

The dashboard's percentage is reported as a display convention rather than an
independent reliability finding. Its denominator differs from the test driver's
full attempt count. A brief may mention the display value if it also preserves
that definition. It must not equate the display with overall client reliability.
This dossier deliberately includes the denominator trap to exercise independent
review rather than just JSON formatting.

There was no correctness evaluation for the returned drafts. Transport success
does not establish factual accuracy, instruction compliance, or readiness for
launch. The evidence also contains no latency distribution, cost record, token
usage completeness study, or comparison to another model. Do not invent these
measurements because they would be useful in a real operational review.

The first recommended next step may be collection of missing measurements, but
it must be labelled as a proposal. The dossier contains no adopted service-level
objective, production capacity commitment, approved launch gate, or expenditure
authorization. The reviewer should reject an unsupported claim of any of these,
while allowing clearly proposed follow-up work grounded in the observed limits.
