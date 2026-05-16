-- ============================================
-- Playbooks: minimal remediation corpus
-- (embeddings left NULL for now; populated by the worker in Act 4)
-- ============================================
INSERT INTO playbook_chunks (playbook_id, chunk_index, title, content) VALUES
('PB-001', 0, 'Brute force login detection',
 'Multiple failed authentication attempts from a single source IP within a short window. Threshold: 10 failures in 5 minutes. Immediate action: block IP at edge firewall, force password reset for targeted accounts.'),
('PB-001', 1, 'Brute force escalation',
 'If failures continue from rotating IPs, escalate to credential stuffing playbook PB-007. Notify SOC lead. Capture full PCAP for forensics.'),

('PB-002', 0, 'Data exfiltration via DNS tunneling',
 'Suspicious DNS queries with high entropy subdomains or unusually long TXT records. Indicators: queries to recently registered domains, base64-like patterns in subdomain. Action: sinkhole the domain, isolate host.'),

('PB-003', 0, 'Suspicious PowerShell execution',
 'PowerShell invoked with encoded commands (-EncodedCommand flag), hidden window (-WindowStyle Hidden), or downloading remote content (Invoke-WebRequest, IEX). Action: kill process, capture memory dump, scan host for persistence.');

-- ============================================
-- Alerts: sample findings
-- (embeddings left NULL; populated by the worker in Act 4)
-- ============================================
INSERT INTO alerts (source_ip, severity, category, raw_text) VALUES
('203.0.113.42', 'high',     'authentication', 'SSH brute force: 47 failed logins for user "admin" in 4 minutes from 203.0.113.42'),
('198.51.100.7', 'critical', 'exfiltration',   'Unusual outbound: 2.3GB transferred to unknown-host.cloud-eu.net over 12 minutes'),
('10.4.2.18',    'high',     'execution',      'PowerShell launched with -EncodedCommand on workstation WS-FIN-042 by user jdoe'),
('10.4.2.18',    'medium',   'execution',      'PowerShell Invoke-WebRequest from same workstation 3 minutes later'),
('45.33.12.99',  'low',      'reconnaissance', 'Port scan detected: 1024 ports probed on edge-fw-01 in 30 seconds'),
('192.0.2.55',   'medium',   'authentication', 'Successful login for user "cfo" from new geolocation (Lagos, NG)');

-- ============================================
-- LTM: default analyst preferences
-- ============================================
INSERT INTO ltm (analyst_id, key, value, importance) VALUES
('cristian', 'severity_filter',  '["high","critical"]'::jsonb, 0.9),
('cristian', 'timezone',         '"America/Bogota"'::jsonb,    0.5),
('cristian', 'ignored_ips',      '["10.0.0.5"]'::jsonb,        0.7),
('cristian', 'preferred_format', '"timeline"'::jsonb,          0.4);

-- ============================================
-- Audit log: initialisation marker
-- ============================================
INSERT INTO audit_log (principal, operation, granted, metadata) VALUES
('system', 'database_init', true, '{"version":"act-1","seed_rows":13}'::jsonb);
