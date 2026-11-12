# Harness 0.9.17 — bounded sub-agents

Host-authored workflow nodes and conversations can select named specialists using Runtime 0.9.23. The host binds each alias to an independent context pack and a reviewed local read inventory. Parent nodes use their existing tool list. Specialists return schema-checked findings and may contribute observations through the parent's citation contract.

Harness freezes the selected context and reserves the shared allowance before dispatch. It adopts a saved parent receipt offline and rechecks current grants before reusing delegated results. A dispatched parent with no parent receipt stays interrupted.

Enable delegation storage explicitly. PostgreSQL users need adapter 0.4.5 and its owner migration for existing stores. See the [authoring and recovery guide](sub-agents.md) and [adapter notes](release-postgres-0.4.5.md).
