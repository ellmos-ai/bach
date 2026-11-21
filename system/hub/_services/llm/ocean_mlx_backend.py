# SPDX-License-Identifier: MIT
"""Opt-in text-only Qwen backend over the authenticated Ocean resource host."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

from hub._services.chat.resource_host_client import ResourceHostUnavailable
from hub._services.chat.resource_mlx_client import generate_mlx_tokens
from hub._services.llm.model_backend import ModelBackend

MODEL = "qwen3.8:27b-mlx"
MODEL_DIGEST = "5642e97495e1a088883805981563dcdc4a040c2f53388b7a41d1f24d3622cf7e"
_MANIFEST = "manifests/registry.ollama.ai/library/qwen3.8/27b-mlx"
_TEXT_CONTROL_MARKERS = ("<|im_start|>", "<|im_end|>", "<|endoftext|>", "<think>", "</think>")


def _safe_text(content):
    # Keep literal markup out of the chat-template protocol.
    for marker in _TEXT_CONTROL_MARKERS:
        content = content.replace(marker, marker.replace("<", "&lt;", 1))
    return content


def _read(path, limit):
    if path.is_symlink():
        raise ResourceHostUnavailable("resource_mlx_tokenizer_asset_linked")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ResourceHostUnavailable("resource_mlx_tokenizer_asset_too_large")
    return raw


def _load_tokenizer(store):
    from tokenizers import Tokenizer
    from transformers import PreTrainedTokenizerFast, __version__

    if __version__ != "5.15.0":
        raise ResourceHostUnavailable("resource_mlx_tokenizer_version_unreviewed")
    manifest = _read(store / _MANIFEST, 1024 * 1024)
    if hashlib.sha256(manifest).hexdigest() != MODEL_DIGEST:
        raise ResourceHostUnavailable("resource_mlx_tokenizer_manifest_changed")
    layers = json.loads(manifest)["layers"]

    def asset(name, limit):
        selected = [layer for layer in layers if layer.get("name") == name]
        if len(selected) != 1:
            raise ResourceHostUnavailable("resource_mlx_tokenizer_asset_ambiguous")
        fingerprint = selected[0]["digest"]
        if (len(fingerprint) != 71 or not fingerprint.startswith("sha256:")
                or any(c not in "0123456789abcdef" for c in fingerprint[7:])):
            raise ResourceHostUnavailable("resource_mlx_tokenizer_digest_invalid")
        data = _read(store / "blobs" / fingerprint.replace(":", "-"), limit)
        if "sha256:" + hashlib.sha256(data).hexdigest() != fingerprint:
            raise ResourceHostUnavailable("resource_mlx_tokenizer_asset_changed")
        return data

    config = json.loads(asset("tokenizer_config.json", 1024 * 1024))
    generation = json.loads(asset("generation_config.json", 1024 * 1024))
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=Tokenizer.from_str(asset("tokenizer.json", 16 * 1024 * 1024).decode("utf-8")),
        chat_template=config["chat_template"], eos_token=config["eos_token"], pad_token=config["pad_token"],
    )
    stops = generation["eos_token_id"]
    if (not isinstance(stops, list) or not stops
            or any(type(token) is not int or token < 0 for token in stops)):
        raise ResourceHostUnavailable("resource_mlx_stop_tokens_unavailable")
    return tokenizer, tuple(stops)


def _decode_answer(tokenizer, tokens, thinking_enabled):
    def decode(values):
        return tokenizer.decode(values, skip_special_tokens=True, clean_up_tokenization_spaces=False)

    if not thinking_enabled:
        return decode(tokens), ""
    close = tokenizer.convert_tokens_to_ids("</think>")
    if close not in tokens:
        return "", decode(tokens)
    index = tokens.index(close)
    return decode(tokens[index + 1:]), decode(tokens[:index])


class OceanMLXBackend(ModelBackend):
    """Text turns with an exact locally pinned tokenizer and Ocean-owned KV state."""

    backend_id = "mlx-qwen"

    def __init__(self, *, model_store, default_model=MODEL, num_ctx=4096, max_new_tokens=256,
                 timeout_seconds=600):
        self.model_store = Path(model_store)
        if not self.model_store.is_absolute() or self.model_store.resolve() != self.model_store:
            raise ValueError("Ein absoluter lokaler Modellpfad ist erforderlich")
        if (default_model != MODEL or type(num_ctx) is not int or not 512 <= num_ctx <= 262144
                or type(max_new_tokens) is not int or not 1 <= max_new_tokens < num_ctx
                or type(timeout_seconds) not in {int, float} or not 1 <= timeout_seconds <= 3600):
            raise ValueError("Ungültige Ocean-MLX-Textkonfiguration")
        self.default_model = default_model
        self.num_ctx, self.max_new_tokens, self.timeout_seconds = num_ctx, max_new_tokens, timeout_seconds
        self._tokenizer = None
        self._lock = asyncio.Lock()

    def get_default_model(self):
        return self.default_model

    def get_context_limit(self):
        return self.num_ctx

    def list_models(self):
        return [self.default_model] if os.environ.get("BACH_RESOURCE_BROKER_CONFIG") else []

    async def chat(self, messages, tools=None, think=True, model=None, *, priority="foreground", check_ready=None):
        if model not in {None, MODEL} or priority not in {"foreground", "background"}:
            raise ResourceHostUnavailable("resource_mlx_target_unavailable")
        if tools or not isinstance(messages, list) or not messages or any(
            not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant"}
            or not isinstance(message.get("content"), str) or message.get("tool_calls") for message in messages
        ):
            raise ResourceHostUnavailable("resource_mlx_text_messages_required")
        text = [{"role": message["role"], "content": _safe_text(message["content"])} for message in messages]
        async with self._lock:
            if check_ready is not None:
                check_ready()
            if self._tokenizer is None:
                self._tokenizer = await asyncio.to_thread(_load_tokenizer, self.model_store)
            tokenizer, stops = self._tokenizer
            prompt = await asyncio.to_thread(tokenizer.apply_chat_template, text, tokenize=True,
                                             return_dict=False, add_generation_prompt=True,
                                             enable_thinking=bool(think), sanitize_control_tokens=True)
            if (not isinstance(prompt, list) or not prompt or any(type(token) is not int for token in prompt)
                    or len(prompt) + self.max_new_tokens > self.num_ctx):
                raise ResourceHostUnavailable("resource_mlx_context_exceeded")
            tokens = await generate_mlx_tokens(MODEL, MODEL_DIGEST, self.num_ctx, prompt, self.max_new_tokens,
                                               stops, priority=priority, timeout_seconds=self.timeout_seconds,
                                               check_ready=check_ready)
            content, thinking = await asyncio.to_thread(_decode_answer, tokenizer, tokens, bool(think))
            if check_ready is not None:
                check_ready()
        self.last_resolved_model = MODEL
        return {"content": content, "thinking": thinking, "tool_calls": None,
                "raw_message": {"role": "assistant", "content": content}, "provider_reported_model": MODEL}
