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

## Linting & Formatting

```bash
uv run ruff check .          # lint
uv run ruff format --check .  # format check
uv run ruff format .          # auto-format
```

CI runs both on every push (Python 3.12 + 3.13).

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

Restart Claude Desktop after any code change (it doesn't hot-reload MCP servers).

## Project Structure

```
mcp_server.py          # MCP server — all tool/prompt/resource definitions
app/
  fpl_client.py        # FPL API wrapper with caching + retry
  algorithms/          # Each tool's logic lives here
    captain.py         # Captain scoring algorithm (v2.1)
    rivals.py          # Mini-league rival intelligence
    chips.py           # Chip strategy with DGW prediction
    ...
tests/
  test_*.py            # Unit tests (190+ tests)
```

## Adding a New Tool

1. Create `app/algorithms/your_tool.py` with an async function
2. Add a `@mcp.tool()` handler in `mcp_server.py`
3. Include input validation and error handling with `_error()`
4. Add tests
5. Update the tools table in `README.md`

## Pull Requests

- Keep PRs focused — one feature or fix per PR
- Run `uv run ruff check . && uv run ruff format --check .` before submitting
- Run `uv run pytest tests/` before submitting
- Test with Claude Desktop if your changes affect MCP tools
