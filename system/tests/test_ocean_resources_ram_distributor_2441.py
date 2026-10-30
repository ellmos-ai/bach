from hub._services.ocean_resources_adapter import OceanRamDistributor

def test_ram_distributor_reserve_admission_fallback_and_release():
    dist = OceanRamDistributor(total_ram_gb=64.0, protected_reserve_gb=14.0)
    assert dist.allocatable_ram_gb == 50.0

    g1 = dist.request_admission(consumer_id="buddha-27b", model="qwen3.8:27b-mlx", requested_ram_gb=32.0, priority="fackel_holder")
    assert g1["admitted"] is True
    assert dist.allocatable_ram_gb == 18.0

    g2 = dist.request_admission(consumer_id="telegram-chat", model="qwen3:32b", requested_ram_gb=24.0, priority="interactive")
    assert g2["admitted"] is False
    assert "RAM-Reserve geschützt" in g2["fallback_notice"]

    rel = dist.release_grant("buddha-27b", expected_fence=g1["fence"])
    assert rel["released"] is True
    assert dist.allocatable_ram_gb == 50.0
