# Architecture

## 1. System Overview

This project is an **autonomous internet measurement and topology mapping system**.

The name of the software project is **cyberWatch**

Core capabilities:

* Actively probe the internet (traceroute, MTR, latency / packet loss).
* Consume routing and ASN/IXP metadata.
* Build a historical view of paths and topology from the vantage point of this node.
* Optionally bias measurements using anonymized DNS metadata from a local resolver (e.g. Pi-hole) so results are relevant to actual usage.
* Provide web interfaces for querying routes, visualizing topology, and inspecting time-series metrics.

The **core runtime** is a **Debian-based VM**, running Python services and associated databases. The design is hardware-agnostic beyond “Linux + Python + network access”.

---

## 2. High-Level Goals

1. **Measurement**

   * Continuously run traceroutes / ping / MTR to selected targets.
   * Dynamically select targets from multiple sources: static lists, ASN sets, and anonymized DNS feed.

2. **Topology & Context**

   * Resolve IPs → prefixes → ASNs → IXPs.
   * Construct an AS-level graph from observed paths and BGP/metadata feeds.

3. **History & Analytics**

   * Store raw measurements and summarized statistics.
   * Query historical changes in paths, latency, and reachability.
   * Visualize key metrics via dashboards.

4. **Looking Glass Functionality**

   * On-demand probes from the web UI (traceroute/MTR).
   * Path and ASN visualization for specific targets.

5. **Privacy & Security (Phase 2)**

   * Ensure DNS-derived targets are anonymized before storage.
   * Encrypt in-flight and at-rest where appropriate.
   * Isolate the system in the network.

---

## 3. Logical Architecture

Top-level components:

1. **DNS Target Collector (optional)**
2. **Target Queue / Scheduler**
3. **Measurement Worker Pool**
4. **Enrichment & Topology Builder (Multi-source)**
5. **ASN Discovery & Expansion**
6. **Remeasurement Scheduler**
7. **Data Stores (PostgreSQL + Neo4j)**
8. **APIs & Web UI**
9. **Monitoring & Security**

Conceptual diagram:

```text
          +----------------------+
          |  DNS / Resolver      |
          | (e.g. Pi-hole, etc.) |
          +----------+-----------+
                     |
                     v
          +----------+-----------+
          |  DNS Target Collector|
          |  (Anonymize & Filter)|
          +----------+-----------+
                     |
                     v
          +----------+-----------+
          |  Target Queue        |
          |  (Redis)             |
          +----------+-----------+
                     |
         +-----------+-----------+
         |                       |
         v                       v
+--------+---------+   +---------+--------+
| Measurement      |   | Enrichment /     |
| Worker Pool      |   | Topology Builder |
| (2-4 workers)    |   | (Multi-source)   |
| Rate-limited     |   |                  |
+--------+---------+   +---------+--------+
         |                       |
         v                       v
   +-----+-------+         +-----+------+
   |  PostgreSQL |         |   Neo4j    |
   | (metrics +  |<------->|(AS graph)  |
   |  ASN table) |         |            |
   +-----+-------+         +-----+------+
         |                       |
         v                       v
   +-----+-------+         +-----+------+
   | Grafana     |         |  Web UI /  |
   | Dashboards  |         | Looking-   |
   +-------------+         |   Glass    |
                           +------------+
         ^                       ^
         |                       |
         +----------+------------+
                    |
          +---------+-----------+
          | Remeasurement       |
          | Scheduler           |
          | (periodic refresh)  |
          +---------------------+
```

---

## 4. Deployment Model

### 4.1 Single Debian VM

The core system runs on a **single Debian VM**, which hosts:

* Python services (collector, workers, enrichment, remeasurement scheduler).
* Redis (queue).
* PostgreSQL (measurement DB + ASN metadata table).
* Neo4j (graph DB).
* Web UI + API (Python web framework).
* Grafana (dashboards).

This VM can be created on Proxmox or any other hypervisor. Vertical scaling is achieved by giving more CPU/RAM to the VM.

**Worker Scaling:** The measurement worker pool is horizontally scalable using systemd template units (`cyberWatch-worker@.service`). Start with 2 workers, scale to 4+ as needed by enabling additional instances (`cyberWatch-worker@3.service`, etc.).

---

## 5. Components

### 5.1 DNS Target Collector (Optional but Intended)

**Purpose:** transform raw DNS query logs from a resolver into sanitized measurement targets.

Responsibilities:

* Read DNS query events via:

  * HTTP/API (e.g. Pi-hole API).
  * Log tailing (FTL logs, syslog).
  * Or custom source.
* Extract domain names and timestamps.
* Apply privacy controls:

  * Strip client IPs / identifiers.
  * Apply domain whitelists/blacklists.
  * Hash domains (optionally non-reversible).
* Resolve domains → IPs → candidate targets.
* Emit measurement tasks to the **Target Queue**.

Implementation:

* Python service (async), running on the same VM or a nearby node.
* Communication to the queue via Redis, HTTP, or message broker.

### 5.2 Target Queue / Scheduler

**Purpose:** central buffer of measurement tasks.

Responsibilities:

* Hold measurement tasks: `{target_ip, target_type, priority, source, created_at}`.
* Handle rate limiting and scheduling:

  * Basic backoff per target / ASN.
  * Avoid over-probing.
* Support multiple producers:

  * DNS Collector.
  * Static lists (config).
  * Manual submissions via API/UI.

Implementation:

* Preferred: **Redis** (simple and robust for queues).
* Python layer for scheduling policies (workers pull tasks via Redis lists/streams).

### 5.3 Measurement Worker Pool

**Purpose:** perform actual network measurements with rate limiting and concurrency control.

Responsibilities:

* Pull tasks from the Target Queue (Redis `cyberwatch:targets` list).
* Run measurement tools:

  * `scamper` for traceroute / ping.
  * `mtr` for more detailed path statistics (as needed).
  * `ping` / `nping` for simple latency checks.
* Parse outputs and normalize them into structured data:

  * Hop list with IPs, RTTs, loss.
  * Overall path characteristics (hop count, min/avg/max RTT).
* Push normalized results to:

  * PostgreSQL (raw + summarized).
  * An internal channel for enrichment.
* **Rate limiting:** Token bucket algorithm prevents network abuse (default: 30 traceroutes/min per worker).
* **Concurrency control:** Max concurrent traceroutes per worker (default: 5) prevents resource exhaustion.

Implementation:

* Python async workers using `asyncio`.
* Scalable via systemd template units (`cyberWatch-worker@1.service`, `cyberWatch-worker@2.service`, etc.).
* **Settings loaded from PostgreSQL** (`worker_settings` key):
  * `rate_limit_per_minute`: Max traceroutes per minute per worker
  * `max_concurrent_traceroutes`: Max parallel traceroutes per worker
  * `worker_count`: Number of worker instances
* Token bucket with 60-second rolling window for rate limiting.
* Semaphore for concurrency control.

**Scaling Example:**
```bash
# Start 4 workers instead of 2
sudo systemctl start cyberWatch-worker@3.service cyberWatch-worker@4.service
sudo systemctl enable cyberWatch-worker@3.service cyberWatch-worker@4.service
```

### 5.4 Enrichment & Topology Builder

**Purpose:** transform raw measurement results into topology and context.

Responsibilities:

* IP → ASN / prefix mapping:

  * Use local databases (e.g. downloaded RIR/MaxMind-style datasets) or online sources (Team Cymru DNS interface).
* ASN → organization / IXP lookup:

  * Use PeeringDB or similar APIs.
* Build/maintain AS-level graph:

  * Nodes: ASNs, IXPs, prefixes (optional).
  * Edges: observed adjacency from traceroutes (AS hop transitions).
  * Track edge weights (count of observations, latency stats).
* Historical updates:

  * Upsert graph nodes/edges.
  * Annotate with time ranges and counts.

Implementation:

* Python service that subscribes to “new measurement” events or periodically scans PostgreSQL for unenriched records.
* Writes enriched path + AS graph updates to:

  * PostgreSQL (denormalized views).
  * Neo4j (graph structure).

### 5.5 Data Stores

#### 5.7.1 PostgreSQL

Used for:

* Raw probe results (per measurement, per hop).
* **ASN metadata table** (`asns`):

  * Comprehensive ASN information from all enrichment sources
  * Fields: asn, org_name, country_code, prefix_count, neighbor_count
  * PeeringDB data: peeringdb_id, facility_count, peering_policy, traffic_levels, irr_as_set
  * Statistics: total_measurements, avg_rtt_ms
  * Timestamps: first_seen, last_seen, last_enriched, last_enrichment_attempt
  * Indexes on asn, org_name, country_code, neighbor_count, last_enriched
* Derived metrics:

  * Per target: latency distribution, hop count, success/failure rates.
  * Per ASN: aggregate performance numbers (stored in `asns` table).
* Metadata:

  * Task definitions.
  * Target sets with measurement timestamps.
  * Configuration snapshots.
* **Settings table** for runtime configuration:

  * worker_settings: rate limits, concurrency, worker count
  * enrichment_settings: ASN expansion parameters
  * remeasurement_settings: remeasurement intervals and batch sizes

Schema (high-level):

* `targets` – known targets (IP, ASN, labels, first/last seen, last_measurement_at).
* `measurements` – one row per measurement run with enrichment/graph status.
* `hops` – hop-level data for each measurement with ASN/org/country from enrichment.
* `asns` – **dedicated ASN metadata table** with comprehensive enrichment data.
* `asn_stats` – aggregated metrics per ASN per time window.
* `settings` – runtime configuration (JSONB key-value store).

#### 5.7.2 Neo4j

Used for:

* AS-level graph:

  * Nodes: `AS {asn, org_name, country, ...}`.
  * Optional nodes: `Prefix`, `IXP`.
  * Edges: `ROUTE {observed_count, min_rtt, max_rtt, last_seen, ...}`.
* Queries:

  * Path between AS A and B.
  * Neighbors of AS.
  * Changes in adjacency over time.

### 5.8 APIs & Web UI

#### 5.8.1 Backend API

Responsibilities:

* Provide REST/JSON endpoints for:

  * Submitting ad-hoc targets for measurement.
  * Fetching traceroute/MTR results (latest or historical).
  * Exposing aggregate metrics.
  * Querying parts of the AS graph (e.g. shortest path, neighbors).

Implementation:

* Python web framework (FastAPI or similar).
* Direct DB access (PostgreSQL, Neo4j).

#### 5.8.2 Looking Glass Web UI

Responsibilities:

* Front-end for:

  * Running “live” traceroute/MTR to a target.
  * Displaying recent path + hop metrics.
  * Showing ASN path and basic org info.
* Integrate with topology and time-series views:

  * Link from traceroute result to “AS graph view” and Grafana dashboards.

Implementation:

* Simple SPA or server-rendered pages.
* Talks to backend API.

#### 5.8.3 Grafana Dashboards

Responsibilities:

* Time-series visualization using PostgreSQL as data source.
* Example dashboards:

  * Latency to major ASNs / prefixes.
  * Hop count distribution.
  * Measurement success/failure rates.
  * Derived “internet weather” indicators based on chosen targets.

---

## 6. Monitoring & Security

### 6.1 Monitoring

* System metrics:

  * Use Prometheus/node_exporter or similar on the VM (optional).
  * Resource usage of workers and databases.
* Application logs:

  * Structured logging for all Python services.
  * Log level control (info/debug).

### 6.2 Security (Design Requirements)

Even if implemented in later phases:

* DNS-derived data:

  * No client-identifying fields stored.
  * Domain hashing/aggregation before persistence.
* Transport:

  * Encrypted channels for DNS feed ingestion (HTTPS, WireGuard, etc.).
* Isolation:

  * VM placed in a dedicated VLAN or network segment.
  * Firewall rules restricting inbound/outbound ports.
* Access:

  * Authenticated access to Grafana and Web UI.
  * DB access restricted to the VM and admin endpoints only.

---

## 7. Implementation Phases

**Phase 0 – Skeleton** ✅ Completed

* Debian VM baseline.
* PostgreSQL + Redis installed.
* Minimal Python worker that:

  * Pulls targets from a static list.
  * Runs traceroute.
  * Stores results in PostgreSQL.

**Phase 1 – Queue & Workers** ✅ Completed

* Introduce Target Queue with Redis.
* Build stable worker process with basic scheduling.
* **Worker pool** with rate limiting and concurrency control.
* Systemd template units for horizontal scaling.

**Phase 2 – Enrichment** ✅ Completed

* IP → ASN mapping via **multi-source enrichment** (Team Cymru, PeeringDB, RIPE RIS, ip-api, ipinfo).
* **Dedicated ASN metadata table** with comprehensive fields.
* Store ASN info and basic aggregations.
* **ASN discovery and expansion** via prefix sampling.
* **Remeasurement scheduler** for keeping data fresh.

**Phase 3 – Graph & UI** ✅ Completed

* Neo4j graph builder.
* Basic API + web UI + Grafana.
* **Enhanced ASN API** with full enrichment data.

**Phase 4 – DNS Integration & Privacy** 🔄 In Progress

* DNS Target Collector.
* Anonymization, hashing, and policy controls.

**Phase 5 – Hardening** ⏳ Planned

* Network isolation, TLS, authentication, and logging policies.

---

This file defines the **logical design and intended behavior**. Implementation details (exact schemas, API endpoints, and service layouts) will live in separate documents (`schema.md`, `api.md`, deployment notes, etc.) as the codebase matures.
