"""Domain research (Iteration 2): the MCP client, the research providers and the tool pins.

`discover` depends on `ResearchProvider` (`provider.py`), never on NotebookLM itself:
`NotebookLMProvider` (`nlm.py`) implements it over the MCP client (`mcp_client.py`), and the
research pack provider of step 10 behind the same interface. `pins.py` checks a server's
reported identity and its tools against `config/mcp_pins.yaml` before a run uses it (M10).
"""
