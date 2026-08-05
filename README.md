# Woow_ha_immich — WoowTech Immich Home Assistant Add-on Repository

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FWOOWTECH%2FWoow_ha_immich)

Home Assistant add-on repository for [Immich](https://immich.app) — a
high-performance self-hosted photo and video management platform
(HTTP/LAN variant — use a Cloudflare Tunnel for HTTPS).

Immich 高效能自架照片與影片管理平台的 Home Assistant add-on 倉庫
(HTTP 區網版本,對外請以 Cloudflare Tunnel 建立 HTTPS)。

## Add-ons in this repository | 本倉庫的 add-on

| Add-on | Description |
|---|---|
| [Woow Immich](woow-immich/) | Immich photo/video server + bundled PostgreSQL (pgvecto.rs) & Redis (amd64/aarch64) |

## Installation | 安裝

1. Click the badge above (or **Settings → Add-ons → Add-on Store → ⋮ →
   Repositories**) and add:
   `https://github.com/WOOWTECH/Woow_ha_immich`
2. Find **Woow Immich** in the store and click **INSTALL**.
3. Details, options and troubleshooting: [woow-immich/README.md](woow-immich/README.md)

> **Migrated from `Woow_immich_docker_compose_all` (branch `ha`)** — if you
> added the old repository URL, remove it and add this one to keep receiving
> updates.
> 若你先前加入的是舊倉庫網址,請移除並改加本倉庫,才能繼續收到更新。

## Other deployment platforms | 其他部署平台

- Docker/Podman Compose → [Woow_podman_immich](https://github.com/WOOWTECH/Woow_podman_immich)
- K3s/Kubernetes Helm chart → [Woow_k3s_immich](https://github.com/WOOWTECH/Woow_k3s_immich)
