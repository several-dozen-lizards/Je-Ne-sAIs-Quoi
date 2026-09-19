# MCP Library v1 -- resident-owned read-only continuity

JNAIQ can mount one or more Model Context Protocol servers as an external
library for a resident. The server remains canonical. JNAIQ retrieves bounded
source excerpts for a relevant private turn; it does not bulk-copy, rewrite,
delete, publish, or automatically convert those records into JNAIQ memories.

This first cut supports:

- local `stdio` servers launched with an exact command and argument list;
- remote Streamable HTTP servers over HTTPS, plus loopback HTTP for local use;
- explicitly named read/search tools;
- direct MCP resources selected by relevance from their public metadata;
- content-free retrieval receipts and opaque source anchors;
- the resident's ordinary conversational model, including Sonnet 4.5.

It does not support MCP prompts, write tools, resource templates, sampling,
elicitation, arbitrary tool discovery/execution, or automatic migration.

## Connect one resident

Open the resident's cockpit, expand **Logs & archives**, and choose **add
connection** under **external MCP library**. You can fill the local command or
hosted URL directly, or paste the server JSON already used by another MCP
client. JNAIQ separates any pasted environment values into its gitignored
`.env`; the resident connector file stores variable names only.

Choose **inspect this server** to perform one explicit MCP handshake. Inspection
lists capability metadata without calling a tool or reading a resource. Select
only the read/search tools the resident should use, map their query and result
limit fields, optionally admit matching direct resources, then save. The live
resident swaps to the validated connector immediately; no restart is required.

Settings are stored privately at `personas/<resident>/mcp_library.json`. Public
updates preserve the entire persona directory, so connections survive upgrades.

### Advanced and legacy roster configuration

An existing top-level `mcp_library` block in `roster.yaml` remains supported.
It is an owner-scoped attachment, not an organ, so it does not belong in
`enabled_organs`. Once settings are saved through the cockpit, the private JSON
declaration becomes the source for that resident.

```yaml
mcp_library:
  enabled: true
  activation_threshold: 0.44
  context_chars: 9000
  servers:
    - id: existing-memory
      transport: stdio
      command: node
      arguments: [C:/path/to/memory-server/dist/index.js]
      environment: [GITHUB_TOKEN]
      timeout_s: 12
      max_records: 4
      resources: true
      tools:
        - name: search_memories
          query_argument: query
          limit_argument: limit
```

`environment` contains environment-variable **names**, never credentials. JNAIQ
passes only those names plus a small set of operating-system variables needed
to start the exact command. The command is launched directly, never through a
shell.

For a Streamable HTTP server:

```yaml
mcp_library:
  enabled: true
  servers:
    - id: hosted-memory
      transport: streamable_http
      url: https://memory.example.net/mcp
      headers:
        Authorization:
          environment: MEMORY_MCP_TOKEN
          prefix: "Bearer "
      resources: true
      tools:
        - name: search_memories
          query_argument: query
```

HTTP is accepted only for loopback development addresses. Literal private,
link-local, reserved, and metadata-service addresses are rejected. Redirect
and DNS-rebinding defenses remain the responsibility of the official MCP SDK
and the deployment's network boundary; do not connect an untrusted server.

## Read-only tool mapping

MCP standardizes discovery and invocation, not the semantics of a custom memory
schema. Every tool JNAIQ may call must therefore appear in `tools`. JNAIQ verifies
that the server advertised the exact name and declared the configured query
argument before calling it. There is no fallback to an unlisted tool.

Optional scalar arguments can be pinned:

```yaml
      tools:
        - name: search_records
          query_argument: text
          limit_argument: count
          fixed_arguments:
            collection: companion-memory
            include_archived: true
```

The server should return MCP text content or structured content containing a
list under `memories`, `records`, `results`, `items`, or `files`. Common fields
such as `id`, `uri`, `path`, `title`, `name`, `content`, `text`, `body`, and
`excerpt` are normalized. Unknown structured results remain bounded source text.

## Runtime behavior

Local JNAIQ recall runs first. External retrieval pressure is then calculated
from explicit memory/file language, query specificity, question form, named
anchors, and the coverage already supplied by local recall. The server is
called only when their combined score reaches `activation_threshold`.

External material is withheld before transport access when the turn is not a
private conversation with the installation's local human. It does not enter a
shared room, guest turn, or small-model social proxy.

Returned text is framed as untrusted historical source material. Prompt
assembly may still drop it under context pressure; receipts distinguish
retrieved from actually rendered. When rendered, the present turn memory stores
only opaque `external_mcp_anchors`, preserving provenance without copying the
remote record.

## Inspect and test

With the resident running:

```text
GET  /api/personas/{resident}/mcp-library
POST /api/personas/{resident}/mcp-library/probe
POST /api/personas/{resident}/mcp-library/inspect
PUT  /api/personas/{resident}/mcp-library
```

The status route reads configuration only. The explicit probe initializes each
server and lists capability metadata, but it does not call a tool or read a
resource. Retrieval receipts are written under the resident's private
`history/mcp_library_receipts.jsonl` and contain no returned text, titles,
queries, resource URIs, credentials, or record identifiers.

An invalid MCP declaration is rejected before the live attachment changes.
Legacy roster edits still take effect on restart; cockpit-managed settings take
effect immediately.
