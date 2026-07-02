import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import docker_manager
from .database import query_all


LOG_TS_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
HOST_RE = re.compile(r"Host(?:\\?:|=|`|\\\")(?P<host>[A-Za-z0-9.-]+)")
RULE_RE = re.compile(r"id[:=]'?(?P<rule>\d+)")


def parse_log_time(line: str) -> datetime:
    match = LOG_TS_RE.search(line)
    if not match:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(match.group("ts")).replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def coraza_summary(hours: int = 24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    sites = [dict(row) for row in query_all("SELECT username, domain, waf_enabled FROM sites ORDER BY username")]
    enabled_sites = [site for site in sites if site["waf_enabled"]]
    events = []

    try:
        container = docker_manager.client().containers.get("hosting-traefik")
        raw_logs = container.logs(since=int(since.timestamp()), tail=5000).decode("utf-8", errors="replace")
    except Exception as exc:
        raw_logs = ""
        events.append(
            {
                "time": datetime.now(timezone.utc),
                "host": "-",
                "rule": "-",
                "message": f"Log Traefik belum bisa dibaca: {exc}",
            }
        )

    for line in raw_logs.splitlines():
        lowered = line.lower()
        if "coraza" not in lowered and "secrule" not in lowered and "waf" not in lowered:
            continue
        event_time = parse_log_time(line)
        host_match = HOST_RE.search(line)
        rule_match = RULE_RE.search(line)
        events.append(
            {
                "time": event_time,
                "host": host_match.group("host") if host_match else "-",
                "rule": rule_match.group("rule") if rule_match else "-",
                "message": line[-500:],
            }
        )

    hourly = Counter(event["time"].strftime("%H:00") for event in events)
    domain_counts = Counter(event["host"] for event in events if event["host"] != "-")
    max_hourly = max(hourly.values(), default=1)
    return {
        "hours": hours,
        "enabled_sites": enabled_sites,
        "total_events": len(events),
        "hourly": [{"label": label, "count": count, "percent": int(count / max_hourly * 100)} for label, count in sorted(hourly.items())],
        "domains": domain_counts.most_common(8),
        "events": sorted(events, key=lambda item: item["time"], reverse=True)[:80],
    }
