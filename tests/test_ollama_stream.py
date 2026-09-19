import unittest

from umbra.ollama_client import OllamaEngine


class FakeClient:
    def chat(self, **_kwargs):
        yield {"message": {"content": "checking "}}
        yield {"message": {"tool_calls": [{"function": {
            "name": "read", "arguments": {"path": "README.md"}}}]}}
        yield {"message": {"content": "done"}}


class OllamaStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_keeps_all_text_and_native_calls_across_chunks(self):
        engine = OllamaEngine("http://localhost:11434", "test")
        engine._ollama = FakeClient()
        chunks = []
        calls, content = await engine.chat([], chunks.append)
        self.assertEqual(content, "checking done")
        self.assertEqual(chunks, ["checking ", "done"])
        self.assertEqual(calls, [{"name": "read", "arguments": {"path": "README.md"}}])
        self.assertTrue(engine.last_native)

    async def test_connection_error_is_not_masked_by_tools_retry(self):
        engine = OllamaEngine("http://localhost:11434", "test")

        class Flaky:
            def __init__(self):
                self.calls = 0

            def chat(self, **_kwargs):
                self.calls += 1
                raise ConnectionError("unable to connect to host")

        client = Flaky()
        engine._ollama = client
        with self.assertRaises(ConnectionError):
            await engine.chat([], lambda _t: None)
        self.assertEqual(client.calls, 1)

    async def test_tools_rejection_falls_back_to_text_protocol(self):
        engine = OllamaEngine("http://localhost:11434", "test")

        class ToolsRejectedOnce:
            def __init__(self):
                self.calls = 0

            def chat(self, **kwargs):
                self.calls += 1
                if kwargs.get("tools"):
                    raise RuntimeError("tools are not supported by this model")
                yield {"message": {"content": "plain answer"}}

        client = ToolsRejectedOnce()
        engine._ollama = client
        calls, content = await engine.chat([], lambda _t: None)
        self.assertEqual(client.calls, 2)
        self.assertEqual(content, "plain answer")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
