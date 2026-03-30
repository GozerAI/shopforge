"""Tests for Shopforge dynamic provisioning (Phase 2)."""

import asyncio
import json
import pathlib
import tempfile

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shopforge.medusa import MedusaStorefront, NicheStorefront, NICHE_STOREFRONTS
from shopforge.provisioning import (
    StorefrontProvisioner,
    _is_port_available,
    _find_next_port,
    _PORT_RANGE_START,
)


@pytest.fixture
def tmp_data_dir(tmp_path):
    return tmp_path


@pytest.fixture
def medusa_sf(tmp_data_dir):
    return MedusaStorefront(data_dir=tmp_data_dir)


@pytest.fixture
def provisioner(medusa_sf):
    return StorefrontProvisioner(medusa_storefront=medusa_sf)


class TestDynamicStorefrontRegistration:

    def test_register_dynamic_storefront_basic(self, medusa_sf):
        sf = medusa_sf.register_dynamic_storefront({"name": "Eco Living", "segments": ["eco"]})
        assert sf.key == "eco_living"
        assert sf.name == "Eco Living"
        assert sf.url == "eco_living.gozerai.com"

    def test_register_with_full_config(self, medusa_sf):
        config = {
            "name": "Gaming Gear",
            "description": "Gaming peripherals",
            "url": "gaming.gozerai.com",
            "segments": ["gaming", "electronics"],
            "product_types": ["Gaming"],
            "tags": ["gaming", "esports"],
            "theme": "dark",
            "target_audience": "Gamers",
            "markup_percentage": 15.0,
        }
        sf = medusa_sf.register_dynamic_storefront(config)
        assert sf.key == "gaming_gear"
        assert sf.markup_percentage == 15.0
        assert sf.url == "gaming.gozerai.com"

    def test_register_duplicate_raises(self, medusa_sf):
        medusa_sf.register_dynamic_storefront({"name": "My Shop", "segments": ["x"]})
        with pytest.raises(ValueError, match="already exists"):
            medusa_sf.register_dynamic_storefront({"name": "My Shop", "segments": ["y"]})

    def test_register_empty_name_raises(self, medusa_sf):
        with pytest.raises(ValueError, match="name is required"):
            medusa_sf.register_dynamic_storefront({"name": "", "segments": ["x"]})

    def test_register_hardcoded_collision_raises(self, medusa_sf):
        with pytest.raises(ValueError, match="already exists"):
            medusa_sf.register_dynamic_storefront({"name": "Pet Paradise", "segments": ["x"]})

    def test_slugify(self):
        assert MedusaStorefront._slugify("Hello World") == "hello_world"
        assert MedusaStorefront._slugify("  Eco & Green!  ") == "eco_green"
        assert MedusaStorefront._slugify("A") == "a"

    def test_persistence_roundtrip(self, tmp_data_dir):
        ms1 = MedusaStorefront(data_dir=tmp_data_dir)
        ms1.register_dynamic_storefront({"name": "Persist Test", "segments": ["test"]})
        assert (tmp_data_dir / "storefronts.json").exists()
        ms2 = MedusaStorefront(data_dir=tmp_data_dir)
        assert ms2.get_niche_storefront("persist_test") is not None
        assert ms2.get_niche_storefront("persist_test").name == "Persist Test"

    def test_list_all_storefronts(self, medusa_sf):
        initial = len(medusa_sf.list_all_storefronts())
        medusa_sf.register_dynamic_storefront({"name": "New One", "segments": ["a"]})
        assert len(medusa_sf.list_all_storefronts()) == initial + 1

    def test_list_dynamic_storefronts(self, medusa_sf):
        assert len(medusa_sf.list_dynamic_storefronts()) == 0
        medusa_sf.register_dynamic_storefront({"name": "Dyn1", "segments": ["a"]})
        medusa_sf.register_dynamic_storefront({"name": "Dyn2", "segments": ["b"]})
        assert len(medusa_sf.list_dynamic_storefronts()) == 2

    def test_stats_include_dynamic_counts(self, medusa_sf):
        medusa_sf.register_dynamic_storefront({"name": "Stats Test", "segments": ["x"]})
        stats = medusa_sf.get_stats()
        assert stats["dynamic_storefronts"] == 1
        assert stats["hardcoded_storefronts"] == 8
        assert stats["total_niche_storefronts"] == 9


class TestProvisioningService:

    @pytest.mark.asyncio
    async def test_provision_config_only(self, provisioner):
        result = await provisioner.provision({
            "name": "Eco Store",
            "segments": ["eco", "sustainable"],
            "deploy_container": False,
        })
        assert result["status"] == "provisioned"
        assert result["storefront_key"] == "eco_store"
        assert result["deploy_mode"] == "config_only"

    @pytest.mark.asyncio
    async def test_provision_missing_name(self, provisioner):
        result = await provisioner.provision({
            "name": "",
            "segments": ["test"],
        })
        assert result["status"] == "failed"
        assert "name is required" in result["error"]

    @pytest.mark.asyncio
    async def test_provision_missing_segments(self, provisioner):
        result = await provisioner.provision({"name": "Test Store"})
        assert result["status"] == "failed"
        assert "segments" in result["error"]

    @pytest.mark.asyncio
    async def test_provision_duplicate(self, provisioner):
        await provisioner.provision({
            "name": "Unique Store", "segments": ["test"], "deploy_container": False})
        result = await provisioner.provision({
            "name": "Unique Store", "segments": ["test"], "deploy_container": False})
        assert result["status"] == "failed"
        assert "already exists" in result["error"]

    @pytest.mark.asyncio
    async def test_provision_docker_unavailable(self, provisioner):
        # Force Docker to be unavailable regardless of host environment
        provisioner._docker_available = False
        provisioner._docker_client = None
        result = await provisioner.provision({
            "name": "Docker Test", "segments": ["test"], "deploy_container": True})
        assert result["status"] == "provisioned"
        assert result["container_status"] == "docker_unavailable"
        assert result["deploy_mode"] == "config_only"

    @pytest.mark.asyncio
    async def test_provision_with_mocked_docker(self, medusa_sf):
        prov = StorefrontProvisioner(medusa_storefront=medusa_sf)
        prov._docker_available = True
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.id = "abc123"
        mock_client.containers.run.return_value = mock_container
        mock_client.images.get.side_effect = Exception("not found")
        prov._docker_client = mock_client
        with patch.object(prov, "_wait_for_health", new_callable=AsyncMock, return_value=True):
            result = await prov.provision({
                "name": "Docker Deployed", "segments": ["test"], "deploy_container": True})
        assert result["status"] == "provisioned"
        assert result["container_id"] == "abc123"
        assert result["container_status"] == "running"
        assert result["deploy_mode"] == "container"

    def test_port_available(self):
        result = _is_port_available(9199)
        assert isinstance(result, bool)

    def test_find_next_port(self):
        port = _find_next_port(set())
        assert port is not None
        assert port >= _PORT_RANGE_START

    def test_find_next_port_skips_allocated(self):
        allocated = {_PORT_RANGE_START}
        port = _find_next_port(allocated)
        assert port != _PORT_RANGE_START

    def test_provisioner_status(self, provisioner):
        status = provisioner.get_status()
        assert "docker_available" in status
        assert "allocated_ports" in status
        assert "dynamic_storefronts" in status


class TestProvisioningEndpoints:

    @pytest.fixture
    async def client(self, tmp_path):
        from httpx import ASGITransport, AsyncClient
        import shopforge.app as app_module
        from shopforge.app import app, get_tenant
        from shopforge.service import CommerceService
        original_service = app_module._service
        original_prov = app_module._provisioner
        original_require = app_module.require_entitlement
        svc = CommerceService()
        app_module._service = svc
        ms = MedusaStorefront(data_dir=tmp_path)
        app_module._provisioner = StorefrontProvisioner(medusa_storefront=ms)
        svc._medusa_storefront = ms
        # Override auth
        mock_tenant_data = {"tenant_id": "t", "entitlements": ["shopforge:basic", "shopforge:full"]}
        async def mock_tenant():
            return mock_tenant_data
        app.dependency_overrides[get_tenant] = mock_tenant
        # For require_entitlement, we need to override each generated dependency
        # The simplest approach: override get_tenant which is called by require_entitlement
        # But require_entitlement creates its own dependency. Override directly:
        for route in app.routes:
            if hasattr(route, "dependant"):
                for dep in getattr(route.dependant, "dependencies", []):
                    if dep.call and hasattr(dep.call, "__name__") and dep.call.__name__ == "_check":
                        app.dependency_overrides[dep.call] = mock_tenant
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
        app_module._service = original_service
        app_module._provisioner = original_prov
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_provision_endpoint(self, client):
        resp = await client.post(
            "/v1/storefronts/provision/dynamic",
            json={"name": "API Test", "segments": ["test"], "deploy_container": False},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "provisioned"

    @pytest.mark.asyncio
    async def test_provision_validation(self, client):
        resp = await client.post(
            "/v1/storefronts/provision/dynamic",
            json={"name": "", "segments": ["x"]},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_dynamic(self, client):
        resp = await client.get("/v1/storefronts/dynamic")
        assert resp.status_code == 200
        assert "storefronts" in resp.json()

    @pytest.mark.asyncio
    async def test_provision_then_list(self, client):
        await client.post(
            "/v1/storefronts/provision/dynamic",
            json={"name": "Listed", "segments": ["t"], "deploy_container": False},
        )
        resp = await client.get("/v1/storefronts/dynamic")
        keys = [s["key"] for s in resp.json()["storefronts"]]
        assert "listed" in keys

    @pytest.mark.asyncio
    async def test_missing_required_field(self, client):
        resp = await client.post(
            "/v1/storefronts/provision/dynamic",
            json={"description": "no name"},
        )
        assert resp.status_code == 422


class TestStorefrontProvisioningWorkflow:

    def _load_wf_module(self):
        import importlib
        spec = importlib.util.spec_from_file_location(
            "provisioning_workflow",
            r"F:\Projects\c-suite\src\csuite\modules\commerce\provisioning_workflow.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @pytest.mark.asyncio
    async def test_provision_workflow(self):
        mod = self._load_wf_module()
        adapter = mod.ShopforgeToolAdapter()
        adapter.provision_storefront = AsyncMock(return_value={
            "status": "provisioned", "storefront_key": "eco_shop"})
        wf = mod.StorefrontProvisioningWorkflow(adapter=adapter)
        result = await wf.provision_storefront("Eco Shop", ["eco"])
        assert result["status"] == "provisioned"
        adapter.provision_storefront.assert_called_once()

    @pytest.mark.asyncio
    async def test_suggest_fitness(self):
        mod = self._load_wf_module()
        wf = mod.StorefrontProvisioningWorkflow()
        result = await wf.suggest_storefront("Growing demand for fitness")
        assert "fitness" in result["segments"]
        assert "suggested_name" in result

    @pytest.mark.asyncio
    async def test_suggest_unknown(self):
        mod = self._load_wf_module()
        wf = mod.StorefrontProvisioningWorkflow()
        result = await wf.suggest_storefront("Artisanal cheese")
        assert "general" in result["segments"]

    @pytest.mark.asyncio
    async def test_suggest_multi_segment(self):
        mod = self._load_wf_module()
        wf = mod.StorefrontProvisioningWorkflow()
        result = await wf.suggest_storefront("Luxury sustainable fashion")
        assert "luxury" in result["segments"]
        assert "sustainable" in result["segments"]
        assert result["confidence"] == "medium"

    @pytest.mark.asyncio
    async def test_workflow_failure(self):
        mod = self._load_wf_module()
        adapter = mod.ShopforgeToolAdapter()
        adapter.provision_storefront = AsyncMock(return_value={
            "status": "failed", "error": "name is required"})
        wf = mod.StorefrontProvisioningWorkflow(adapter=adapter)
        result = await wf.provision_storefront("", [])
        assert result["status"] == "failed"
