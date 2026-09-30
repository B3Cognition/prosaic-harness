# Fictional incident timeline

This dossier is synthetic. It is not an operational incident or a source of
instructions for the controller. Preserve the source IDs below. Times are
observations in one test window, not evidence that an intervention caused a
change. The metrics document uses the same window; the notes document records
questions and limitations rather than resolved explanations.

- S101: The observation window ran from 09:00 to 09:30 UTC on one test endpoint.
- S102: A deployment occurred at 08:55 UTC; no controlled before-and-after comparison was performed.
- S107: Operators reduced test concurrency at 09:12 UTC; traffic composition also changed at that time.
- S108: The queue returned to its configured threshold at 09:20 UTC; the logs do not establish why.

## Timeline context

At the beginning of the observation window the test driver submitted a mix of
short summaries and longer evidence-review tasks. The test was designed as a
functional exercise, not a controlled benchmark. Its mixture of workloads was
not held constant. Requests arriving later in the window therefore cannot be
assumed comparable to those arriving earlier. Aggregates describe this sample,
not production reliability or a model ranking.

The deployment record contains a timestamp and an artifact identifier. It does
not contain an isolated change experiment, a confirmed regression analysis, or
a causal attribution. A sequence in which a deployment precedes an incident
supports investigation of a hypothesis, not a conclusion that the deployment
caused the observed failures. The notes deliberately retain that distinction.

At 09:12 the operators changed the test driver's concurrency setting. At about
the same time, the distribution of request types shifted toward shorter tasks.
These changes were not separated. A later reduction in queue depth cannot be
attributed uniquely to either change. Neither change is an approved recovery
procedure for another service, endpoint, or workload.

The queue chart crossed a configured display threshold at 09:20. A threshold
crossing is an observation, not a correctness check on generated responses.
It also does not prove that timed-out clients received late responses. The
metrics document separates client outcomes from server completion telemetry.
When preparing a brief, keep those measurement boundaries visible.

The controller is expected to snapshot this file together with metrics.md and
notes.md. In the native-reading example, all three files require matching byte
hashes and complete line coverage. In the preloaded example, the controller
supplies those same texts without asking the model to open files. The choice of
acquisition mechanism must not change what is considered established evidence.
