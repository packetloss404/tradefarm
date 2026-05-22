from __future__ import annotations

from tradefarm.orchestrator.broadcast_os import BroadcastMoment, BroadcastOutput
from tradefarm.orchestrator.broadcast_scheduler import BroadcastScheduler


def _moment(
    moment_id: str,
    *,
    priority: int = 50,
    outputs: tuple[BroadcastOutput, ...] = ("lower_third",),
    ttl_sec: int = 5,
    title: str | None = None,
) -> BroadcastMoment:
    return BroadcastMoment(
        id=moment_id,
        kind="activity",
        title=title or moment_id,
        priority=priority,
        outputs=outputs,
        ttl_sec=ttl_sec,
    )


def test_submit_activates_outputs_until_ttl_expires() -> None:
    scheduler = BroadcastScheduler()
    moment = _moment("headline", priority=80, outputs=("lower_third", "ticker"), ttl_sec=5)

    scheduled = scheduler.submit(moment, now=10.0)

    assert [active.moment.id for active in scheduled] == ["headline"]
    assert set(scheduler.active_slots) == {"lower_third", "ticker"}
    assert scheduler.expire(now=14.9) == ()

    expired = scheduler.expire(now=15.0)

    assert [active.moment.id for active in expired] == ["headline"]
    assert scheduler.active_slots == {}


def test_lower_priority_collision_waits_until_higher_priority_expires() -> None:
    scheduler = BroadcastScheduler()
    scheduler.submit(_moment("breaking", priority=90, ttl_sec=5), now=0.0)
    lower = _moment("ambient", priority=20, ttl_sec=4)

    scheduled = scheduler.submit(lower, now=1.0)

    assert scheduled == ()
    assert [moment.id for moment in scheduler.queued] == ["ambient"]
    assert scheduler.active_slots["lower_third"].moment.id == "breaking"

    scheduled_after_expiry = scheduler.drain(now=5.0)

    assert [active.moment.id for active in scheduled_after_expiry] == ["ambient"]
    assert scheduler.queued == ()
    assert scheduler.active_slots["lower_third"].moment.id == "ambient"


def test_higher_priority_preempts_lower_priority_on_conflicting_output() -> None:
    scheduler = BroadcastScheduler()
    scheduler.submit(
        _moment("ambient", priority=20, outputs=("lower_third", "ticker"), ttl_sec=20),
        now=0.0,
    )
    urgent = _moment("urgent", priority=95, outputs=("lower_third",), ttl_sec=5)

    scheduled = scheduler.submit(urgent, now=2.0)

    assert [active.moment.id for active in scheduled] == ["urgent"]
    assert [moment.id for moment in scheduled[0].preempted] == ["ambient"]
    assert set(scheduler.active_slots) == {"lower_third"}
    assert scheduler.active_slots["lower_third"].moment.id == "urgent"


def test_lower_priority_non_conflicting_output_can_run_while_high_priority_is_active() -> None:
    scheduler = BroadcastScheduler()
    scheduler.submit(_moment("banner", priority=90, outputs=("lower_third",), ttl_sec=10), now=0.0)
    ticker = _moment("ticker-note", priority=10, outputs=("ticker",), ttl_sec=5)

    scheduled = scheduler.submit(ticker, now=1.0)

    assert [active.moment.id for active in scheduled] == ["ticker-note"]
    assert scheduler.active_slots["lower_third"].moment.id == "banner"
    assert scheduler.active_slots["ticker"].moment.id == "ticker-note"


def test_equal_priority_queue_uses_fifo_time_order() -> None:
    scheduler = BroadcastScheduler()
    first = _moment("first", priority=50)
    second = _moment("second", priority=50)

    scheduler.enqueue(first, now=0.0)
    scheduler.enqueue(second, now=1.0)
    scheduled = scheduler.drain(now=2.0)

    assert [active.moment.id for active in scheduled] == ["first"]
    assert [moment.id for moment in scheduler.queued] == ["second"]
    assert scheduler.active_slots["lower_third"].moment.id == "first"


def test_enqueue_replaces_existing_queued_item_by_id() -> None:
    scheduler = BroadcastScheduler()
    scheduler.submit(_moment("breaking", priority=90, ttl_sec=5), now=0.0)
    old = _moment("queued", priority=20, title="old title")
    new = _moment("queued", priority=30, title="new title")

    scheduler.enqueue(old, now=1.0)
    result = scheduler.enqueue(new, now=2.0)

    assert result.accepted is True
    assert result.reason == "replaced"
    assert result.replaced == old
    assert [moment.title for moment in scheduler.queued] == ["new title"]

    scheduled = scheduler.drain(now=6.0)

    assert [active.moment.title for active in scheduled] == ["new title"]


def test_queue_capacity_drops_lowest_priority_newest_item() -> None:
    scheduler = BroadcastScheduler(max_queue_size=2)
    first = _moment("first", priority=10)
    second = _moment("second", priority=10)
    newest_low = _moment("newest-low", priority=10)
    better = _moment("better", priority=20)

    scheduler.enqueue(first, now=0.0)
    scheduler.enqueue(second, now=1.0)
    dropped_newest = scheduler.enqueue(newest_low, now=2.0)

    assert dropped_newest.accepted is False
    assert [moment.id for moment in dropped_newest.dropped] == ["newest-low"]
    assert [moment.id for moment in scheduler.queued] == ["first", "second"]

    dropped_for_better = scheduler.enqueue(better, now=3.0)

    assert dropped_for_better.accepted is True
    assert [moment.id for moment in dropped_for_better.dropped] == ["second"]
    assert [moment.id for moment in scheduler.queued] == ["better", "first"]
