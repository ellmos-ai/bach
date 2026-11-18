# SPDX-License-Identifier: MIT
"""Unchanged independent late-revocation repro; all provider reads are fixtures."""
import asyncio
from types import SimpleNamespace

import pytest
from hub._services import ocean_resources_provider
from hub._services.chat import local_resource_reserve, resource_load_pending
from hub._services.chat.host_inference_gate import HostInferenceGate
from hub._services.chat.resource_model_port import (
    GuardedModelPort,
    ModelReturnUnconfirmed,
)
from ocean_resources.model_executor import ModelSpec


def test_journal_permission_rechecked_after_last_native_process_sample(tmp_path, monkeypatch):
    spec = ModelSpec("fixture:1", "a" * 64, 4096)
    process = {"pid": 10, "created_at": 2.0, "boot_time": 1.0}
    policy = resource_load_pending.REVIEWED_POLICY_SHA256
    monkeypatch.setenv("BACH_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(local_resource_reserve, "read_policy", lambda: ({},policy))
    samples=[]
    current=[True]
    def port_process(_):
        samples.append(1)
        if len(samples)==2:
            current[0]=False
        return process,10
    def validate(*args,**kw):
        if not current[0]:
            raise RuntimeError("fixture native permission revoked")
    monkeypatch.setattr(resource_load_pending,"native_model_process",port_process)
    monkeypatch.setattr(ocean_resources_provider,"load_verified",lambda _:{
        "ocean_resources.model_dispatch":SimpleNamespace(require_dispatch_permission=validate)})
    permit={"phase":"MAY_LOAD","workload_sha256":spec.fingerprint(),"writer_readback":{},
            "policy_sha256":policy,"deadline":110.0,"baseline":{"process":process}}
    authority={k:"fixture" for k in ("host_id","authority_id","client_id")}
    target={"socket_id":"s","binding_id":"b","agent_id":"a","backend":"ollama","model":spec.model}
    def provider_readback(_,path,payload):
        assert payload is None
        return {"/api/version":{"version":"0.33.3"},
                "/api/tags":{"models":[{"name":spec.model,"digest":spec.digest}]},"/api/ps":{"models":[]}}[path]
    async def scenario():
        async with HostInferenceGate().turn("fixture","background", model_target=target):
            with pytest.raises(ModelReturnUnconfirmed):
                GuardedModelPort(transport=provider_readback,clock=lambda:100.0).check_load_under_owner(spec,permit,authority=authority)
    asyncio.run(scenario())
