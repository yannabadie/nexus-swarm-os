"""
REPL Alert - Boot-time notification

Displays alert message when PENDING_REVIEW exists.
"""


def get_repl_alert_message(pending_metadata: dict, config) -> str:
    """
    Generate REPL alert message for pending review.

    Args:
        pending_metadata: Metadata from check_pending_review()
        config: Config instance

    Returns:
        str: Formatted alert message for REPL
    """
    generation = pending_metadata["generation"]
    children_count = pending_metadata["children_count"]
    hours_elapsed = pending_metadata["hours_elapsed"]

    # Determine alert level based on elapsed time
    if hours_elapsed >= config.critical_review_hours:
        alert_level = "🚨 CRITICAL"
        color_code = "\033[91m"  # Red
    elif hours_elapsed >= config.recommended_eval_hours:
        alert_level = "[WARN]️  OVERDUE"
        color_code = "\033[93m"  # Yellow
    else:
        alert_level = "ℹ️  PENDING"
        color_code = "\033[94m"  # Blue

    reset_color = "\033[0m"

    # Build children summary
    children_lines = []
    for child in pending_metadata.get("children", [])[:3]:  # Show top 3
        improvement = child.get("improvement", 0)
        sign = "+" if improvement >= 0 else ""
        children_lines.append(f"  | +- {child['id']} (score: {child['score']:.2f}, {sign}{improvement:.1%})")

    if children_count > 3:
        children_lines.append(f"  | +- ... and {children_count - 3} more")

    children_summary = "\n".join(children_lines)

    message = f"""
{color_code}╭{"-" * 60}╮{reset_color}
{color_code}| {alert_level} REVIEW REQUIRED{" " * (60 - len(alert_level) - 17)}|{reset_color}
{color_code}╰{"-" * 60}╯{reset_color}
  |
  | Generation {generation} - {children_count} Children Awaiting Evaluation
  | Elapsed: {hours_elapsed:.1f}h / Recommended: {config.recommended_eval_hours}h
  |
{children_summary}
  |
  | Use: /review to start evaluation
  |
{color_code}╰{"-" * 60}╯{reset_color}
"""

    return message


def should_block_evolution(pending_metadata: dict, config) -> bool:
    """
    Determine if evolution should be blocked due to pending review.

    Args:
        pending_metadata: Metadata from check_pending_review()
        config: Config instance

    Returns:
        bool: True if evolution should be blocked
    """
    hours_elapsed = pending_metadata["hours_elapsed"]

    # Block evolution if review is critical (72h+)
    return hours_elapsed >= config.critical_review_hours
