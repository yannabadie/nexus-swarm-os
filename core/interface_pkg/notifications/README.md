# NEXUS Notifications Module

## Synopsis

The **notifications** module provides multi-channel notification capabilities for NEXUS. It supports email notifications, REPL alerts, and file-based logging for important system events, task completions, and error conditions.

## Architecture

```
+-------------------------------------------------------------------------+
|                    NOTIFICATION ARCHITECTURE                             |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                    NotificationManager                            |   |
|  |              Dispatches to configured channels                    |   |
|  +----------------------------+-------------------------------------+   |
|                               |                                          |
|         +---------------------+---------------------+                   |
|         |                     |                     |                   |
|         v                     v                     v                   |
|  +--------------+    +--------------+    +------------------+          |
|  |EmailNotifier |    | REPLAlert    |    |  FileNotifier    |          |
|  | (SMTP)       |    | (Console)    |    |  (Log file)      |          |
|  +--------------+    +--------------+    +------------------+          |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `email_notifier.py` | SMTP email notifications | `EmailNotifier` |
| `repl_alert.py` | Console/REPL alerts | `REPLAlert` |
| `file_notifier.py` | File-based notifications | `FileNotifier` |

## Key Interfaces

### EmailNotifier
```python
class EmailNotifier:
    """Sends email notifications via SMTP."""

    def __init__(self, smtp_config: SMTPConfig)
    async def send(self, subject: str, body: str, recipients: List[str])
    async def send_error_alert(self, error: Exception, context: Dict)
    async def send_task_complete(self, task_id: str, result: TaskResult)
```

### REPLAlert
```python
class REPLAlert:
    """Console alerts with optional sound/visual."""

    def alert(self, message: str, level: AlertLevel = AlertLevel.INFO)
    def error(self, message: str)
    def success(self, message: str)
    def bell(self)  # System bell
```

### FileNotifier
```python
class FileNotifier:
    """Writes notifications to log file."""

    def __init__(self, log_path: Path)
    def notify(self, event_type: str, data: Dict)
```

## Configuration

```bash
# .env configuration
NOTIFICATION_EMAIL_ENABLED=True
NOTIFICATION_EMAIL_SMTP_HOST=smtp.gmail.com
NOTIFICATION_EMAIL_SMTP_PORT=587
NOTIFICATION_EMAIL_USERNAME=user@gmail.com
NOTIFICATION_EMAIL_PASSWORD=app_password
NOTIFICATION_EMAIL_RECIPIENTS=admin@example.com
```

## Usage

```python
from core.notifications import EmailNotifier, REPLAlert

# Email notification
notifier = EmailNotifier(smtp_config)
await notifier.send_task_complete(task_id, result)

# REPL alert
alert = REPLAlert()
alert.success("Task completed successfully!")
alert.bell()  # Audible alert
```

## Dependencies

### External
- `aiosmtplib` - Async SMTP client (optional)
- Standard library (smtplib, email)

## Version History

- **V8.0** - Initial notification system
- **V12.2** - IRONCLAD: Enhanced email security
- **V12.4** - Async email support
