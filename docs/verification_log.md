# Verification log

Technical claims checked against current documentation before the code that depends on them is written. A status is `VALIDATED`, `INVALIDATED` or `INSUFFICIENT_DOCS`.

| Date | Claim | Source and version | Status | Used by | Reference |
|---|---|---|---|---|---|
| 2026-11-02 | The reference sequential-thinking MCP server exposes one tool, `sequentialthinking` (`thought`, `nextThoughtNeeded`, `thoughtNumber`, `totalThoughts`, plus optional revision and branch fields). It runs over stdio through `npx -y @modelcontextprotocol/server-sequential-thinking` or `docker run --rm -i mcp/sequentialthinking`, and `DISABLE_THOUGHT_LOGGING=true` turns off its thought logging. | Context7 `/modelcontextprotocol/servers`, main branch | `VALIDATED` | The gated `reflect` tool (CH-68) | `src/sequentialthinking/README.md` and `index.ts` |
