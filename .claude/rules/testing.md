# Testing

- pytest with `asyncio_mode = auto`: async tests are plain `async def test_...`.
- One behaviour per test, named as a sentence: `test_stops_when_the_same_tool_call_repeats`.
- Arrange, act, assert, separated by blank lines.
- Fake only the boundaries. The LLM is `ScriptedLLM` (`app/adapters/llm/scripted_llm.py`)
  with the `say(...)` and `call_tool(...)` helpers. Your own `httpx` clients are faked with
  `respx`; provider SDKs are faked at the port, not at the HTTP layer. Do not mock
  services, the agent loop or the tool registry.
- API tests use `TestClient(app)` and `app.dependency_overrides[get_agent_service]`.
- Every new tool gets: valid call, invalid arguments, domain failure, and (if it does I/O)
  timeout and malformed response.
- Every new agent behaviour gets a loop test and, when it changes what users see, a line in
  the golden dataset.
- No network and no real API keys in tests.
- A failing test is fixed in the implementation. Change the test only when the test is
  wrong, and say why first.
