"""Regression tests for CLI turns sharing a task with the web workbench."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import chives_chat as chat
import chives_cli


def message(mid, role, content):
    return {"id": mid, "role": role, "kind": "text", "content": content}


class SharedTurns(unittest.TestCase):
    def test_only_documented_shell_commands_remain(self):
        for args in (["bot"], ["chat"], ["ask"], ["stop"]):
            with self.subTest(args=args), self.assertRaises(SystemExit), patch.object(chives_cli, "control") as service:
                chives_cli.main("release", args)
                service.assert_not_called()

    def test_bare_interactive_command_opens_web_workbench(self):
        with patch("sys.stdin.isatty", return_value=True), patch.object(chives_cli, "control") as service, \
                patch("chives_terminal.actions.open_page") as open_page:
            chives_cli.main("release", [])
            service.assert_called_once_with("release")
            open_page.assert_called_once_with()

    def test_cli_command_opens_terminal_workbench(self):
        with patch.object(chat, "run") as run:
            chives_cli.main("release", ["cli"])
            self.assertEqual(run.call_args.args[0], ["cli"])

    def test_bare_command_uses_stdin_for_script_queries(self):
        with patch.object(chat, "run") as run, patch("sys.stdin", StringIO("question")):
            chives_cli.main("release", [])
            self.assertEqual(run.call_args.args[0], ["ask"])

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
            chat.reply(api, {"id": "ceo", "name": "总经理"}, "terminal question")
        self.assertEqual(output.getvalue(), "answer to terminal\n")
        self.assertEqual([c.args[0] for c in api.json.call_args_list],
                         ["/api/bots/ceo/messages", "/api/tasks/same-task"])

    def test_uncertain_submission_is_never_retried(self):
        api = Mock()
        api.open.return_value = nullcontext(iter(()))
        api.json.side_effect = ConnectionResetError()
        with self.assertRaisesRegex(RuntimeError, "提交状态待确认"):
            chat.reply(api, {"id": "ceo", "name": "总经理"}, "test")
        api.json.assert_called_once()

    def test_failed_followup_does_not_print_previous_answer(self):
        api = Mock()
        api.json.return_value = {"task": {"status": "failed", "errorCode": "model_auth"},
                                 "messages": [message("prev", "bot", "old answer"),
                                              message("cli", "user", "new question")]}
        output = StringIO()
        with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, "model_auth"):
            chat.persisted_result(api, "same-task", "cli", "总经理")
        self.assertEqual(output.getvalue(), "")


class TerminalView(unittest.TestCase):
    def test_stream_summary_tools_usage_and_canonical_answer(self):
        from prompt_toolkit.input.defaults import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        from chives_terminal.workbench import Workbench
        from chives_terminal.screen import context_label
        bot = {"id":"ceo", "name":"总经理", "role":"分析", "model":"fixture"}
        with create_pipe_input() as inp:
            desk = Workbench(Mock(), [bot], Mock(), input=inp, output=DummyOutput())
            desk.bot = bot
            self.assertIn("待上报", context_label(desk.used, desk.size))
            desk.handle_event({"type":"draft.delta", "kind":"reasoning", "text":"公开摘要"})
            desk.handle_event({"type":"draft.delta", "kind":"text", "text":"临时草稿"})
            for state, kind in (("running","tool.started"), ("completed","tool.ended")):
                desk.handle_event({"type":kind, "tool":{"id":"call1","title":"核对资料","status":state}})
            desk.handle_event({"type":"usage","usage":{"used":2400,"size":10000}})
            desk.show_result(["正式答复"], {"status":"done"})
            desk.end_turn(None)
            desk.prepare(desk.app)
            self.assertEqual(desk.transcript.text.count("核对资料"), 1)
            self.assertEqual(desk.transcript.text.count("正式答复"), 1)
            self.assertNotIn("临时草稿", desk.transcript.text)
            self.assertIn("公开摘要", desk.transcript.text)
            self.assertIn("24%", context_label(desk.used, desk.size))


if __name__ == "__main__":
    unittest.main()
