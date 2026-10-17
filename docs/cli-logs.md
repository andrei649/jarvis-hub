# Read recent hub logs

`nerva logs` prints recent records from the configured hub log without needing a
running hub. A traceback counts as one record. Use `-n` to choose the record count:

```bash
nerva logs -n 50
nerva logs list
nerva logs jarvis.log.1 -n 20
```

`list` shows available filenames, sizes and modification times. Select the exact
name shown there: the configured log and its numbered rotations are supported.
If the active file is missing, the default reads the first available rotation.
An unknown name fails with available names; it does not read an arbitrary path.

Use `--name` when a filename conflicts with the `list` command, for example
`nerva logs --name list`. Do not combine it with a positional filename.
`JARVIS_LOG_FILE` selects the configured log; otherwise the CLI uses the normal
application data directory. When no log exists, the command explains how to
enable file logging with `nerva config set system.log_to_file on`.

Records pass through the same secret redactor as the hub log reader. If the
redactor is unavailable, nothing from the log is printed. Reads use a bounded
tail window; large requests can return fewer records with a notice on stderr.
The CLI preserves its existing support for requests above 500 records; the web
log API has a separate 500-record limit. No follow mode is provided here.
