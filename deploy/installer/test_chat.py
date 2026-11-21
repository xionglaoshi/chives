"""Regression tests for CLI turns sharing a task with the web workbench."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import chives_chat as chat


def message(mid, role, content):
    return {"id": mid, "role": role, "kind": "text", "content": content}


class SharedTurns(unittest.TestCase):
    def test_stream_disconnect_reads_only_accepted_turn(self):
        api = Mock()
        api.open.return_value = nullcontext(iter(()))
        # The next web turn has already restarted the same task.
        api.json.side_effect = [
            {"taskId": "same-task", "messageId": "cli"},
            {"task": {"status": "running"}, "messages": [
                message("prev", "bot", "earlier web answer"),
                message("cli", "user", "terminal question"),
                message("mine", "bot", "answer to terminal"),
                message("web", "user", "new web question"),
                message("next", "bot", "answer to web"),
            ]},
        ]
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(StringIO()):
            chat.reply(api, {"id": "expert", "name": "投资专家"}, "terminal question")
        self.assertEqual(output.getvalue(), "answer to terminal\n")
        self.assertEqual([c.args[0] for c in api.json.call_args_list],
                         ["/api/bots/expert/messages", "/api/tasks/same-task"])

    def test_uncertain_submission_is_never_retried(self):
        api = Mock()
        api.open.return_value = nullcontext(iter(()))
        api.json.side_effect = ConnectionResetError()
        with self.assertRaisesRegex(RuntimeError, "提交状态待确认"):
            chat.reply(api, {"id": "expert", "name": "投资专家"}, "test")
        api.json.assert_called_once()

    def test_failed_followup_does_not_print_previous_answer(self):
        api = Mock()
        api.json.return_value = {"task": {"status": "failed", "errorCode": "model_auth"},
                                 "messages": [message("prev", "bot", "old answer"),
                                              message("cli", "user", "new question")]}
        output = StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, "model_auth"):
            chat.persisted_result(api, "same-task", "cli", "投资专家")
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
