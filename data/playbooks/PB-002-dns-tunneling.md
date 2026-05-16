# PB-002 — Data exfiltration via DNS tunneling

## Detection

Suspicious DNS queries with high entropy subdomains or unusually long TXT
records. Indicators:

- Queries to recently registered domains.
- Base64-like patterns in the subdomain label.
- High volume of TXT / NULL records to the same authoritative server.

## Action

- Sinkhole the domain at the resolver.
- Isolate the originating host from the network.
- Collect process tree and outbound connection log from the host.
