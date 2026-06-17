from __future__ import annotations

from watchdirs.models import MountDecision, MountInfo, MountPolicy

DEFAULT_SKIPPED_FILESYSTEMS = frozenset({
    "proc",
    "sysfs",
    "devtmpfs",
    "devpts",
    "tmpfs",
    "cgroup2",
    "pstore",
    "securityfs",
    "debugfs",
    "tracefs",
    "configfs",
    "fusectl",
    "nsfs",
})
DEFAULT_CONTAINER_FILESYSTEMS = frozenset({"overlay", "nsfs"})


def classify_mount(mount: MountInfo | None, policy: MountPolicy | None = None) -> MountDecision:
    if mount is None:
        return MountDecision(
            include=True,
            reason="no mount classification available",
            filesystem_type=None,
            mount_id=None,
            device_changed=False,
        )

    resolved_policy = policy or MountPolicy()
    filesystem_type = mount.filesystem_type
    if filesystem_type in resolved_policy.included_filesystems:
        return MountDecision(
            include=True,
            reason=f"{filesystem_type} explicitly included by configuration",
            filesystem_type=filesystem_type,
            mount_id=mount.mount_id,
            device_changed=False,
        )

    if resolved_policy.skip_overlay and filesystem_type == "overlay":
        return MountDecision(
            include=False,
            reason="overlay mount skipped by default",
            filesystem_type=filesystem_type,
            mount_id=mount.mount_id,
            device_changed=False,
        )

    if resolved_policy.skip_namespace and filesystem_type == "nsfs":
        return MountDecision(
            include=False,
            reason="nsfs mount skipped by default",
            filesystem_type=filesystem_type,
            mount_id=mount.mount_id,
            device_changed=False,
        )

    skipped_filesystems = DEFAULT_SKIPPED_FILESYSTEMS | resolved_policy.skipped_filesystems
    if filesystem_type in skipped_filesystems:
        return MountDecision(
            include=False,
            reason=f"{filesystem_type} skipped by default mount policy",
            filesystem_type=filesystem_type,
            mount_id=mount.mount_id,
            device_changed=False,
        )

    return MountDecision(
        include=True,
        reason=f"{filesystem_type} included",
        filesystem_type=filesystem_type,
        mount_id=mount.mount_id,
        device_changed=False,
    )
