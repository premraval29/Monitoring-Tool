import base64
import json
import logging
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

logger = logging.getLogger("pulsemon.email")

class MailjetEmailService:
    """Dispatches system alert notifications using Mailjet Send API v3.1."""

    MAILJET_API_URL = "https://api.mailjet.com/v3.1/send"
    DEFAULT_SENDER_EMAIL = "vardhakpatel6@gmail.com"
    DEFAULT_SENDER_NAME = "PulseMon Alert Manager"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.update_config(config or {})

    def update_config(self, config: Dict[str, Any]):
        """Updates service settings from config dictionary."""
        self.enabled = bool(config.get("enabled", True))
        self.api_key = str(config.get("api_key", "29d0b23ae14c1227ac447b6b3f9d7036")).strip()
        self.secret_key = str(config.get("secret_key", "cbedbdce0fedb02cc97043fc49262081")).strip()
        # Sender email is fixed to verified Mailjet sender
        self.sender_email = str(config.get("sender_email", self.DEFAULT_SENDER_EMAIL)).strip() or self.DEFAULT_SENDER_EMAIL
        self.sender_name = str(config.get("sender_name", self.DEFAULT_SENDER_NAME)).strip() or self.DEFAULT_SENDER_NAME
        self.recipient_email = str(config.get("recipient_email", "")).strip()
        self.send_on_resolved = bool(config.get("send_on_resolved", True))

    def is_configured(self) -> bool:
        """Returns True if minimum required credentials and recipient are configured."""
        return bool(self.api_key and self.secret_key and self.recipient_email and self.sender_email)

    def send_message(
        self,
        subject: str,
        html_content: str,
        text_content: str,
        recipient_override: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Synchronous HTTP call to Mailjet Send API v3.1."""
        target_recipient = (recipient_override or self.recipient_email).strip()

        if not target_recipient:
            return {"status": "error", "message": "No recipient email address configured."}

        if not self.enabled and not force:
            return {"status": "skipped", "message": "Email notifications are disabled."}

        if not self.api_key or not self.secret_key:
            return {"status": "error", "message": "Mailjet API key or Secret key is missing."}

        payload = {
            "Messages": [
                {
                    "From": {
                        "Email": self.sender_email,
                        "Name": self.sender_name,
                    },
                    "To": [
                        {
                            "Email": target_recipient,
                            "Name": "System Administrator",
                        }
                    ],
                    "Subject": subject,
                    "TextPart": text_content,
                    "HTMLPart": html_content,
                }
            ]
        }

        auth_str = f"{self.api_key}:{self.secret_key}"
        auth_bytes = auth_str.encode("utf-8")
        auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")

        req = urllib.request.Request(
            url=self.MAILJET_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth_b64}",
                "User-Agent": "PulseMon-Monitor/2.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                resp_body = resp.read().decode("utf-8")
                resp_json = json.loads(resp_body) if resp_body else {}

                messages = resp_json.get("Messages", [])
                if messages and messages[0].get("Status") == "success":
                    return {
                        "status": "success",
                        "message": f"Email successfully sent to {target_recipient}",
                        "data": resp_json,
                    }
                elif messages and messages[0].get("Errors"):
                    err_msg = json.dumps(messages[0].get("Errors"))
                    return {"status": "error", "message": f"Mailjet message error: {err_msg}"}
                return {
                    "status": "success",
                    "message": f"Email dispatched to {target_recipient}",
                    "data": resp_json,
                }
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")
                err_data = json.loads(err_body)
                err_msg = err_data.get("ErrorMessage") or err_data.get("message") or err_body
            except Exception:
                err_msg = err_body or str(e)
            logger.error(f"Mailjet HTTP Error {e.code}: {err_msg}")
            return {
                "status": "error",
                "code": e.code,
                "message": f"Mailjet API Error ({e.code}): {err_msg}",
            }
        except urllib.error.URLError as e:
            logger.error(f"Mailjet Connection Error: {e.reason}")
            return {"status": "error", "message": f"Failed to connect to Mailjet API: {e.reason}"}
        except Exception as e:
            logger.error(f"Mailjet Unexpected Exception: {e}")
            return {"status": "error", "message": f"Unexpected error dispatching email: {str(e)}"}

    def format_alert_email(
        self,
        alert_data: Dict[str, Any],
        system_snapshot: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, str, str]:
        """Formats rich HTML and plain text for an active alert breach."""
        source = alert_data.get("source", "System Component")
        message = alert_data.get("message", "Threshold breached")
        level = (alert_data.get("level") or "warning").upper()
        time_str = alert_data.get("time_str") or time.strftime("%H:%M:%S")
        date_str = time.strftime("%Y-%m-%d")

        is_critical = level in ("DANGER", "CRITICAL")
        accent_color = "#ef4444" if is_critical else "#f59e0b"
        badge_bg = "#fef2f2" if is_critical else "#fffbeb"
        badge_border = "#fca5a5" if is_critical else "#fde68a"
        badge_text = "#b91c1c" if is_critical else "#b45309"

        subject = f"[{level}] {source}: {message} - PulseMon Alert"

        # Contextual recommendation
        advice = "Check system processes and activity monitor logs."
        src_lower = source.lower()
        if "cpu" in src_lower:
            advice = "Investigate runaway background processes or high compute tasks via Activity Monitor / top."
        elif "memory" in src_lower or "ram" in src_lower:
            advice = "Review memory leak candidates and consider restarting memory-intensive database or worker processes."
        elif "disk" in src_lower:
            advice = "Clean up temp directories, vacuum database files, or archive large application log files."
        elif "database" in src_lower:
            advice = "Verify database service status, connectivity, and investigate slow running lock queries."

        # Snapshot rows
        snapshot_html = ""
        snapshot_text = ""
        if system_snapshot and "system" in system_snapshot:
            sys = system_snapshot["system"]
            cpu = sys.get("cpu", {})
            ram = sys.get("ram", {})
            uptime = sys.get("uptime_human", "N/A")
            cpu_total = cpu.get("total_percent", "N/A")
            ram_used = ram.get("percent", "N/A")
            load_avg = ", ".join(f"{x:.2f}" for x in cpu.get("load_avg", [])) if cpu.get("load_avg") else "N/A"

            snapshot_html = f"""
            <table style="width:100%;border-collapse:collapse;margin-top:16px;font-size:12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;">
              <tr style="border-bottom:1px solid #e2e8f0;">
                <td style="padding:8px 12px;color:#64748b;font-weight:600;">System Uptime</td>
                <td style="padding:8px 12px;color:#0f172a;font-weight:bold;">{uptime}</td>
              </tr>
              <tr style="border-bottom:1px solid #e2e8f0;">
                <td style="padding:8px 12px;color:#64748b;font-weight:600;">CPU Utilization</td>
                <td style="padding:8px 12px;color:#0f172a;font-weight:bold;">{cpu_total}% (Load: {load_avg})</td>
              </tr>
              <tr>
                <td style="padding:8px 12px;color:#64748b;font-weight:600;">RAM Memory Used</td>
                <td style="padding:8px 12px;color:#0f172a;font-weight:bold;">{ram_used}%</td>
              </tr>
            </table>
            """
            snapshot_text = f"\nSystem Snapshot:\n- Uptime: {uptime}\n- CPU: {cpu_total}% (Load: {load_avg})\n- RAM Used: {ram_used}%\n"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <title>{subject}</title>
        </head>
        <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;margin:0;padding:24px;background-color:#f1f5f9;color:#1e293b;">
          <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 6px -1px rgba(0,0,0,0.1),0 2px 4px -2px rgba(0,0,0,0.1);border:1px solid #e2e8f0;">
            
            <!-- Header Banner -->
            <div style="background:{accent_color};padding:20px 24px;color:#ffffff;">
              <div style="display:flex;align-items:center;justify-content:space-between;">
                <span style="font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;background:rgba(255,255,255,0.2);padding:3px 8px;border-radius:6px;">PulseMon Alert</span>
                <span style="font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;background:rgba(255,255,255,0.25);padding:3px 8px;border-radius:6px;">{level}</span>
              </div>
              <h1 style="margin:12px 0 4px 0;font-size:20px;font-weight:700;line-height:1.3;">{source} Sustained Limit Breach</h1>
              <p style="margin:0;font-size:13px;opacity:0.9;">Continuous breach exceeded sustained threshold window (&ge;90s).</p>
            </div>

            <!-- Content Area -->
            <div style="padding:24px;">
              <!-- Incident Card -->
              <div style="background:#f8fafc;border-left:4px solid {accent_color};border-radius:4px;padding:14px 16px;margin-bottom:18px;">
                <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:bold;margin-bottom:4px;">Violation Details</div>
                <div style="font-size:14px;color:#0f172a;font-weight:600;margin-bottom:6px;">{message}</div>
                <div style="font-size:12px;color:#64748b;">Triggered at: <strong>{time_str}</strong> ({date_str})</div>
              </div>

              <!-- Recommendation -->
              <div style="background:{badge_bg};border:1px solid {badge_border};border-radius:8px;padding:12px 16px;margin-bottom:18px;">
                <div style="font-size:11px;font-weight:700;color:{badge_text};text-transform:uppercase;margin-bottom:4px;">Recommended Action</div>
                <div style="font-size:12px;color:{badge_text};line-height:1.4;">{advice}</div>
              </div>

              <!-- Telemetry -->
              <div style="margin-top:16px;">
                <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;">Host Telemetry Snapshot</div>
                {snapshot_html}
              </div>

              <!-- CTA Button -->
              <div style="margin-top:24px;text-align:center;">
                <a href="http://localhost:8000" style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;font-size:13px;font-weight:600;padding:10px 22px;border-radius:8px;box-shadow:0 2px 4px rgba(79,70,229,0.3);">Open Live Monitoring Dashboard</a>
              </div>
            </div>

            <!-- Footer -->
            <div style="background:#f8fafc;padding:14px 24px;border-top:1px solid #e2e8f0;font-size:11px;color:#94a3b8;text-align:center;">
              PulseMon Real-time System &amp; Database Monitor &bull; Automated Alert Dispatcher
            </div>
          </div>
        </body>
        </html>
        """

        plain_text = f"""[PULSEMON ALERT - {level}]
Source: {source}
Message: {message}
Triggered At: {time_str} ({date_str})
Condition: Threshold sustained above limit for >= 90 seconds.
Recommended Action: {advice}
{snapshot_text}
Dashboard: http://localhost:8000
"""
        return subject, html_body, plain_text

    def format_resolution_email(
        self,
        alert_data: Dict[str, Any],
        system_snapshot: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, str, str]:
        """Formats rich HTML and plain text for a resolved alert."""
        source = alert_data.get("source", "System Component")
        message = alert_data.get("message", "Metric returned under limit")
        time_str = alert_data.get("time_str") or time.strftime("%H:%M:%S")
        date_str = time.strftime("%Y-%m-%d")
        dur_sec = alert_data.get("active_duration_seconds", 0)
        dur_str = f"{dur_sec // 60}m {dur_sec % 60}s" if dur_sec >= 60 else f"{dur_sec}s"

        subject = f"[RESOLVED] {source}: Normalized - PulseMon"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <title>{subject}</title>
        </head>
        <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;margin:0;padding:24px;background-color:#f1f5f9;color:#1e293b;">
          <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);border:1px solid #e2e8f0;">
            <div style="background:#10b981;padding:20px 24px;color:#ffffff;">
              <span style="font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;background:rgba(255,255,255,0.25);padding:3px 8px;border-radius:6px;">Resolved</span>
              <h1 style="margin:12px 0 4px 0;font-size:20px;font-weight:700;">{source} Alert Resolved</h1>
              <p style="margin:0;font-size:13px;opacity:0.9;">Metric has remained continuously below limit for 90 seconds.</p>
            </div>
            <div style="padding:24px;">
              <div style="background:#f0fdf4;border-left:4px solid #10b981;border-radius:4px;padding:14px 16px;margin-bottom:18px;">
                <div style="font-size:11px;color:#166534;text-transform:uppercase;font-weight:bold;margin-bottom:4px;">Resolution Status</div>
                <div style="font-size:14px;color:#14532d;font-weight:600;margin-bottom:6px;">{message}</div>
                <div style="font-size:12px;color:#166534;">Resolved at: <strong>{time_str}</strong> ({date_str}) &bull; Active duration: <strong>{dur_str}</strong></div>
              </div>
              <div style="text-align:center;margin-top:20px;">
                <a href="http://localhost:8000" style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;font-size:13px;font-weight:600;padding:10px 22px;border-radius:8px;">View System Dashboard</a>
              </div>
            </div>
            <div style="background:#f8fafc;padding:14px 24px;border-top:1px solid #e2e8f0;font-size:11px;color:#94a3b8;text-align:center;">
              PulseMon Real-time System &amp; Database Monitor
            </div>
          </div>
        </body>
        </html>
        """

        plain_text = f"""[PULSEMON ALERT RESOLVED]
Source: {source}
Status: {message}
Resolved At: {time_str} ({date_str})
Incident Active Duration: {dur_str}
Dashboard: http://localhost:8000
"""
        return subject, html_body, plain_text

    def send_test_email(self, recipient_override: Optional[str] = None) -> Dict[str, Any]:
        """Dispatches a test email to verify Mailjet credentials and recipient delivery."""
        recipient = (recipient_override or self.recipient_email).strip()
        if not recipient:
            return {"status": "error", "message": "Please specify a recipient email address to receive the test email."}

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        subject = "[TEST] PulseMon Alert System - Mailjet Integration Verified"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;padding:24px;background-color:#f1f5f9;color:#1e293b;">
          <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;padding:28px;">
            <div style="display:flex;align-items:center;margin-bottom:16px;">
              <span style="background:#4f46e5;color:#ffffff;font-size:11px;font-weight:700;padding:4px 10px;border-radius:6px;text-transform:uppercase;">Test Verification</span>
            </div>
            <h2 style="margin:0 0 10px 0;font-size:20px;color:#0f172a;">Mailjet Email Delivery Verified!</h2>
            <p style="font-size:13px;color:#475569;line-height:1.5;">This test email confirms that your PulseMon monitoring server can successfully dispatch alert notifications through the Mailjet API.</p>
            <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px;margin:18px 0;font-size:12px;color:#334155;">
              <div><strong>Sender:</strong> {self.sender_email} (Verified Mailjet Sender)</div>
              <div style="margin-top:4px;"><strong>Recipient:</strong> {recipient}</div>
              <div style="margin-top:4px;"><strong>Dispatched At:</strong> {timestamp}</div>
            </div>
            <p style="font-size:12px;color:#64748b;">You will receive sustained threshold breach alerts (&ge;90s) and recovery notices at this address.</p>
          </div>
        </body>
        </html>
        """

        plain_text = f"""[TEST] PulseMon Mailjet Integration Verified
Sender: {self.sender_email}
Recipient: {recipient}
Timestamp: {timestamp}
This test email confirms your PulseMon alert notifications are working properly.
"""
        return self.send_message(
            subject=subject,
            html_content=html_body,
            text_content=plain_text,
            recipient_override=recipient,
            force=True,
        )

