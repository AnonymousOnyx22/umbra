import unittest

from umbra.sessions import Session


class SessionTests(unittest.TestCase):
    def test_from_dict_tolerates_unknown_and_missing_keys(self):
        s = Session.from_dict({
            "name": "nightly",
            "messages": [{"role": "user", "content": "hi"}],
            "not_a_field": 123,
        })
        self.assertEqual(s.name, "nightly")
        self.assertEqual(s.messages, [{"role": "user", "content": "hi"}])
        self.assertEqual(s.cwd, "")
        self.assertEqual(s.model, "")
        self.assertIsInstance(s.created, float)
        self.assertEqual(s.input_tokens, 0)

    def test_round_trip(self):
        s = Session("n", "c", "m")
        s.messages = [{"role": "user", "content": "yo"}]
        self.assertEqual(Session.from_dict(s.to_dict()), s)


if __name__ == "__main__":
    unittest.main()