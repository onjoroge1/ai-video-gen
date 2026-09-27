"""Bounded continuation keeps the approved job and completed provider stages intact."""
from contextlib import contextmanager
from copy import deepcopy
import json

from durable_execution import PostgresStore


def store_for_selection(selected):
    class Cursor:
        def __init__(self):
            self.calls = []
            self.row = deepcopy(selected)

        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            if 'UPDATE generation_jobs' in sql:
                self.row.update(status='queued', error=None,
                                max_attempts=max(self.row['max_attempts'], self.row['attempts'] + 2),
                                lease_owner=None, lease_expires_at=None)

        def fetchone(self):
            return deepcopy(self.row)

    cursor = Cursor()
    store = object.__new__(PostgresStore)
    @contextmanager
    def transaction():
        yield None, cursor
    store._tx = transaction
    store.ensure_schema = lambda: None
    store._row = lambda _, row: row
    return store, cursor


def test_shot_timing_recovery_preserves_approval_checkpoint_cost_and_provider_stages():
    saved = dict(id='7983e778', status='error', attempts=8, max_attempts=9,
                 error='Nature shot gp1_61 measures 3.50s; repartition this beat into 0.75-3.4s shots before visuals',
                 request={'approved_sha256': 'immutable'}, checkpoint={'sha256': 'saved'},
                 spent_cost_usd=.12, reserved_cost_usd=0, max_cost_usd=5)
    store, cursor = store_for_selection(saved)
    recovered = store.rearm_next_nature_shot_timing_failure()
    assert recovered['status'] == 'queued' and recovered['error'] is None
    assert recovered['attempts'] == 8 and recovered['max_attempts'] == 10
    for key in ('request', 'checkpoint', 'spent_cost_usd', 'reserved_cost_usd', 'max_cost_usd'):
        assert recovered[key] == saved[key]
    selection = cursor.calls[0][0]
    for guard in ("j.status='error'", "j.error ~ '^Nature shot", 'j.lease_expires_at < now()',
                  'j.reserved_cost_usd=0', 'j.spent_cost_usd < j.max_cost_usd',
                  "j.checkpoint <> '{}'::jsonb", "a.status='queued'", 'a.approved_at IS NOT NULL',
                  "a.operation='directed_pilot'", "'nature_short_v2'", 'NOT EXISTS'):
        assert guard in selection
    event_sql, params = cursor.calls[-1]
    details = json.loads(params[-1])
    assert "'infrastructure_rearmed'" in event_sql
    assert details['recovery_key'] == 'nature_measured_holds_v1'
    assert details['recovery_key'] in selection
    assert details['prior_error'] == saved['error']
    assert all('generation_stages' not in sql for sql, _ in cursor.calls)


def test_no_eligible_timing_failure_does_not_mutate_jobs():
    store, cursor = store_for_selection(None)
    assert store.rearm_next_nature_shot_timing_failure() is None
    assert len(cursor.calls) == 1


def test_existing_cron_audio_recovery_picks_up_shot_migration_first():
    store = object.__new__(PostgresStore)
    job = {'id': '7983e778', 'status': 'queued'}
    store.rearm_next_nature_motion_disk_failure = lambda: None
    store.rearm_next_nature_shot_timing_failure = lambda: job
    assert store.rearm_next_directed_audio_runtime_failure() is job


def test_existing_cron_audio_recovery_picks_up_motion_disk_migration_first():
    store = object.__new__(PostgresStore)
    job = {'id': '7983e778', 'status': 'queued'}
    store.rearm_next_nature_motion_disk_failure = lambda: job
    assert store.rearm_next_directed_audio_runtime_failure() is job


def test_nature_motion_disk_recovery_preserves_open_stage_reservation():
    job = dict(id='7983e778', status='storage_error', attempts=9, max_attempts=10,
               error='[Errno 28] No space left on device', checkpoint={'sha256':'saved'},
               spent_cost_usd=2.59, reserved_cost_usd=.224, max_cost_usd=5,
               max_inflight_call_usd=1, lease_owner=None, lease_expires_at=None)
    stage = dict(stage_key='motion:abc123', status='retry', provider='fal',
                 reserved_cost_usd=.224)

    class Cursor:
        def __init__(self):
            self.calls = []
            self.one = None
            self.many = []
        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            self.one, self.many = None, []
            if 'SELECT j.* FROM generation_jobs' in sql:
                self.one = deepcopy(job)
            elif 'SELECT stage_key,status,provider' in sql:
                self.many = [deepcopy(stage)]
            elif 'UPDATE generation_jobs' in sql:
                job.update(status='queued', error=None, max_attempts=11)
                self.one = deepcopy(job)
        def fetchone(self): return self.one
        def fetchall(self): return self.many

    cursor = Cursor()
    store = object.__new__(PostgresStore)
    @contextmanager
    def transaction(): yield None, cursor
    store._tx = transaction
    store.ensure_schema = lambda: None
    store._row = lambda _, row: row
    recovered = store.rearm_next_nature_motion_disk_failure()
    assert recovered['status'] == 'queued'
    assert recovered['spent_cost_usd'] == 2.59
    assert recovered['reserved_cost_usd'] == .224
    assert recovered['checkpoint'] == {'sha256':'saved'}
    event_sql, params = cursor.calls[-1]
    details = json.loads(params[-1])
    assert "'infrastructure_rearmed'" in event_sql
    assert details['recovery_key'] == 'nature_motion_disk_v1'
    assert details['preserved_stage_key'] == 'motion:abc123'
    assert details['preserved_reserved_cost_usd'] == .224
