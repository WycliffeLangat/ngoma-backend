import io
import socket
import traceback
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection, models, transaction
from django.utils import timezone

from .models import ChartCalculationJob, ChartUpload, WeeklyUpload


class NamedBytesIO(io.BytesIO):
    def __init__(self, content, name):
        super().__init__(content)
        self.name = name


def _async_jobs_enabled():
    return bool(getattr(settings, 'CHART_JOBS_ASYNC', True))


def _user_id(user):
    return user.pk if getattr(user, 'is_authenticated', False) else None


def enqueue_chart_job(
    job_type,
    payload=None,
    *,
    user=None,
    dedupe_key='',
    priority=100,
    max_attempts=3,
    run_inline=None,
):
    """Create a chart calculation job and optionally run it immediately."""
    payload = payload or {}
    active_statuses = [
        ChartCalculationJob.Status.QUEUED,
        ChartCalculationJob.Status.RUNNING,
    ]
    if dedupe_key:
        existing = (
            ChartCalculationJob.objects
            .filter(dedupe_key=dedupe_key, status__in=active_statuses)
            .order_by('priority', 'created_at')
            .first()
        )
        if existing:
            return existing

    job = ChartCalculationJob.objects.create(
        job_type=job_type,
        payload=payload,
        dedupe_key=dedupe_key or '',
        priority=priority,
        max_attempts=max_attempts,
        created_by_id=_user_id(user),
    )
    if run_inline is None:
        run_inline = not _async_jobs_enabled()
    if run_inline:
        now = timezone.now()
        job.status = ChartCalculationJob.Status.RUNNING
        job.locked_by = 'inline'
        job.locked_at = now
        job.started_at = now
        job.attempts += 1
        job.save(update_fields=[
            'status', 'locked_by', 'locked_at', 'started_at', 'attempts', 'updated_at',
        ])
        process_job(job)
        job.refresh_from_db()
    return job


def enqueue_harmonize_job(*, user=None, chart_type=None, chart_ids=None, priority=60):
    chart_ids = [int(value) for value in (chart_ids or []) if value]
    chart_type = str(chart_type or '')
    scope = ','.join(str(value) for value in sorted(chart_ids)) if chart_ids else chart_type or 'all'
    return enqueue_chart_job(
        ChartCalculationJob.JobType.HARMONIZE_CHART_HISTORY,
        {
            **({'chart_type': chart_type} if chart_type else {}),
            **({'chart_ids': chart_ids} if chart_ids else {}),
        },
        user=user,
        dedupe_key=f'harmonize:{scope}',
        priority=priority,
    )


def _job_worker_id():
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:10]}"


def claim_next_job(worker_id=None, stale_after_minutes=45):
    worker_id = worker_id or _job_worker_id()
    now = timezone.now()
    stale_before = now - timedelta(minutes=stale_after_minutes)
    retryable = (
        ChartCalculationJob.objects
        .filter(status=ChartCalculationJob.Status.RUNNING, locked_at__lt=stale_before)
        .exclude(attempts__gte=models.F('max_attempts'))
    )
    if retryable.exists():
        retryable.update(status=ChartCalculationJob.Status.QUEUED, locked_by='', locked_at=None)

    with transaction.atomic():
        qs = ChartCalculationJob.objects.filter(status=ChartCalculationJob.Status.QUEUED)
        if connection.features.has_select_for_update:
            qs = qs.select_for_update(skip_locked=connection.features.has_select_for_update_skip_locked)
        job = qs.order_by('priority', 'created_at').first()
        if not job:
            return None
        job.status = ChartCalculationJob.Status.RUNNING
        job.locked_by = worker_id
        job.locked_at = now
        job.started_at = job.started_at or now
        job.finished_at = None
        job.attempts += 1
        job.save(update_fields=[
            'status', 'locked_by', 'locked_at', 'started_at',
            'finished_at', 'attempts', 'updated_at',
        ])
        return job


def _weekly_file(upload):
    content = bytes(upload.workbook_data or b'')
    if not content:
        return None
    filename = str(getattr(upload.file, 'name', '') or f'{upload}.xlsx')
    filename = filename.replace('\\', '/').rsplit('/', 1)[-1] or 'weekly-chart.xlsx'
    return NamedBytesIO(content, filename)


def _process_weekly_upload(payload):
    from .pipeline import process_weekly_upload

    upload = WeeklyUpload.objects.get(pk=payload['weekly_upload_id'])
    result = process_weekly_upload(
        upload,
        file_obj=_weekly_file(upload),
        harmonize=payload.get('harmonize', True),
    )
    upload.refresh_from_db()
    upload.processing_notes = str(result)
    upload.save(update_fields=['processing_notes'])
    return result


def _rebuild_month(payload):
    from .pipeline import rebuild_monthly_chart

    return rebuild_monthly_chart(
        payload['chart_type'],
        int(payload['year']),
        int(payload['month']),
        harmonize=payload.get('harmonize', True),
    )


def _publish_chart_upload(payload):
    from .cms_utils import publish_chart_upload

    upload = ChartUpload.objects.get(pk=payload['chart_upload_id'])
    user = User.objects.filter(pk=payload.get('user_id')).first()
    chart, count = publish_chart_upload(upload, user=user)
    return {'chart_id': chart.id, 'entries_created': count}


def _harmonize_chart_history(payload):
    from .cms_utils import harmonize_chart_history

    return harmonize_chart_history(
        chart_type=payload.get('chart_type'),
        chart_ids=payload.get('chart_ids') or [],
    )


def perform_chart_job(job):
    handlers = {
        ChartCalculationJob.JobType.PROCESS_WEEKLY_UPLOAD: _process_weekly_upload,
        ChartCalculationJob.JobType.REBUILD_MONTH: _rebuild_month,
        ChartCalculationJob.JobType.PUBLISH_CHART_UPLOAD: _publish_chart_upload,
        ChartCalculationJob.JobType.HARMONIZE_CHART_HISTORY: _harmonize_chart_history,
    }
    handler = handlers.get(job.job_type)
    if not handler:
        raise ValueError(f'Unsupported chart calculation job type: {job.job_type}')
    return handler(job.payload or {})


def process_job(job):
    try:
        result = perform_chart_job(job)
    except Exception as exc:
        now = timezone.now()
        job.error = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-12000:]
        job.result = {}
        job.locked_by = ''
        job.locked_at = None
        job.finished_at = now
        job.status = (
            ChartCalculationJob.Status.FAILED
            if job.attempts >= job.max_attempts
            else ChartCalculationJob.Status.QUEUED
        )
        job.save(update_fields=[
            'status', 'result', 'error', 'locked_by', 'locked_at',
            'finished_at', 'updated_at',
        ])
        _mark_related_upload_failed(job, exc)
        return False

    job.status = ChartCalculationJob.Status.SUCCEEDED
    job.result = result or {}
    job.error = ''
    job.locked_by = ''
    job.locked_at = None
    job.finished_at = timezone.now()
    job.save(update_fields=[
        'status', 'result', 'error', 'locked_by', 'locked_at',
        'finished_at', 'updated_at',
    ])
    return True


def _mark_related_upload_failed(job, exc):
    if job.job_type != ChartCalculationJob.JobType.PROCESS_WEEKLY_UPLOAD:
        return
    upload_id = (job.payload or {}).get('weekly_upload_id')
    if not upload_id:
        return
    WeeklyUpload.objects.filter(pk=upload_id).update(
        processed=False,
        processing_notes=f'Error: {exc}',
    )


def run_worker(*, once=False, sleep_seconds=2, worker_id=None, stdout=None):
    import time

    worker_id = worker_id or _job_worker_id()
    while True:
        job = claim_next_job(worker_id=worker_id)
        if job:
            if stdout:
                stdout.write(f'Running chart job {job.pk} ({job.job_type})')
            process_job(job)
            continue
        if once:
            return
        time.sleep(sleep_seconds)
