"""
Storefront Provisioning Service.

Handles dynamic provisioning of new Medusa storefronts including
Docker container lifecycle management and storefront registration.
"""

import asyncio
import logging
import os
import socket
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shopforge.medusa import MedusaStorefront, NicheStorefront

logger = logging.getLogger(__name__)

_PORT_RANGE_START = 9100
_PORT_RANGE_END = 9200
_MEDUSA_IMAGE = "medusajs/medusa:latest"


def _is_port_available(port: int) -> bool:
    """Check if a TCP port is available on localhost."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def _find_next_port(allocated_ports: set) -> Optional[int]:
    """Find the next available port in the provisioning range."""
    for port in range(_PORT_RANGE_START, _PORT_RANGE_END):
        if port not in allocated_ports and _is_port_available(port):
            return port
    return None


class StorefrontProvisioner:
    """Provisions new Medusa storefronts with optional Docker deployment."""

    def __init__(self, medusa_storefront: Optional[MedusaStorefront] = None):
        self._medusa = medusa_storefront or MedusaStorefront()
        self._docker_client = None
        self._docker_available = False
        self._allocated_ports: set = set()
        self._try_connect_docker()

    def _try_connect_docker(self) -> None:
        """Attempt to connect to Docker daemon."""
        try:
            import docker
            self._docker_client = docker.from_env()
            self._docker_client.ping()
            self._docker_available = True
        except Exception as e:
            self._docker_available = False
            self._docker_client = None

    def _validate_config(self, config: dict) -> Optional[str]:
        """Validate provisioning config."""
        if not config.get("name", "").strip():
            return "name is required"
        if not config.get("segments"):
            return "segments is required (list of market segments)"
        return None

    def _generate_store_config(self, config: dict, port: Optional[int] = None) -> Dict[str, Any]:
        """Generate Medusa-compatible store configuration."""
        key = MedusaStorefront._slugify(config["name"])
        base_url = f"http://localhost:{port}" if port else f"https://{key}.gozerai.com"
        return {
            "key": key,
            "name": config["name"],
            "store_url": base_url,
            "admin_url": f"{base_url}/admin",
            "port": port,
        }

    async def provision(self, config):
        """Provision a new storefront."""
        error = self._validate_config(config)
        if error:
            return {"error": error, "status": "failed"}

        deploy = config.get("deploy_container", True)
        port = None
        container_id = None
        container_status = "not_deployed"

        if deploy and self._docker_available:
            port = _find_next_port(self._allocated_ports)
            if port is None:
                return {"error": "No available ports", "status": "failed"}

        store_config = self._generate_store_config(config, port)

        if deploy and self._docker_available and port is not None:
            try:
                container_id, container_status = await self._deploy_container(store_config, port)
                self._allocated_ports.add(port)
            except Exception:
                container_status = "deploy_failed"
        elif deploy and not self._docker_available:
            container_status = "docker_unavailable"

        try:
            sf = self._medusa.register_dynamic_storefront({
                "name": config["name"],
                "description": config.get("description", ""),
                "url": store_config["store_url"],
                "segments": config["segments"],
                "product_types": config.get("product_types", []),
                "tags": config.get("tags", []),
                "theme": config.get("theme", "default"),
                "target_audience": config.get("target_audience", ""),
                "markup_percentage": config.get("markup_percentage", 0.0),
            })
        except ValueError as e:
            return {"error": str(e), "status": "failed"}

        return {
            "status": "provisioned",
            "storefront_key": sf.key,
            "storefront_name": sf.name,
            "store_url": store_config["store_url"],
            "admin_url": store_config["admin_url"],
            "port": port,
            "container_id": container_id,
            "container_status": container_status,
            "deploy_mode": "container" if container_id else "config_only",
            "provisioned_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _deploy_container(self, store_config, port):
        if not self._docker_client:
            return None, "docker_unavailable"
        key = store_config["key"]
        container_name = f"shopforge-medusa-{key}"
        try:
            try:
                self._docker_client.images.get(_MEDUSA_IMAGE)
            except Exception:
                self._docker_client.images.pull(_MEDUSA_IMAGE)
            container = self._docker_client.containers.run(
                _MEDUSA_IMAGE, name=container_name, detach=True,
                ports={"9000/tcp": port},
                environment={"STORE_NAME": store_config["name"]},
                labels={"shopforge.storefront": key, "shopforge.managed": "true"},
            )
            healthy = await self._wait_for_health(port, timeout=30)
            return container.id, "running" if healthy else "started_unhealthy"
        except Exception as e:
            return None, f"deploy_error: {str(e)[:200]}"

    async def _wait_for_health(self, port, timeout=30):
        import urllib.request
        url = f"http://localhost:{port}/health"
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                pass
            await asyncio.sleep(1)
        return False

    @property
    def docker_available(self):
        return self._docker_available

    def get_status(self):
        return {
            "docker_available": self._docker_available,
            "allocated_ports": sorted(self._allocated_ports),
            "port_range": f"{_PORT_RANGE_START}-{_PORT_RANGE_END}",
            "dynamic_storefronts": len(self._medusa.list_dynamic_storefronts()),
        }
