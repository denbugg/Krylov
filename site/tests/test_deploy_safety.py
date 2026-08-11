from pathlib import Path
import re
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

    def test_nginx_https_uses_current_http2_syntax(self):
        text = self.read("nginx.https.conf.template")
        self.assertNotIn("listen 443 ssl http2;", text)
        self.assertNotIn("listen [::]:443 ssl http2;", text)
        self.assertEqual(text.count("http2 on;"), 2)

    def test_site_and_bot_have_independent_release_roots(self):
        site_service = self.read("elite.service")
        bot_service = self.read("elite-bot.service")
        self.assertIn("WorkingDirectory=/srv/elite/current/site", site_service)
        self.assertIn("/srv/elite/current/venv/bin/gunicorn", site_service)
        self.assertIn("WorkingDirectory=/srv/elite-bot/current/site", bot_service)
        self.assertIn("/srv/elite-bot/current/venv/bin/python", bot_service)

    def test_bot_autodeploy_is_present(self):
        updater = self.read("bot-update.sh")
        bootstrap = self.read("bot-bootstrap.sh")
        self.assertIn("REPO=/srv/elite-bot/repo", updater)
        self.assertIn("CURRENT=/srv/elite-bot/current", updater)
        self.assertIn("origin elite-bot", updater)
        self.assertIn("bot-deployed-sha", updater)
        self.assertIn("/srv/elite-bot/repo", bootstrap)
        self.assertIn("install -d -m 0755 -o elite -g elite /srv/elite-bot /srv/elite-bot/releases", bootstrap)
        self.assertTrue((DEPLOY / "elite-bot-autodeploy.timer").is_file())

    def test_bot_bootstrap_requests_secure_configuration_when_token_missing(self):
        bootstrap = self.read("bot-bootstrap.sh")
        configure = self.read("configure-telegram.sh")
        self.assertIn("/usr/local/sbin/elite-configure-telegram", bootstrap)
        self.assertIn('read -r -s -p "Telegram BotFather token (hidden): "', configure)
        self.assertIn('/getMe', configure)
        self.assertIn('deleteWebhook', configure)
        self.assertIn('setMyCommands', configure)
        self.assertIn('TELEGRAM_ADMIN_USERNAME "Undina_007"', configure)

    def test_bot_runtime_check_uses_server_only_environment(self):
        updater = self.read("bot-update.sh")
        configure = self.read("configure-telegram.sh")
        self.assertIn("run_bot_check", updater)
        self.assertIn('LEADS_ENCRYPTION_KEY="$encryption_key"', updater)
        self.assertIn('TELEGRAM_BOT_TOKEN="$token"', updater)
        self.assertIn('LEADS_DB_PATH="$db_path"', updater)
        self.assertIn('LEADS_ENCRYPTION_KEY="$encryption_key"', configure)
        self.assertIn('TELEGRAM_BOT_TOKEN="$BOT_TOKEN"', configure)
        self.assertIn('LEADS_DB_PATH="$db_path"', configure)

    def test_bot_db_migration_runs_before_service_activation(self):
        updater = self.read("bot-update.sh")
        self.assertIn("run_db_migration", updater)
        self.assertIn('migrate-bot-db.py', updater)
        activation = updater.split('atomic_link "$RELEASE" "$CURRENT"', 1)[1]
        self.assertLess(activation.index('run_db_migration "$RELEASE"'), activation.index('systemctl restart elite-bot.service'))

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
        for name in ("update.sh", "rollback.sh", "bot-update.sh"):
            text = self.read(name)
            self.assertNotIn(unsafe, text, name)
            self.assertIn('local target="$1"', text, name)
            self.assertIn('local link="$2"', text, name)
            self.assertIn('local tmp="${link}.new"', text, name)

    def test_local_declarations_do_not_reference_same_line_locals(self):
        declaration = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)=")
        for path in DEPLOY.glob("*.sh"):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if not stripped.startswith("local "):
                    continue
                names = declaration.findall(stripped)
                for name in names:
                    if f"${name}" in stripped or f"${{{name}}}" in stripped:
                        self.fail(
                            f"{path.name}:{lineno} declares and references local {name!r} "
                            "on the same line; unsafe with set -u"
                        )

    def test_previous_release_comes_from_success_state(self):
        text = self.read("update.sh")
        self.assertIn('DEPLOYED_SHA="$(cat "$STATE_DIR/deployed-sha"', text)
        self.assertIn('OLD_RELEASE="$RELEASES/$DEPLOYED_SHA"', text)
        self.assertIn('if [ "$TARGET" = "$DEPLOYED_SHA" ]; then', text)
        self.assertIn('atomic_link "$OLD_RELEASE" "$PREVIOUS"', text)
        self.assertIn('printf \'%s\\n\' "$DEPLOYED_SHA" >"$STATE_DIR/previous-sha"', text)
        self.assertIn("clearing uncommitted current symlink", text)

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
