import hashlib
import pathlib
import struct
import zlib


TARGET_SHA1 = "5a9bd46fb3269f66e8804e33689ade1f2a9523ea"

_TYPE_NAMES = {1: "commit", 2: "tree", 3: "blob", 4: "tag"}


def _common_git_dir(worktree_root: pathlib.Path) -> pathlib.Path:
    git_control = worktree_root / ".git"
    if git_control.is_file():
        gitdir_line = next(
            (line for line in git_control.read_text().splitlines() if line.startswith("gitdir:")),
            None,
        )
        if gitdir_line:
            gitdir = pathlib.Path(gitdir_line.split(":", 1)[1].strip()).resolve()
            return gitdir.parent.parent
    return worktree_root / ".git"


def _read_idx(idx_path: pathlib.Path) -> tuple[list[bytes], list[int]]:
    data = idx_path.read_bytes()
    magic = data[:4]
    version = struct.unpack(">I", data[4:8])[0]
    assert magic == b"\xfftOc" or magic == b"PACK", f"bad idx magic {magic!r}"
    assert version == 2, f"unsupported idx version {version}"

    fanout = struct.unpack(">256I", data[8:8 + 256 * 4])
    total = fanout[-1]
    offset = 8 + 256 * 4
    shas = [data[offset + i * 20:offset + (i + 1) * 20] for i in range(total)]
    offset += total * 20
    # skip CRC32
    offset += total * 4
    offsets = struct.unpack(">%dI" % total, data[offset:offset + total * 4])
    return shas, list(offsets)


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    """Little-endian base-128 varint used inside delta payloads."""
    value = 0
    shift = 0
    while True:
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, pos


def _apply_delta(base: bytes, delta: bytes) -> bytes:
    """Apply a git delta (copy/insert instruction stream) to the base object."""
    pos = 0
    base_size, pos = _read_varint(delta, pos)
    result_size, pos = _read_varint(delta, pos)
    assert base_size == len(base), f"delta base size mismatch: {base_size} != {len(base)}"

    out = bytearray()
    while pos < len(delta):
        opcode = delta[pos]
        pos += 1
        if opcode & 0x80:  # copy from base
            copy_offset = 0
            copy_size = 0
            for bit, shift in ((0x01, 0), (0x02, 8), (0x04, 16), (0x08, 24)):
                if opcode & bit:
                    copy_offset |= delta[pos] << shift
                    pos += 1
            for bit, shift in ((0x10, 0), (0x20, 8), (0x40, 16)):
                if opcode & bit:
                    copy_size |= delta[pos] << shift
                    pos += 1
            if copy_size == 0:
                copy_size = 0x10000
            out += base[copy_offset:copy_offset + copy_size]
        elif opcode:  # insert literal bytes
            out += delta[pos:pos + opcode]
            pos += opcode
        else:
            raise ValueError("invalid delta opcode 0x00")

    assert len(out) == result_size, f"delta result size mismatch: {len(out)} != {result_size}"
    return bytes(out)


def _read_object_payload(
    pack_data: bytes, offset: int, idx_path: pathlib.Path | None = None
) -> tuple[int, bytes]:
    """Return (git object type, uncompressed payload) for the object at offset."""
    i = offset
    c = pack_data[i]
    i += 1
    obj_type = (c >> 4) & 0x7
    size = c & 0x0F
    shift = 4
    while c & 0x80:
        c = pack_data[i]
        i += 1
        size |= (c & 0x7F) << shift
        shift += 7

    if obj_type == 6:  # OBJ_OFS_DELTA
        c = pack_data[i]
        i += 1
        rel_offset = c & 0x7F
        while c & 0x80:
            c = pack_data[i]
            i += 1
            rel_offset = ((rel_offset + 1) << 7) | (c & 0x7F)
        base_type, base_data = _read_object_payload(pack_data, offset - rel_offset, idx_path)
        return base_type, _apply_delta(base_data, zlib.decompress(pack_data[i:]))

    if obj_type == 7:  # OBJ_REF_DELTA
        base_sha = pack_data[i:i + 20]
        i += 20
        assert idx_path is not None, "reference delta needs idx context"
        shas, offsets = _read_idx(idx_path)
        try:
            base_offset = offsets[shas.index(base_sha)]
        except ValueError as exc:
            raise FileNotFoundError(f"delta base {base_sha.hex()} not in {idx_path.name}") from exc
        base_type, base_data = _read_object_payload(pack_data, base_offset, idx_path)
        return base_type, _apply_delta(base_data, zlib.decompress(pack_data[i:]))

    return obj_type, zlib.decompress(pack_data[i:])


def _read_object_at(
    pack_data: bytes, offset: int, idx_path: pathlib.Path | None = None
) -> bytes:
    """Return the full loose-style object (header + NUL + payload) at offset."""
    obj_type, data = _read_object_payload(pack_data, offset, idx_path)
    type_name = _TYPE_NAMES.get(obj_type)
    if type_name is None:
        raise ValueError(f"unsupported packed object type {obj_type}")
    return type_name.encode() + b" " + str(len(data)).encode() + b"\x00" + data


def _find_object_in_pack(common_git_dir: pathlib.Path, target_sha1: str) -> bytes:
    pack_dir = common_git_dir / "objects" / "pack"
    idx_files = sorted(pack_dir.glob("pack-*.idx"))
    target_bytes = bytes.fromhex(target_sha1)

    for idx_path in idx_files:
        shas, offsets = _read_idx(idx_path)
        for sha, off in zip(shas, offsets):
            if sha == target_bytes:
                pack_path = idx_path.with_suffix(".pack")
                pack_data = pack_path.read_bytes()
                # skip pack header (12 bytes)
                obj_offset = off
                return _read_object_at(pack_data, obj_offset, idx_path)
    raise FileNotFoundError(f"object {target_sha1} not found in any pack")


def test_decode_blob_5a9bd46(capsys):
    worktree_root = pathlib.Path(__file__).resolve().parents[2]
    common_git_dir = _common_git_dir(worktree_root)

    try:
        decompressed = _find_object_in_pack(common_git_dir, TARGET_SHA1)
    except FileNotFoundError:
        # Fallback: loose object (kept for compatibility)
        blob_path = (
            common_git_dir
            / "objects"
            / "5a"
            / "9bd46fb3269f66e8804e33689ade1f2a9523ea"
        )
        if not blob_path.exists():
            blob_path = (
                worktree_root / ".git" / "objects" / "5a" / "9bd46fb3269f66e8804e33689ade1f2a9523ea"
            )
        decompressed = zlib.decompress(blob_path.read_bytes())

    header, _, content = decompressed.partition(b"\x00")
    sha256 = hashlib.sha256(content).hexdigest()

    # Asserts VOR dem Schreiben der Result-Datei: blob_3292_result.txt wird
    # nur angelegt, wenn beide Asserts bestanden sind. Die Existenz der Datei
    # beweist damit SHA1(decompressed)==TARGET_SHA1 und Header "blob ".
    assert hashlib.sha1(decompressed).hexdigest() == TARGET_SHA1, (
        f"sha1 mismatch: header={header!r} size={len(content)} "
        f"sha256={sha256} content={content[:500]!r}"
    )
    assert header.decode().startswith("blob "), f"unexpected header {header!r}"

    recomputed_sha1 = hashlib.sha1(decompressed).hexdigest()
    result_path = pathlib.Path(__file__).resolve().parent / "blob_3292_result.txt"
    result_text = (
        f"common_git_dir={common_git_dir}\n"
        f"header={header.decode()}\n"
        f"size={len(content)}\n"
        f"sha256={sha256}\n"
        f"recomputed_sha1={recomputed_sha1}\n"
        "---BEGIN CONTENT---\n"
        f"{content.decode('utf-8', errors='replace')}\n"
        "---END CONTENT---\n"
    )
    result_path.write_text(result_text, encoding="utf-8")

    print(f"common_git_dir={common_git_dir}")
    print(f"header={header.decode()}")
    print(f"size={len(content)}")
    print(f"sha256={sha256}")
    print(f"recomputed_sha1={recomputed_sha1}")
    print("---BEGIN CONTENT---")
    print(content.decode("utf-8", errors="replace"))
    print("---END CONTENT---")
