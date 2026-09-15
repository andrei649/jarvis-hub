"""Typed automation forms. Prompts use only the existing governed agent path.

Monitors request evidence from configured tools; they never imply a connector exists.
"""

from __future__ import annotations


def text(key, label, default="", required=True):
    return {
        "key": key,
        "label": label,
        "type": "text",
        "required": required,
        "default": default,
        "max_length": 500,
    }


EXTRA_BLUEPRINTS = [
    (
        "price_watch",
        "Price watch",
        "every day at 9:00",
        [
            text("product", "Product or URL"),
            {
                "key": "threshold",
                "label": "Price threshold",
                "type": "number",
                "required": True,
                "default": 100,
                "minimum": 0,
            },
        ],
        "Check the current price for {product}. Report only new prices below {threshold}, with source and currency. Never purchase.",
    ),
    (
        "competitor_watch",
        "Competitor watch",
        "every weekday at 9:00",
        [text("competitor", "Competitor or website")],
        "Review public updates for {competitor}. Summarize material changes since the previous run with dated sources.",
    ),
    (
        "weekly_review",
        "Weekly review",
        "0 17 * * 5",
        [text("focus", "Review focus", "completed work and open commitments")],
        "Prepare a weekly review of {focus}: outcomes, blockers, unfinished commitments and suggested next steps.",
    ),
    (
        "calendar_preview",
        "Calendar preview",
        "every weekday at 7:00",
        [text("horizon", "Planning horizon", "today")],
        "Review my configured calendar for {horizon}. Flag conflicts, preparation needs and travel gaps. Do not modify events.",
    ),
    (
        "research_digest",
        "Research digest",
        "every weekday at 8:00",
        [text("topic", "Research topic")],
        "Find new research about {topic}. Compare with prior notes, include primary sources and uncertainty; distinguish evidence from opinion.",
    ),
    (
        "project_checkin",
        "Project check-in",
        "every weekday at 16:00",
        [text("project", "Project")],
        "Review {project} using available project context. Report changed blockers, milestone progress and the next decision needed.",
    ),
    (
        "meeting_prep",
        "Meeting preparation",
        "every weekday at 8:00",
        [text("meeting", "Meeting or participant")],
        "Prepare for {meeting} using configured calendar and existing notes: objectives, unresolved questions and relevant context. Do not contact anyone.",
    ),
    (
        "learning_review",
        "Learning review",
        "every day at 18:00",
        [text("subject", "Learning subject")],
        "Prepare a short active-recall exercise for {subject}, adapting to prior notes, then include an answer key.",
    ),
    (
        "habit_reminder",
        "Habit reminder",
        "every day at 12:00",
        [text("habit", "Habit", "Take a short walk")],
        None,
    ),
    (
        "subscription_review",
        "Subscription review",
        "0 9 1 * *",
        [text("scope", "Subscriptions to review", "my recorded subscriptions")],
        "Review {scope} from existing records. Highlight upcoming renewals and missing cost information. Never cancel or buy anything.",
    ),
    (
        "backup_review",
        "Backup review",
        "0 9 * * 1",
        [text("scope", "Backup system", "configured local backups")],
        "Review available status evidence for {scope}. Report last verified backup, failures and evidence gaps. Do not run commands or alter backups.",
    ),
]


def extend_catalog(catalog):
    for bid, title, schedule, fields, prompt in EXTRA_BLUEPRINTS:
        catalog[bid] = {
            "title": title,
            "description": (
                "A fixed reminder. No model."
                if prompt is None
                else "Uses configured agent capabilities; unavailable sources are reported explicitly."
            ),
            "schedule_text": schedule,
            "action": {"type": "remind", "message": "{habit}"}
            if prompt is None
            else {"type": "ask", "agent": "jarvis", "prompt": prompt, "deliver": True},
            "params": ["schedule_text", *[f["key"] for f in fields]],
            "fields": fields,
            "template": True,
        }
    for spec in catalog.values():
        spec.setdefault(
            "fields",
            [
                text(
                    k,
                    k.replace("_", " ").title(),
                    spec["action"].get(k, ""),
                    k in ("message", "prompt"),
                )
                for k in spec["params"]
                if k != "schedule_text"
            ],
        )
        spec["fields"] = [
            {
                "key": "schedule_text",
                "label": "Schedule",
                "type": "text",
                "required": False,
                "default": spec["schedule_text"],
                "max_length": 200,
            },
            *spec["fields"],
        ]


def validate_params(spec, params):
    values = {}
    for field in spec["fields"]:
        key = field["key"]
        value = params.get(key, field.get("default"))
        if field["type"] == "number":
            if isinstance(value, str):
                try:
                    value = float(value)
                except ValueError:
                    raise ValueError(f"{key} must be a number") from None
            if type(value) not in (int, float) or not field.get("minimum", 0) <= value <= 1e12:
                raise ValueError(f"{key} must be a finite number between 0 and 1000000000000")
        elif value is not None:
            if not isinstance(value, str) or len(value) > field.get("max_length", 500):
                raise ValueError(f"{key} must be bounded text")
            if field.get("required") and not value.strip():
                raise ValueError(f"blueprint needs a {key}")
        values[key] = value
    return values
