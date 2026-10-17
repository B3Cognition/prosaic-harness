# Harness 0.9.4

Publishes the reviewed typed bounded-recovery changes described in
[0.9.3](release-0.9.3.md), preserving the published 0.9.2 lifecycle fixes.

The unpublished 0.9.3 candidate exposed stale version paths in PostgreSQL
packaging fixtures. This candidate updates every adapter install/metadata and
upstream fixture to Harness 0.9.4 and Runtime 0.9.7. The failed 0.9.3 tag and
evidence remain immutable; no 0.9.3 bytes were published. Qualification gates
remain mandatory and PostgreSQL 0.4.0 is not republished.
