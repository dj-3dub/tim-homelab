# Homelab Stack: Caddy + Homepage + Pi-hole

[![GitHub repo](https://img.shields.io/badge/github-dj--3dub/tim--homelab-181717?logo=github)](https://github.com/dj-3dub/tim-homelab)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue?logo=docker)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-Automation-3776AB?logo=python)](https://www.python.org/)

A **self-hosted homelab stack** built with **Python automation** and **Docker Compose**.

This project combines:
- 🌐 **Caddy** → HTTPS reverse proxy with local CA for trusted TLS  
- 🏠 **Homepage** → customizable dashboard for service links and monitoring  
- 🛡️ **Pi-hole** → DNS sinkhole and ad-blocker  

It also includes **monitoring and self-healing** logic to keep services healthy and free of zombie processes.

---

## ✨ Features at a Glance

- Automatic HTTPS via local CA (trusted certs for `.pizza` domains)
- Reverse proxy for multiple internal services
- Central dashboard with health and quick links
- DNS-level ad-blocking with Pi-hole
- Built-in watchdog + zombie guard for container self-healing

---

## 🔧 Services

### 🌐 Caddy
- Reverse proxy with automatic HTTPS
- Handles TLS termination and certificate rotation
- Routes traffic to backend containers

### 🏠 Homepage
- Dashboard at **`homepage.pizza`**
- Aggregates links, service health, and monitoring
- Configurable via `config/` and `public/`

### 🛡️ Pi-hole
- Ad-blocker at **`pihole.pizza/admin`**
- Runs in Docker with persistent config
- Secured with HTTPS via Caddy

---

## 📈 Monitoring & Self-Healing

- **Watchdog container**  
  Executes staged health checks

- **zombie_guard.py**  
  Detects zombie processes inside containers and restarts affected services

- **smoke_test_zombies.py**  
  Verifies:
  - `init: true` is set so PID 1 reaps child processes
  - No long-lived zombies exist
  - Watchdog is functioning correctly

---

## Architecture

```mermaid
flowchart LR
    subgraph Client["Clients / Browsers"]
      U1["Laptop / Phone"]
    end

    U1 -->|HTTPS (LAN)| RP[Caddy Reverse Proxy]

    subgraph DockerNet["Docker Network (proxy)"]
      direction LR
      RP -->|HTTP :3000| HP[Homepage Container]
      RP -->|HTTP :80| PH[Pi-hole Container]
    end

    %% Monitoring & Self-Healing
    subgraph Ops["Monitoring & Self-Healing"]
      WD[Watchdog Container]
      ZG[zombie_guard.py]
      SMK[smoke_test_zombies.py]
    end

    WD -->|executes staged checks| ZG
    WD -->|periodic checks| SMK
    ZG -->|detects 'Z' zombies| ZOMBIE{{Defunct Child<br/>(e.g., wget &lt;defunct&gt;)}}
    ZOMBIE -. parent-> PARENT([Parent PID in Container])
    ZG -->|maps PPID → container| MAP{{docker inspect / cgroup}}
    ZG -->|auto-restart| HP
    ZG -->|auto-restart| PH

    %% Notes
    note right of HP
      PID 1 = docker-init (via `init: true`)
      Reaps orphaned children → prevents zombies
    end

    classDef svc fill:#eef,stroke:#88a,color:#000
    classDef ops fill:#efe,stroke:#8a8,color:#000
    class HP,PH,RP svc
    class WD,ZG,SMK ops

