"""
services/email_service.py

Phase 8 — Post-Call Summary Email

Sends HTML summary email via:
  Primary:  Azure Communication Services (free 100 emails/day)
  Fallback: SendGrid (free 100 emails/day)
"""
from datetime import datetime
from typing import Optional
from jinja2 import Template

from config.settings import get_settings
from utils.logger import logger

settings = get_settings()

EMAIL_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body { font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }
    .header { background: #1E3A5F; color: white; padding: 20px; border-radius: 8px 8px 0 0; }
    .header h1 { margin: 0; font-size: 20px; }
    .header p { margin: 5px 0 0; opacity: 0.8; font-size: 13px; }
    .content { background: #f9f9f9; padding: 20px; border: 1px solid #ddd; }
    .section { background: white; padding: 15px; margin-bottom: 15px; border-radius: 6px;
                border-left: 4px solid #38BDF8; }
    .section h3 { margin: 0 0 10px; color: #1E3A5F; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; }
    .badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px;
             font-weight: bold; margin: 2px; }
    .badge-intent { background: #e0f2fe; color: #0369a1; }
    .badge-resolved { background: #dcfce7; color: #166534; }
    .badge-escalated { background: #fef3c7; color: #92400e; }
    .footer { background: #eee; padding: 12px 20px; font-size: 11px; color: #666;
              border-radius: 0 0 8px 8px; text-align: center; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    td, th { padding: 8px; text-align: left; border-bottom: 1px solid #eee; }
    th { background: #f0f0f0; font-weight: bold; }
    .ref { font-family: monospace; background: #f0f4f8; padding: 4px 8px; border-radius: 4px; }
  </style>
</head>
<body>
  <div class="header">
    <h1>📞 Call Summary</h1>
    <p>{{ org_name }} — Voice Navigator</p>
  </div>
  <div class="content">

    <div class="section">
      <h3>Call Overview</h3>
      <table>
        <tr><th>Caller</th><td>{{ caller_name }}</td></tr>
        <tr><th>Phone</th><td>{{ caller_phone }}</td></tr>
        <tr><th>Date & Time</th><td>{{ call_date }}</td></tr>
        <tr><th>Duration</th><td>~{{ duration_estimate }} minutes</td></tr>
        <tr><th>Reference</th><td><span class="ref">{{ call_id }}</span></td></tr>
        <tr><th>Status</th><td>
          <span class="badge badge-{{ status_class }}">{{ status_label }}</span>
        </td></tr>
        {% if agent_name %}
        <tr><th>Agent</th><td>{{ agent_name }}</td></tr>
        {% endif %}
      </table>
    </div>

    <div class="section">
      <h3>Topics Discussed</h3>
      {% for intent in intent_history %}
        <span class="badge badge-intent">{{ intent.replace('_', ' ') }}</span>
      {% endfor %}
    </div>

    <div class="section">
      <h3>Summary</h3>
      {{ ai_summary | safe }}
    </div>

    {% if documents_referenced %}
    <div class="section">
      <h3>Documents Referenced</h3>
      <ul style="margin: 0; padding-left: 20px; font-size: 13px;">
        {% for doc in documents_referenced %}
          <li>{{ doc }}</li>
        {% endfor %}
      </ul>
    </div>
    {% endif %}

    {% if next_steps %}
    <div class="section" style="border-left-color: #FB923C;">
      <h3>Next Steps</h3>
      {{ next_steps | safe }}
    </div>
    {% endif %}

  </div>
  <div class="footer">
    This is an automated summary from Voice Navigator.
    Call ID: {{ call_id }} | Generated: {{ generated_at }}
  </div>
</body>
</html>
"""


class EmailService:
    """
    Sends post-call summary emails.
    Primary: Azure Communication Services (free 100/day)
    Fallback: SendGrid free tier
    """

    def send_call_summary(
        self,
        to_email: str,
        caller_name: str,
        caller_phone: str,
        call_id: str,
        intent_history: list[str],
        conversation_turns: int,
        ai_summary: str,
        documents_referenced: list[str],
        agent_name: Optional[str] = None,
        is_resolved: bool = True,
        next_steps: str = "",
        org_name: str = "Voice Navigator",
    ) -> bool:
        """
        Render and send the call summary email.
        Returns True if sent successfully.
        """
        html = self._render_html(
            caller_name=caller_name,
            caller_phone=caller_phone,
            call_id=call_id,
            intent_history=intent_history,
            conversation_turns=conversation_turns,
            ai_summary=ai_summary,
            documents_referenced=documents_referenced,
            agent_name=agent_name,
            is_resolved=is_resolved,
            next_steps=next_steps,
            org_name=org_name,
        )

        subject = f"Your Call Summary — {datetime.utcnow().strftime('%B %d, %Y')} | Ref: {call_id[:8].upper()}"

        # Try Azure Communication Services first
        if settings.azure_comm_connection_string:
            try:
                self._send_via_azure(to_email, subject, html)
                logger.info("email_sent_azure", to=to_email, call_id=call_id)
                return True
            except Exception as e:
                logger.warning("azure_email_failed", error=str(e))

        # Fallback to SendGrid
        try:
            self._send_via_sendgrid(to_email, subject, html)
            logger.info("email_sent_sendgrid", to=to_email, call_id=call_id)
            return True
        except Exception as e:
            logger.error("email_send_failed", error=str(e), to=to_email)
            return False

    def _render_html(self, **kwargs) -> str:
        """Render the Jinja2 HTML template."""
        t = Template(EMAIL_HTML_TEMPLATE)
        return t.render(
            **kwargs,
            call_date=datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC"),
            duration_estimate=max(1, kwargs.get("conversation_turns", 1) * 2),
            status_label="Resolved" if kwargs.get("is_resolved") else "Escalated to Agent",
            status_class="resolved" if kwargs.get("is_resolved") else "escalated",
            generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        )

    def _send_via_azure(self, to: str, subject: str, html: str):
        """Send via Azure Communication Services Email."""
        from azure.communication.email import EmailClient

        client = EmailClient.from_connection_string(
            settings.azure_comm_connection_string
        )
        message = {
            "content": {
                "subject": subject,
                "html": html,
            },
            "recipients": {"to": [{"address": to}]},
            "senderAddress": settings.azure_comm_sender_email,
        }
        poller = client.begin_send(message)
        result = poller.result()
        if result.get("status") == "Failed":
            raise RuntimeError(f"Azure email failed: {result}")

    def _send_via_sendgrid(self, to: str, subject: str, html: str):
        """Send via SendGrid (free 100/day)."""
        import sendgrid
        from sendgrid.helpers.mail import Mail

        sg = sendgrid.SendGridAPIClient(api_key=settings.azure_comm_connection_string)  # reuse key field
        message = Mail(
            from_email=settings.azure_comm_sender_email or "noreply@voicenavigator.ai",
            to_emails=to,
            subject=subject,
            html_content=html,
        )
        response = sg.send(message)
        if response.status_code not in (200, 202):
            raise RuntimeError(f"SendGrid failed: {response.status_code}")


def get_email_service() -> EmailService:
    return EmailService()
