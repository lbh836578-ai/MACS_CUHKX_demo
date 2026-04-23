"""Helpers for applying runtime IMU device selection overrides."""


def normalise_imu_labels(labels):
    normalised = []
    seen = set()
    for item in labels or []:
        if item is None:
            continue
        for raw_label in str(item).split(","):
            label = raw_label.strip()
            if not label or label in seen:
                continue
            normalised.append(label)
            seen.add(label)
    return normalised


def apply_runtime_imu_selection(config, selected_labels):
    labels = normalise_imu_labels(selected_labels)
    if not labels:
        return config

    multimodal_cfg = config.setdefault("multimodal", {})
    imu_cfg = multimodal_cfg.setdefault("imu", {})
    imu_cfg["active_devices"] = labels
    return config


def resolve_enabled_imu_devices(imu_cfg):
    active_labels = set(normalise_imu_labels(imu_cfg.get("active_devices", [])))
    devices = []

    for index, item in enumerate(imu_cfg.get("devices", []), start=1):
        item = item or {}
        label = item.get("label") or f"imu{index:02d}"
        enabled = bool(item.get("enabled", True))
        mac = (item.get("mac") or "").strip()

        if not enabled:
            continue
        if active_labels and label not in active_labels:
            continue
        if not mac:
            continue

        devices.append({
            "label": label,
            "mac": mac,
            "enabled": enabled,
        })

    return devices