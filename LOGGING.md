# CyberWatch Logging Implementation Summary

## Overview
Comprehensive structured logging has been implemented across the entire CyberWatch codebase. All logs are output in **JSONL (JSON Lines)** format for easy parsing and analysis. Logging is **enabled by default** with INFO level.

## Key Features

### 1. Centralized Configuration
- **Module**: `cyberWatch/logging_config.py`
- **Formatter**: Custom `JSONLFormatter` that outputs single-line JSON objects
- **Rotation**: Automatic log rotation at 100MB (default) with 10 backup files
- **Components**: Separate loggers for `api`, `worker`, `collector`, `enrichment`, `scheduler`, `ui`, `db`

### 2. Structured Log Format
Each log entry includes:
```json
{
  "timestamp": "2025-12-25T10:30:45.123456Z",
  "level": "INFO|DEBUG|WARNING|ERROR|CRITICAL",
  "component": "api|worker|collector|enrichment|db",
  "logger": "cyberwatch.api",
  "message": "Human-readable message",
  "hostname": "server-name",
  "process_id": 12345,
  "thread_id": 67890,
  "module": "traceroute",
  "function": "run",
  "line": 123,
  // Context-specific fields...
  "request_id": "uuid",
  "duration": 1234.56,
  "outcome": "success|error",
  "target": "8.8.8.8",
  "status_code": 200
}
```

### 3. What's Logged

#### API Component (`cyberwatch.api`)
- **HTTP Middleware**: Every request/response with timing
  - Request ID generation and correlation
  - Method, path, query parameters
  - Status codes, response time in milliseconds
  - User agent and client IP
  
- **Route Handlers**:
  - `/traceroute/run`: User input (target), tool selection, subprocess execution, parsing results, database saves
  - `/targets/enqueue`: Queue operations with target details
  - `/dns/top-domains`: Query execution and result counts
  - `/measurements/latest`: Database queries and outcomes
  - All other endpoints with input validation and processing states

#### Worker Component (`cyberwatch.worker`)
- **Task Processing**:
  - Task dequeue events with task IDs
  - Target details from queue
  - Worker state (starting, ready, shutdown, stopped)
  
- **Subprocess Execution**:
  - Full command strings (e.g., `traceroute -n 8.8.8.8`)
  - Exit codes and execution duration
  - stdout/stderr output length
  - Parse results (hop count, lines matched)
  
- **Measurement Storage**:
  - Database insert success/failure
  - Row counts affected

#### Database Component (`cyberwatch.db`)
- **Connection Management**:
  - Pool creation with sanitized DSN (passwords redacted)
  - Connection acquisition timing
  
- **Query Execution**:
  - Measurement inserts with hop counts and timing
  - Bulk operations (DNS queries, targets) with batch sizes
  - Enrichment updates with ASN details
  - Transaction outcomes and rollback reasons (when errors occur)
  
- **Performance Metrics**:
  - Query execution time in milliseconds
  - Rows fetched/affected
  - Slow query detection

#### Collector Component (`cyberwatch.collector`)
- **Collection Cycles**:
  - Raw query count from DNS source
  - Filtered query count and filter reasons
  - DNS resolution results
  - Target enqueue operations
  
- **Filtering**:
  - Domains ignored due to length/suffix/qtype
  - Resolution failures and successes
  
- **State Transitions**:
  - Starting, ready, shutdown, stopped states

#### Enrichment Component (`cyberwatch.enrichment`)
- **ASN Lookups**:
  - IP addresses being enriched
  - ASN/org/country results
  - PeeringDB API calls
  
- **Batch Processing**:
  - Batch size and progress
  - Success/error counts
  - Measurement enrichment completion
  
- **Graph Building**:
  - Measurements processed
  - Edge creation in Neo4j
  - AS node merging operations

### 4. Environment Variables

```bash
# Log level (default: INFO)
export CYBERWATCH_LOG_LEVEL=DEBUG

# Log file path (default: logs/cyberwatch.jsonl)
export CYBERWATCH_LOG_FILE=/var/log/cyberwatch/api.jsonl

# Max bytes before rotation (default: 100MB)
export CYBERWATCH_LOG_MAX_BYTES=52428800
```

### 5. Security Features

**Automatic Redaction**:
- Passwords, tokens, API keys, secrets automatically replaced with `***REDACTED***`
- Database DSNs sanitized (only host portion shown)
- Sensitive fields configurable via `sanitize_log_data()` function

**Sanitized Fields** (case-insensitive):
- `password`, `passwd`, `pwd`
- `token`, `api_key`, `apikey`
- `secret`, `auth`, `authorization`
- `neo4j_password`

### 6. Console Output

In addition to JSONL file logging, human-readable console output is enabled by default:
```
2025-12-25 10:30:45 | INFO     | cyberwatch.api | Request completed
```

This can be disabled by setting the environment or modifying `enable_console=False` in logging setup.

### 7. Usage Examples

#### Finding Errors
```bash
# All errors
grep '"level":"ERROR"' logs/cyberwatch.jsonl | jq '.'

# Errors by component
grep '"component":"worker"' logs/cyberwatch.jsonl | grep ERROR | jq '.'

# Specific error types
grep '"error_type":"HTTPException"' logs/cyberwatch.jsonl | jq '.'
```

#### Request Tracing
```bash
# Find all logs for a specific request
REQUEST_ID="abc-123-def-456"
grep "\"request_id\":\"$REQUEST_ID\"" logs/cyberwatch.jsonl | jq '.'

# Find slow requests (over 1000ms)
jq 'select(.duration > 1000)' logs/cyberwatch.jsonl

# Most common endpoints
jq -r '.path' logs/cyberwatch.jsonl | sort | uniq -c | sort -rn
```

#### Performance Analysis
```bash
# Average response time by endpoint
jq -r '"\(.path) \(.duration)"' logs/cyberwatch.jsonl | \
  awk '{sum[$1]+=$2; count[$1]++} END {for(p in sum) print p, sum[p]/count[p]}'

# Database query timing
grep '"action":"measurement_insert"' logs/cyberwatch.jsonl | \
  jq '.duration' | \
  awk '{sum+=$1; count++} END {print "Avg:", sum/count, "ms"}'
```

#### Troubleshooting
```bash
# Failed traceroutes
grep '"outcome":"error"' logs/cyberwatch.jsonl | \
  grep traceroute | \
  jq '{timestamp, target, error_type, message}'

# DNS collection issues
grep '"component":"collector"' logs/cyberwatch.jsonl | \
  grep ERROR | \
  jq '{timestamp, message, exception}'

# Worker subprocess failures
grep '"exit_code"' logs/cyberwatch.jsonl | \
  jq 'select(.exit_code != 0)'
```

## Integration with Log Analysis Tools

### ELK Stack (Elasticsearch, Logstash, Kibana)
```conf
# Logstash config
input {
  file {
    path => "/var/log/cyberwatch/*.jsonl"
    codec => "json"
  }
}
filter {
  date {
    match => [ "timestamp", "ISO8601" ]
  }
}
output {
  elasticsearch {
    hosts => ["localhost:9200"]
    index => "cyberwatch-%{+YYYY.MM.dd}"
  }
}
```

### Grafana Loki
```yaml
# Promtail config
- job_name: cyberwatch
  static_configs:
  - targets:
      - localhost
    labels:
      job: cyberwatch
      __path__: /var/log/cyberwatch/*.jsonl
  pipeline_stages:
  - json:
      expressions:
        level: level
        component: component
        message: message
```

### Cloud Logging (AWS CloudWatch, GCP Cloud Logging)
Use the structured JSON format for automatic field extraction and filtering in cloud consoles.

## File Organization

```
cyberWatch/
├── logging_config.py          # Centralized logging setup
├── api/
│   ├── server.py              # Request middleware + logging
│   └── routes/
│       ├── traceroute.py      # Route-specific logging
│       ├── targets.py
│       ├── dns.py
│       ├── measurements.py
│       ├── asn.py
│       ├── graph.py
│       └── health.py
├── workers/
│   └── worker.py              # Task + subprocess logging
├── db/
│   ├── pg.py                  # PostgreSQL operation logging
│   ├── pg_dns.py              # DNS table operation logging
│   └── neo4j.py               # Neo4j connection logging
├── collector/
│   └── dns_collector.py       # DNS collection cycle logging
└── enrichment/
    ├── enricher.py            # ASN enrichment logging
    ├── graph_builder.py       # Graph building logging
    └── run_enrichment.py      # Scheduler logging

logs/
└── cyberwatch.jsonl           # Default log output
    cyberwatch.jsonl.1         # Rotated backup
    cyberwatch.jsonl.2
    ...
```

## Log Retention

By default:
- **Active log**: `logs/cyberwatch.jsonl` (grows to 100MB)
- **Rotated logs**: `logs/cyberwatch.jsonl.{1-10}` (10 backups = ~1GB total)
- **Automatic cleanup**: Oldest log deleted when limit exceeded

To customize retention:
```python
from cyberWatch.logging_config import setup_logging

logger = setup_logging(
    component="api",
    max_bytes=200 * 1024 * 1024,  # 200MB
    backup_count=20                # 20 backups
)
```

## Best Practices

1. **Use context-specific extra fields** when logging:
   ```python
   logger.info(
       "Processing user request",
       extra={
           "request_id": request_id,
           "user_input": {"target": target},
           "action": "process_start"
       }
   )
   ```

2. **Log at appropriate levels**:
   - `DEBUG`: Verbose details for development
   - `INFO`: Normal operations (default)
   - `WARNING`: Unexpected but handled situations
   - `ERROR`: Failures requiring attention
   - `CRITICAL`: System-level failures

3. **Include outcomes**: Use `"outcome": "success|error|failed"` for filtering

4. **Correlate with IDs**: Use `request_id`, `task_id`, `measurement_id` for tracing

5. **Monitor performance**: Include `duration` in milliseconds for timing analysis

## Troubleshooting

### Log file not created
- Check directory permissions: `mkdir -p logs && chmod 755 logs`
- Verify path in environment: `echo $CYBERWATCH_LOG_FILE`
- Check for startup errors in console output

### Logs not rotating
- Verify `CYBERWATCH_LOG_MAX_BYTES` is set correctly
- Check disk space: `df -h`
- Ensure write permissions on log directory

### Missing log entries
- Check log level: Set `CYBERWATCH_LOG_LEVEL=DEBUG` for verbose output
- Verify component name matches logger configuration
- Check for exceptions during logger initialization

## Next Steps

Consider:
1. **Centralized log aggregation**: Ship logs to ELK/Loki/Splunk
2. **Alerting**: Set up alerts for ERROR-level logs
3. **Dashboards**: Create Grafana dashboards from log metrics
4. **Archival**: Implement long-term log storage/compression
5. **Analysis**: Regular log analysis for performance optimization

---

**Logging is now fully operational across all CyberWatch components!**
