import pytest
from django.core.management import call_command
from django_celery_beat.models import CrontabSchedule, PeriodicTask


@pytest.mark.django_db
def test_setup_schedule_creates_periodic_task():
    call_command("setup_schedule")

    task = PeriodicTask.objects.get(name="run_scheduled_ingestions")
    assert task.task == "ingestion.tasks.run_scheduled_ingestions"
    assert task.enabled is True
    assert task.crontab is not None
    assert task.interval is None
    assert task.crontab.hour == "9,13,17"
    assert task.crontab.day_of_week == "1-5"
    assert str(task.crontab.timezone) == "America/New_York"


@pytest.mark.django_db
def test_setup_schedule_is_idempotent():
    call_command("setup_schedule")
    call_command("setup_schedule")

    assert PeriodicTask.objects.filter(name="run_scheduled_ingestions").count() == 1
    assert CrontabSchedule.objects.count() == 1


@pytest.mark.django_db
def test_setup_schedule_reenables_a_disabled_task():
    call_command("setup_schedule")
    task = PeriodicTask.objects.get(name="run_scheduled_ingestions")
    task.enabled = False
    task.save(update_fields=["enabled"])

    call_command("setup_schedule")

    task.refresh_from_db()
    assert task.enabled is True
