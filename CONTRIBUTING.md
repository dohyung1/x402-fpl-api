# Contributing to FPL Intelligence

Thanks for your interest! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/dohyung1/x402-fpl-api.git
cd x402-fpl-api
uv sync
```

## Running Tests

```bash
uv run pytest tests/ -v
```

## Testing with Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fpl": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/x402-fpl-api", "mcp_server.py"]
    }
  }
}
```

Restart Claude Desktop and try: "Analyze FPL team 5456980"

## Project Structure

```
mcp_server.py          # MCP server — all tool/prompt/resource definitions
app/
  fpl_client.py        # FPL API wrapper with caching
  algorithms/          # Each tool's logic lives here
    captain.py         # Captain scoring algorithm
    transfers.py       # Transfer suggestions
    ...
tests/
  test_x402.py         # Payment middleware tests
```

## Adding a New Tool

1. Create `app/algorithms/your_tool.py` with an async function
2. Add a `@mcp.tool()` handler in `mcp_server.py`
3. Include input validation and error handling with `_error()`
4. Add tests
5. Update the tools table in `README.md`

## Pull Requests

- Keep PRs focused — one feature or fix per PR
- Run tests before submitting
- Test with Claude Desktop if your changes affect MCP tools
