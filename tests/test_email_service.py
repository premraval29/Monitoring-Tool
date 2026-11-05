import unittest
import asyncio
from unittest.mock import patch, MagicMock
from app.services.email_service import MailjetEmailService
from app.main import (
    get_email_settings,
    update_email_settings,
    send_test_email_endpoint,
    alert_state_manager,
    evaluate_alerts,
)

class TestMailjetEmailService(unittest.TestCase):
    def setUp(self):
        self.service = MailjetEmailService({
            "enabled": True,
            "provider": "mailjet",
            "api_key": "29d0b23ae14c1227ac447b6b3f9d7036",
            "secret_key": "cbedbdce0fedb02cc97043fc49262081",
            "sender_email": "vardhakpatel6@gmail.com",
            "sender_name": "PulseMon Alert Manager",
            "recipient_email": "admin@example.com",
            "send_on_resolved": True,
        })

    def test_initialization_defaults(self):
        self.assertEqual(self.service.sender_email, "vardhakpatel6@gmail.com")
        self.assertEqual(self.service.recipient_email, "admin@example.com")
        self.assertTrue(self.service.enabled)
        self.assertTrue(self.service.send_on_resolved)
        self.assertTrue(self.service.is_configured())

    def test_format_alert_email(self):
        alert_data = {
            "key": "CPU",
            "source": "CPU",
            "level": "danger",
            "message": "High CPU utilization: 96.5% (Threshold: 90.0%)",
            "time_str": "16:20:00",
        }
        snapshot = {
            "system": {
                "uptime_human": "2d 4h 12m",
                "cpu": {"total_percent": 96.5, "load_avg": [3.2, 2.8, 2.1]},
                "ram": {"percent": 74.2},
            }
        }
        subject, html, text = self.service.format_alert_email(alert_data, snapshot)
        self.assertIn("DANGER", subject)
        self.assertIn("CPU", subject)
        self.assertIn("High CPU utilization: 96.5%", html)
        self.assertIn("vardhakpatel6@gmail.com", self.service.sender_email)
        self.assertIn("System Uptime", html)
        self.assertIn("2d 4h 12m", html)
        self.assertIn("High CPU utilization: 96.5%", text)

    def test_format_resolution_email(self):
        alert_data = {
            "key": "CPU",
            "source": "CPU",
            "level": "resolved",
            "message": "CPU utilization resolved: 24.5% (under limit 90.0%)",
            "time_str": "16:25:00",
            "active_duration_seconds": 185,
        }
        subject, html, text = self.service.format_resolution_email(alert_data)
        self.assertIn("RESOLVED", subject)
        self.assertIn("CPU", subject)
        self.assertIn("3m 5s", html)
        self.assertIn("resolved", text.lower())

    @patch("urllib.request.urlopen")
    def test_send_message_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"Messages": [{"Status": "success", "To": [{"Email": "admin@example.com"}]}]}'
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        res = self.service.send_message(
            subject="Test Alert",
            html_content="<p>Test HTML</p>",
            text_content="Test plain",
        )
        self.assertEqual(res["status"], "success")
        self.assertIn("admin@example.com", res["message"])
        self.assertTrue(mock_urlopen.called)

        # Verify request auth header and body
        req = mock_urlopen.call_args[0][0]
        self.assertTrue(req.headers.get("Authorization", "").startswith("Basic "))
        self.assertEqual(req.headers.get("Content-type"), "application/json")

    def test_send_message_missing_recipient(self):
        self.service.recipient_email = ""
        res = self.service.send_message(
            subject="Test",
            html_content="<p>Test</p>",
            text_content="Test",
        )
        self.assertEqual(res["status"], "error")
        self.assertIn("No recipient email", res["message"])

    def test_send_message_disabled_skips(self):
        self.service.enabled = False
        res = self.service.send_message(
            subject="Test",
            html_content="<p>Test</p>",
            text_content="Test",
            force=False,
        )
        self.assertEqual(res["status"], "skipped")

    def test_api_email_endpoints(self):
        # 1. GET /api/settings/email
        get_res = asyncio.run(get_email_settings())
        self.assertEqual(get_res["status"], "success")
        self.assertIn("email", get_res)
        self.assertEqual(get_res["email"]["sender_email"], "vardhakpatel6@gmail.com")

        # 2. POST /api/settings/email
        post_res = asyncio.run(update_email_settings({
            "recipient_email": "ops-team@company.com",
            "send_on_resolved": True,
            "enabled": True,
        }))
        self.assertEqual(post_res["status"], "success")
        self.assertEqual(post_res["email"]["recipient_email"], "ops-team@company.com")

        # Restore clean recipient
        asyncio.run(update_email_settings({"recipient_email": ""}))

    def test_transition_event_emission(self):
        alert_state_manager.reset_all()

        high_payload = {
            "system": {"cpu": {"total_percent": 96.0}, "ram": {"percent": 30.0}, "disk": {"partitions": []}},
            "databases": [],
        }
        low_payload = {
            "system": {"cpu": {"total_percent": 20.0}, "ram": {"percent": 30.0}, "disk": {"partitions": []}},
            "databases": [],
        }

        # T = 1000s: Start breach -> pending_breach (no alert)
        evaluate_alerts(high_payload, now=1000.0)

        # T = 1095s (>= 90s): Transition to firing!
        # Should include transition_event == "firing"
        firing_alerts = evaluate_alerts(high_payload, now=1095.0)
        self.assertEqual(len(firing_alerts), 1)
        self.assertEqual(firing_alerts[0]["state"], "firing")
        self.assertEqual(firing_alerts[0].get("transition_event"), "firing")

        # T = 1096s: Still firing -> NO duplicate transition_event!
        steady_alerts = evaluate_alerts(high_payload, now=1096.0)
        self.assertEqual(len(steady_alerts), 1)
        self.assertEqual(steady_alerts[0]["state"], "firing")
        self.assertIsNone(steady_alerts[0].get("transition_event"))

        # T = 1100s: Drops under limit -> pending_recovery
        evaluate_alerts(low_payload, now=1100.0)

        # T = 1195s (>= 90s under limit): Transition to resolved!
        # Should include transition_event == "resolved"
        resolved_alerts = evaluate_alerts(low_payload, now=1195.0)
        self.assertEqual(len(resolved_alerts), 1)
        self.assertEqual(resolved_alerts[0]["state"], "resolved")
        self.assertEqual(resolved_alerts[0].get("transition_event"), "resolved")

        # T = 1196s: Still resolved -> NO duplicate transition_event!
        steady_res = evaluate_alerts(low_payload, now=1196.0)
        self.assertEqual(len(steady_res), 1)
        self.assertIsNone(steady_res[0].get("transition_event"))

if __name__ == "__main__":
    unittest.main()

