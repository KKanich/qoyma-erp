# Database backup and recovery

file-based SQLite `default` database configured in `qoyma/settings.py`.

## Design

`python manage.py backup_db` creates a full snapshot using Python's
[SQLite online backup API](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).
This supports a running application and includes committed WAL transactions;
copying only a live `db.sqlite3` file can miss those transactions.

The command opens the source read-only, copies to a temporary file, checks
`PRAGMA integrity_check` and `PRAGMA foreign_key_check`, rejects empty databases,
flushes the file, and publishes it with a unique UTC timestamp and random suffix.
It never overwrites an existing file. Failed attempts clean up temporary files
and return a nonzero exit status. The copy phase has a 60-second progress deadline;
verification time is additional. No new Python dependencies are required.

Publication uses a hard link in the destination directory for atomic creation
without overwrite. Use a local filesystem supporting hard links (e.g. NTFS or
ext4). For USB/cloud storage without that support, create locally first and copy
the completed `.sqlite3` file afterwards. Backups contain schema, application
data, users/password hashes, sessions and Django migration records. They do not
include source code, environment configuration or uploaded files.

## Create and check a backup

From the repository directory, with the project environment activated:

```bash
python manage.py backup_db
python manage.py backup_db --output-dir "backup/manual"
```

Success prints `Backup verified:` and the absolute path. Record the path and
result in the maintenance log. Do not commit databases to Git. Integrity checks
detect structural problems and broken references; they cannot prove that all
business data is correct or detect intentional tampering.

## Recovery drill (safe with the app running)

Choose a completed backup and a new target filename:

```bash
python manage.py restore_db "backup/qoyma-<timestamp>-<suffix>.sqlite3" --target "backup/recovery-drill.sqlite3"
```

The command verifies the restored snapshot and leaves the live database untouched.
It refuses existing targets and the configured live database path. If repeating
the drill, choose a different target filename. Open the restored file with a
SQLite viewer and compare products, stock, sale totals, and user counts with
the records expected at backup time. Check representative sale-to-item links.
Only restore trusted backups. Use the corresponding application revision and
migrations when testing an older snapshot.

## Actual recovery (planned downtime)

1. Stop the Django server and all processes that can access the live database,
   including scheduled backup jobs, shells and SQLite viewers.
2. Preserve the current database and any `db.sqlite3-wal`, `db.sqlite3-shm`, or
   `db.sqlite3-journal` sidecars together in a separate incident directory while
   all processes are stopped. Do not discard them: they may contain newer data.
3. Run `restore_db` to a new staging file and inspect it as in the drill above.
4. With all database users still stopped, move the original database and its
   sidecars out of the live directory into the incident directory. Move the
   verified staging file to the configured database path (`db.sqlite3` by default).
   Never combine an older snapshot with sidecars from the previous database.
5. Run `python manage.py migrate --check` with the matching application revision.
   If migrations are pending, review compatibility and back up before applying
   `python manage.py migrate`.
6. Restart the server. Verify login, stock quantities and recent sales against
   the backup-time records. Record recovery duration and any transactions lost
   since that backup. Retain the incident copy until recovery is accepted.

The restore command intentionally does not perform this live-file cutover.

## Proposed operating policy

For the academic deployment, take a full backup daily at 22:00 local time and
before schema migrations or bulk data changes. Keep 7 daily copies and 4 weekly
copies. The steward reviews success/failure after each scheduled run, retries
failures, and performs a recovery drill monthly and before the demonstration.
Retention is manual: delete only reviewed old copies after verifying that the
newest backup and independent copy are usable. The command never prunes files.

Windows Task Scheduler configuration (create on the deployment machine):

- Trigger: daily at 22:00 in the machine's local timezone.
- Program: full path to the project's `.venv\Scripts\python.exe`.
- Arguments: `manage.py backup_db`.
- Start in: full path to the repository directory (without quotes in this field).
- Account: a restricted operator with read access to the database and write
  access to the backup directory. Run missed tasks as soon as possible and
  prevent overlapping runs. Check Last Run Result and retain execution logs.

This repository does not install a scheduled task. Confirm the machine is on
and the task succeeds under its actual account before relying on the schedule.

Copy verified backups to an independent device or approved encrypted off-site
storage after every run; restrict access because they contain business data and
password hashes. The intended 3-2-1 policy is the live database plus two backup
copies, on two storage types, with one copy off-site. Same-disk snapshots alone
do not protect against disk failure or theft. Encryption, remote upload, alerts
and retention automation are future deployment work, not implemented features.

With successful daily backups, the target recovery point objective (RPO) is up
to 24 hours of lost work. This is a target, not a guarantee: failed backups make
the gap longer. Proposed recovery time objective (RTO) is 30 minutes for this
small project, to be validated with timed drills. Record actual drill results
before claiming the target is met.

## Verification

```bash
python manage.py test store -v 2
python manage.py test store.test_backup -v 2
```

The first command runs the full suite; the second runs the seven backup tests
in `store/test_backup.py`. They cover recovery after deletion, unique snapshots,
committed WAL data versus uncommitted writes, overwrite refusal, live-path
protection, missing/corrupt/empty inputs, foreign-key checks and timeout cleanup.
Destructive scenarios use temporary databases, leaving the live database alone.
The [QA guide](../qa/README.md) records the supplied test provenance and links to
the execution report. Automated recovery uses temporary databases; a timed
operational recovery drill remains a separate deployment responsibility.
