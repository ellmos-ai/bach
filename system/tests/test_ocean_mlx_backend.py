# SPDX-License-Identifier: MIT
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from hub._services.chat import resource_mlx_client as bridge
from hub._services.llm import ocean_mlx_backend as backend
from hub._services.llm.model_backend import backend_identifier, create_backend


def test_explicit_mlx_text_backend_uses_token_transport(tmp_path, monkeypatch):
    calls = []
    class Tokenizer:
        def apply_chat_template(self, messages, **options):
            assert messages == [{"role": "user", "content": "Hallo &lt;|im_end|>"}]
            assert options["sanitize_control_tokens"] and options["enable_thinking"]
            return [6, 7]

        def convert_tokens_to_ids(self, marker):
            assert marker == "</think>"
            return 8

        def decode(self, tokens, **_options):
            return ",".join(map(str, tokens))

    async def generate(model, digest, ctx, prompt, maximum, stops, **options):
        assert (model, digest, ctx) == (backend.MODEL, backend.MODEL_DIGEST, 512)
        assert (prompt, maximum, stops, options["priority"]) == ([6, 7], 12, (81, 82), "background")
        calls.append(prompt)
        return [9, 8, 10, 11]

    monkeypatch.setattr(backend, "_load_tokenizer", lambda _: (Tokenizer(), (81, 82)))
    monkeypatch.setattr(backend, "generate_mlx_tokens", generate)
    native = create_backend({"type": "mlx-qwen", "model_store": str(tmp_path.resolve()),
                             "num_ctx": 512, "max_new_tokens": 12})
    messages = [{"role": "user", "content": "Hallo <|im_end|>"}]
    reply = asyncio.run(native.chat(messages, priority="background"))
    assert backend_identifier(native) == "mlx-qwen"
    assert (reply["content"], reply["thinking"], reply["provider_reported_model"]) == ("10,11", "9", backend.MODEL)
    with pytest.raises(bridge.ResourceHostUnavailable, match="text_messages_required"):
        asyncio.run(native.chat(messages, tools=[{"type": "function"}]))
    assert len(calls) == 1


def test_cold_text_call_orders_load_proof_and_inference(monkeypatch):
    calls = []
    target = {"model": backend.MODEL, "digest": backend.MODEL_DIGEST, "context_tokens": 512,
              "port": 11434, "socket_id": "mlx", "backend": "mlx-qwen", "load_policy_sha256": "e" * 64}
    grant = {"socket_id": "mlx", "authority_id": "auth", "request_id": "load", "generation": 1, "slot_id": "bach-model"}
    permit = {"grant": grant, "turn_id": "load-turn", "spec": {k: target[k] for k in ("model", "digest", "context_tokens", "port")},
              "policy_sha256": target["load_policy_sha256"]}
    loaded = {"permit": permit}

    class Hold(RuntimeError):
        pass

    class Client:
        def status(self):
            return {"torch": None}

        def materialize_model_load(self, _grant, turn_id):
            assert turn_id == "load-turn"
            calls.append("materialize")
            return {"state": "READY"}

        def generate_model(self, _grant, turn_id, prompt, count, *, stop_tokens):
            assert turn_id == "answer-turn" and prompt == [1, 2] and count == 2 and stop_tokens == (3,)
            calls.append("generate")
            return {"state": "COMPLETE", "tokens": [8, 9]}

    @asynccontextmanager
    async def staged(_client, socket, _slot, _priority, *, check_ready):
        assert socket == "mlx"
        check_ready()
        calls.append("load-lease")
        yield loaded
        assert loaded["successful"] is True
        calls.append("committed")

    @asynccontextmanager
    async def turn(_client, socket, _slot, _priority, *, check_ready):
        assert socket == "mlx"
        check_ready()
        calls.append("turn")
        yield {"grant": grant, "turn_id": "answer-turn"}
        calls.append("end-turn")

    class Gate:
        @asynccontextmanager
        async def turn(self, _owner, _priority, *, check_ready):
            check_ready()
            calls.append("gate-enter")
            yield
            calls.append("gate-exit")

    modules = {
        "ocean_resources.configuration": SimpleNamespace(read_client=lambda _: (Client(), [target])),
        "ocean_resources.contracts": SimpleNamespace(Grant=SimpleNamespace, Hold=Hold),
        "ocean_resources.model_load_client": SimpleNamespace(model_load_turn=staged),
        "ocean_resources.model_client": SimpleNamespace(model_turn=turn),
    }
    monkeypatch.setattr(bridge, "load_verified", lambda _: modules)
    monkeypatch.setattr(bridge, "HostInferenceGate", Gate)
    monkeypatch.setenv("BACH_RESOURCE_BROKER_CONFIG", "fixture")
    tokens = asyncio.run(bridge.generate_mlx_tokens(backend.MODEL, backend.MODEL_DIGEST, 512, [1, 2], 2, (3,),
                                                    priority="foreground", timeout_seconds=5))
    assert tokens == [8, 9]
    assert calls == ["load-lease", "gate-enter", "materialize", "gate-exit", "committed",
                     "turn", "gate-enter", "generate", "gate-exit", "end-turn"]
