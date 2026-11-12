# Harness 0.9.16 — MCP read tools

Workflow nodes and conversations can use explicitly selected, host-approved MCP
tool aliases. Configure them with Runtime 0.9.22 and its optional `mcp` extra.
Harness checks the sealed registration and can adopt an existing receipt with
the MCP server offline. Current evidence authorization still controls retained
access.

The package retains the Runtime 0.9.21 dependency floor for workloads without MCP.
Use the published PostgreSQL store 0.4.4. No storage migration or adapter release
is required for MCP. See the [README](../README.md#mcp-tools-in-workflows-and-conversations)
for host setup.
