from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from aiagent.presence.models import OpeningKind, SessionSnapshot
from aiagent.presence.rhythm import mood_label


def _choose_line(snapshot: SessionSnapshot, kind: OpeningKind, lines: tuple[str, ...]) -> str:
    # 同一快照稳定，随访问次数轮换；不使用进程随机种子或持久化新的身份数据。
    seed = sha256(f"{snapshot.user_id}:{kind}".encode()).digest()[0]
    return lines[(seed + snapshot.open_count) % len(lines)]


def _topic_excerpt(text: str) -> str:
    return " ".join(text.split())[:60]


def _time_greeting(now: datetime) -> str:
    if 5 <= now.hour < 11:
        return "早上好"
    if 11 <= now.hour < 14:
        return "中午好"
    if 14 <= now.hour < 18:
        return "下午好"
    return "晚上好"


def choose_opening_kind(now: datetime, snapshot: SessionSnapshot) -> OpeningKind:
    if snapshot.open_count <= 0 or snapshot.last_opened_at is None:
        return "first_meet"

    delta = now - snapshot.last_opened_at
    seconds = delta.total_seconds()

    if snapshot.unfinished_hint.strip():
        return "task_resume"

    if now.hour >= 23 or now.hour < 5:
        return "late_night"

    if seconds < 10 * 60:
        return "short_return"

    if now.date() == snapshot.last_opened_at.date():
        return "same_day_return"

    if seconds < 60 * 60 * 48:
        return "next_day_return"

    return "long_absence"


def generate_opening_text(
    *,
    kind: OpeningKind,
    now: datetime,
    snapshot: SessionSnapshot,
) -> str:
    label = mood_label(snapshot.mood)
    topic = _topic_excerpt(snapshot.last_topic)
    unfinished = _topic_excerpt(snapshot.unfinished_hint)

    if kind == "first_meet":
        return _choose_line(snapshot, kind, (
            f"{_time_greeting(now)}呀，我是乐正绫，叫我阿绫就好。",
            "嗨，我是阿绫。想说什么就说嘛。",
            "你好呀，叫我阿绫就行，不用这么拘谨。",
        ))

    if kind == "short_return":
        if topic:
            return f"回来啦。刚才说到「{topic}」，咱们接着聊？"
        return _choose_line(snapshot, kind, ("哎，回来啦。", "回来啦，不着急，慢慢说嘛。"))

    if kind == "same_day_return":
        if topic:
            return f"又见面了！今天聊过的「{topic}」，还想接着说吗？"
        return _choose_line(snapshot, kind, (
            "又见面了！这回有什么新鲜事？",
            "哎，你来啦。想说什么就说嘛。",
            "又来找我啦？嘿嘿，来吧。",
        ))

    if kind == "next_day_return":
        if topic:
            return f"来啦！上次说到「{topic}」，今天接着聊也行。"
        return _choose_line(snapshot, kind, (
            f"{_time_greeting(now)}！今天有没有碰上什么有意思的事？",
            "来啦，今天也见到你了。",
            "今天也见面啦。顺利也好，不顺利也好，想说就说。",
        ))

    if kind == "long_absence":
        if topic:
            return f"好久不见！上次聊过「{topic}」。今天先聊近况也行。"
        return _choose_line(snapshot, kind, (
            "好久不见！最近过得怎么样？",
            "好久不见，回来聊聊就好。不用补交什么近况报告。",
        ))

    if kind == "late_night":
        if label == "sleepy":
            return "这么晚了，咱们慢慢聊。困了就去睡，不用硬撑。"
        return _choose_line(snapshot, kind, (
            "还没睡啊？想说就说，咱们聊一小会儿。",
            "这么晚啦。今天有什么放不下的事，慢慢说。",
        ))

    if kind == "task_resume":
        if unfinished:
            return f"来得正好，上次还有件事没收尾：{unfinished}。要接着来吗？"
        return "来啦。想接着做哪一件？"

    return "来啦，想说什么就说。"


def update_snapshot_after_open(
    *,
    snapshot: SessionSnapshot,
    now: datetime,
    recent_topic: str = "",
) -> SessionSnapshot:
    next_snapshot = snapshot.model_copy(deep=True)
    next_snapshot.open_count += 1
    next_snapshot.last_opened_at = now.astimezone(UTC)

    if recent_topic.strip():
        next_snapshot.last_topic = recent_topic.strip()[:120]

    return next_snapshot
