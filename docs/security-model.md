# Security model

## Secure defaults

- Remediation mode defaults to `OBSERVE`.
- Ollama is optional and addressed through loopback.
- No arbitrary shell command API exists.
- Subprocesses use fixed executable paths, fixed argument positions, and
  `shell=False`.
- Service restarts require an explicit authorized service set.
- Action timeouts and audit records are mandatory execution controls.
- Incident resolution requires successful recovery verification.
- Simulations default to dry-run and cannot run host service/network failures.

## Operational controls

Run the backend under a dedicated least-privilege account. Restrict its SQLite
directory and audit logs to the service account and operators. If systemd
integration is enabled, use a narrowly scoped sudoers policy for the exact
allowlisted operations; never grant a general shell or unrestricted
`systemctl` permission.

## Failure behavior

Unavailable Ollama falls back to deterministic diagnosis. Invalid model output
is rejected. A failed verification leaves the incident open or reopened.
Queue saturation is bounded rather than allowed to grow without limit.
