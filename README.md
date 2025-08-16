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
  U1[Client]
  RP[Caddy Reverse Proxy]
  HP[Homepage Container]
  PH[Pi-hole Container]
  WD[Watchdog Container]
  ZG[zombie_guard.py]
  SMK[smoke_test_zombies.py]

  U1 --> RP
  RP -->|http:3000| HP
  RP -->|http:80|   PH

  WD --> ZG
  WD --> SMK
  ZG -->|detect zombies| HP
  ZG -->|detect zombies| PH
  ZG -->|auto-restart| HP
  ZG -->|auto-restart| PH


