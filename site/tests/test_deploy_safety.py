from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


class DeploySafetyTests(unittest.TestCase):
    def read(self, name: str) -> str:
        return (DEPLOY / name).read_text(encoding="utf-8")

    def test_nginx_has_independent_upstream_fallback(self):
        for name in ("nginx.conf.template", "nginx.https.conf.template"):
            text = self.read(name)
            self.assertIn("proxy_intercept_errors on;", text)
            self.assertIn("error_page 502 503 504 /fallback/index.html;", text)
            self.assertIn("root /srv/elite;", text)

    def test_runtime_uses_atomic_current_release(self):
        site_service = self.read("elite.service")
        bot_service = self.read("elite-bot.service")
        self.assertIn("WorkingDirectory=/srv/elite/current/site", site_service)
        self.assertIn("/srv/elite/current/venv/bin/gunicorn", site_service)
        self.assertIn("WorkingDirectory=/srv/elite/current/site", bot_service)
        self.assertIn("/srv/elite/current/venv/bin/python", bot_service)

    def test_updater_builds_candidate_before_switch(self):
        text = self.read("update.sh")
        self.assertIn("CANDIDATE_PORT=18000", text)
        self.assertIn("Running security/regression tests against candidate", text)
        self.assertIn("Starting isolated candidate smoke test", text)
        self.assertIn("touch \"$release/.prepared\"", text)
        self.assertIn("atomic_link \"$RELEASE\" \"$CURRENT\"", text)
        self.assertIn("restore_old_release", text)

    def test_atomic_link_helpers_are_nounset_safe(self):
        unsafe = 'local target="$1" link="$2" tmp="${link}.new"'
        for name in ("update.sh", "rollback.sh"):
            text = self.read(name)
            self.assertNotIn(unsafe, text, name)
            self.assertIn('local target="$1"', text, name)
            self.assertIn('local link="$2"', text, name)
            self.assertIn('local tmp="${link}.new"', text, name)

    def test_watchdog_and_backup_are_present(self):
        self.assertTrue((DEPLOY / "watchdog.sh").is_file())
        self.assertTrue((DEPLOY / "elite-watchdog.timer").is_file())
        self.assertTrue((DEPLOY / "backup-leads.sh").is_file())
        self.assertTrue((DEPLOY / "elite-backup.timer").is_file())

    def test_fallback_keeps_conversion_channels(self):
        text = self.read("fallback.html")
        self.assertIn("https://t.me/Undina_007", text)
        self.assertIn("tel:+79169653513", text)
        self.assertIn("noindex,nofollow", text)

    def test_no_old_single_venv_runtime_paths(self):
        for name in (
            "elite.service",
            "elite-bot.service",
            "configure-telegram.sh",
            "rollback.sh",
        ):
            self.assertNotIn("/srv/elite/venv/", self.read(name), name)


if __name__ == "__main__":
    unittest.main()
