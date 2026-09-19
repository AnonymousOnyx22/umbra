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


if __name__ == "__main__":
    unittest.main()
