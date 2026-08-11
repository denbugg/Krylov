from pathlib import Path
import py_compile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BotEntryContractTests(unittest.TestCase):
    def test_conversion_entrypoint_compiles_and_is_used_by_systemd(self):
        entry = ROOT / "bot_entry.py"
        py_compile.compile(str(entry), doraise=True)
        service = (ROOT / "deploy" / "elite-bot.service").read_text(encoding="utf-8")
        self.assertIn("/srv/elite-bot/current/site/bot_entry.py", service)

    def test_manager_can_filter_current_and_future_group_leads(self):
        text = (ROOT / "bot_entry.py").read_text(encoding="utf-8")
        self.assertIn('/leads trial', text)
        self.assertIn('/leads future', text)
        self.assertIn('future_group', text)
        self.assertIn('discovery_source', text)

    def test_token_configuration_has_single_hidden_prompt(self):
        text = (ROOT / "deploy" / "configure-telegram.sh").read_text(encoding="utf-8")
        self.assertIn('Telegram BotFather token (hidden): ', text)
        self.assertNotIn('Telegram bot username [', text)
        self.assertIn('/getMe', text)
        self.assertIn('requests.post', text)


if __name__ == "__main__":
    unittest.main()
