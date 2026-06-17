from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from watchdirs.models import MountInfo

PATH_SEPARATOR = b"/"
MIN_LEFT_FIELDS = 6
MIN_RIGHT_FIELDS = 3
BACKSLASH = b"\\"
MIN_OCTAL_DIGIT = 0x30
MAX_OCTAL_DIGIT = 0x37


def parse_mountinfo(raw_mountinfo: str | bytes | Iterable[str] | Iterable[bytes]) -> tuple[MountInfo, ...]:
    mounts: list[MountInfo] = []
    for raw_line in _iter_lines(raw_mountinfo):
        line = raw_line.strip()
        if not line:
            continue

        left, separator, right = line.partition(b" - ")
        if not separator:
            raise ValueError(f"mountinfo row missing separator: {line!r}")

        left_fields = left.split()
        right_fields = right.split()
        if len(left_fields) < MIN_LEFT_FIELDS or len(right_fields) < MIN_RIGHT_FIELDS:
            raise ValueError(f"mountinfo row has too few fields: {line!r}")

        mounts.append(
            MountInfo(
                mount_id=int(left_fields[0]),
                parent_id=int(left_fields[1]),
                major_minor=left_fields[2].decode("utf-8", "surrogateescape"),
                root=unescape_mount_path(left_fields[3]),
                mount_point=unescape_mount_path(left_fields[4]),
                options=_split_csv_bytes(left_fields[5]),
                filesystem_type=right_fields[0].decode("utf-8", "surrogateescape"),
                mount_source=right_fields[1].decode("utf-8", "surrogateescape"),
                super_options=_split_csv_bytes(right_fields[2]),
            )
        )
    return tuple(mounts)


def load_mountinfo(path: str | Path = "/proc/self/mountinfo") -> tuple[MountInfo, ...]:
    return parse_mountinfo(Path(path).read_bytes())


def find_mount_for_path(path_value: str | bytes | Path, mounts: tuple[MountInfo, ...]) -> MountInfo | None:
    path_raw = _normalize_path_bytes(path_value)
    best_match: MountInfo | None = None
    best_length = -1

    for mount in mounts:
        mount_point = _normalize_mount_point(mount.mount_point)
        if _path_matches_mount(path_raw, mount_point) and len(mount_point) > best_length:
            best_match = mount
            best_length = len(mount_point)
    return best_match


def unescape_mount_path(value: str | bytes) -> bytes:
    raw = value.encode("utf-8", "surrogateescape") if isinstance(value, str) else value
    result = bytearray()
    index = 0

    while index < len(raw):
        current = raw[index]
        if current == BACKSLASH[0] and index + 3 < len(raw):
            candidate = raw[index + 1 : index + 4]
            if all(MIN_OCTAL_DIGIT <= digit <= MAX_OCTAL_DIGIT for digit in candidate):
                result.append(int(candidate.decode("ascii"), 8))
                index += 4
                continue
        result.append(current)
        index += 1

    return bytes(result)


def _iter_lines(raw_mountinfo: str | bytes | Iterable[str] | Iterable[bytes]) -> Iterable[bytes]:
    if isinstance(raw_mountinfo, bytes):
        return raw_mountinfo.splitlines()
    if isinstance(raw_mountinfo, str):
        return raw_mountinfo.encode("utf-8", "surrogateescape").splitlines()
    return [line.encode("utf-8", "surrogateescape") if isinstance(line, str) else line for line in raw_mountinfo]


def _split_csv_bytes(raw_value: bytes) -> tuple[str, ...]:
    return tuple(chunk.decode("utf-8", "surrogateescape") for chunk in raw_value.split(b",") if chunk)


def _normalize_path_bytes(path_value: str | bytes | Path) -> bytes:
    if isinstance(path_value, bytes):
        raw_path = path_value
    else:
        raw_path = Path(path_value).resolve(strict=False).as_posix().encode("utf-8", "surrogateescape")
    normalized = raw_path.rstrip(PATH_SEPARATOR)
    return normalized or PATH_SEPARATOR


def _normalize_mount_point(mount_point: bytes) -> bytes:
    normalized = mount_point.rstrip(PATH_SEPARATOR)
    return normalized or PATH_SEPARATOR


def _path_matches_mount(path_raw: bytes, mount_point: bytes) -> bool:
    if mount_point == PATH_SEPARATOR:
        return True
    return path_raw == mount_point or path_raw.startswith(mount_point + PATH_SEPARATOR)
