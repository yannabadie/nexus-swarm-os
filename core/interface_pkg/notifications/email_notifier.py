"""
Email Notifier - Outlook SMTP

Sends review notifications via email.
"""

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


class EmailNotificationError(Exception):
    """Custom exception for email sending failures"""

    pass


def send_review_email(
    config, generation: int, children: list[dict], hours_elapsed: int, template_type: str = "review_ready"
) -> bool:
    """
    Send review notification email via Outlook SMTP.

    Args:
        config: Config instance with email settings
        generation: Current generation number
        children: List of child NEXUS dicts (id, score, etc.)
        hours_elapsed: Hours since evaluation started
        template_type: "review_ready", "review_reminder", or "review_critical"

    Returns:
        bool: True if email sent successfully

    Raises:
        EmailNotificationError: If email fails to send
    """
    # Check if email enabled
    if not config.email_enabled:
        return False

    # Check password configured
    if not config.email_password:
        raise EmailNotificationError("Email password not configured. Set NEXUS_EMAIL_PASSWORD in .env")

    # Prepare email content
    children_summary = "\n".join(
        [f"  - {child['id']}: Score {child['score']:.2f} ({child['improvement']:+.1%} vs parent)" for child in children]
    )

    pending_file = Path(config.workspace_path) / ".nexus" / "PENDING_REVIEW.md"
    deadline = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Select template
    templates = {
        "review_ready": {
            "subject": f"[NEXUS] Generation {generation} - Review Required ({len(children)} children)",
            "body": f"""
Generation {generation} Evolution Complete

Children Awaiting Review: {len(children)}

{children_summary}

Deadline: {deadline} (recommended: {config.recommended_eval_hours}h)
Location: {pending_file}

Use command: nexus (gen:{generation}) > /review

---
NEXUS Evolution Engine
Automated notification - Do not reply
""",
        },
        "review_reminder": {
            "subject": f"[NEXUS] [WARN]️ Review Overdue - Generation {generation}",
            "body": f"""
[WARN]️ REMINDER: Review is overdue

Generation {generation} has been awaiting review for {hours_elapsed}h.
Recommended deadline: {config.recommended_eval_hours}h

Children: {len(children)}
Location: {pending_file}

{children_summary}

Use command: nexus (gen:{generation}) > /review

---
NEXUS Evolution Engine
""",
        },
        "review_critical": {
            "subject": "[NEXUS] 🚨 CRITICAL - Review Required (72h+)",
            "body": f"""
🚨 CRITICAL ALERT

Generation {generation} review is CRITICAL (elapsed: {hours_elapsed}h).

Evolution is BLOCKED until review is completed.

Children: {len(children)}
Location: {pending_file}

{children_summary}

IMMEDIATE ACTION REQUIRED
Use command: nexus (gen:{generation}) > /review

---
NEXUS Evolution Engine
""",
        },
    }

    template = templates.get(template_type, templates["review_ready"])

    # Create message
    msg = MIMEMultipart()
    msg["From"] = config.email_from
    msg["To"] = config.email_to
    msg["Subject"] = template["subject"]
    msg.attach(MIMEText(template["body"], "plain"))

    try:
        # Connect to Outlook SMTP
        with smtplib.SMTP(config.smtp_server, config.smtp_port) as server:
            server.starttls()  # Enable TLS encryption
            server.login(config.email_from, config.email_password)
            server.send_message(msg)

        print(f"[EMAIL] [OK] Sent {template_type} to {config.email_to}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        raise EmailNotificationError(f"SMTP Authentication failed. Check email/password in .env. Error: {e}") from e
    except smtplib.SMTPException as e:
        raise EmailNotificationError(f"SMTP error: {e}") from e
    except Exception as e:
        raise EmailNotificationError(f"Unexpected error sending email: {e}") from e


def test_email_config(config) -> bool:
    """
    Test email configuration by sending a test email.

    Args:
        config: Config instance

    Returns:
        bool: True if test email sent successfully
    """
    try:
        msg = MIMEText("NEXUS email notification test - Configuration OK!")
        msg["From"] = config.email_from
        msg["To"] = config.email_to
        msg["Subject"] = "[NEXUS] Email Test"

        with smtplib.SMTP(config.smtp_server, config.smtp_port) as server:
            server.starttls()
            server.login(config.email_from, config.email_password)
            server.send_message(msg)

        print(f"[EMAIL TEST] [OK] Test email sent to {config.email_to}")
        return True

    except Exception as e:
        print(f"[EMAIL TEST] [X] Failed: {e}")
        return False
