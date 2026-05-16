# PB-003 — Suspicious PowerShell execution

## Detection

PowerShell invoked with any of:

- `-EncodedCommand` flag.
- `-WindowStyle Hidden`.
- Downloading remote content (`Invoke-WebRequest`, `IEX`, `Net.WebClient`).
- Calls to LOLBins (`certutil`, `bitsadmin`) chained with `iex`.

## Action

- Kill the offending process.
- Capture a memory dump of the parent process.
- Scan the host for persistence: Run keys, scheduled tasks, WMI subscriptions.
- Open incident; correlate with EDR alerts in the last 24h for the same user.
