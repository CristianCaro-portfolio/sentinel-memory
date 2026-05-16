# PB-001 — Brute force login response

## Detection

Multiple failed authentication attempts from a single source IP within a short
window. Threshold: **10 failures in 5 minutes**.

## Immediate action

- Block IP at edge firewall.
- Force password reset for targeted accounts.
- Open incident in the SOC tracker.

## Escalation

If failures continue from rotating IPs, escalate to credential stuffing
playbook **PB-007**. Notify SOC lead. Capture full PCAP for forensics.
