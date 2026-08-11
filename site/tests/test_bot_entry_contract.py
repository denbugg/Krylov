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

    def test_token_configuration_is_one_step_and_visible(self):
        text = (ROOT / "deploy" / "configure-telegram.sh").read_text(encoding="utf-8")
        self.assertIn('Telegram BotFather token: ', text)
        self.assertNotIn('Telegram bot username [', text)
        self.assertNotIn('read -r -s', text)
        self.assertIn('/getMe', text)
        self.assertIn('requests.post', text)

    def test_bot_runtime_forces_ipv4_without_host_wide_changes(self):
        policy = (ROOT / "sitecustomize.py").read_text(encoding="utf-8")
        service = (ROOT / "deploy" / "elite-bot.service").read_text(encoding="utf-8")
        configure = (ROOT / "deploy" / "configure-telegram.sh").read_text(encoding="utf-8")
        self.assertIn('socket.AF_INET', policy)
        self.assertIn('allowed_gai_family', policy)
        self.assertIn('Environment=PYTHONPATH=/srv/elite-bot/current/site', service)
        self.assertIn('export PYTHONPATH="$CURRENT/site"', configure)


if __name__ == "__main__":
    unittest.main()