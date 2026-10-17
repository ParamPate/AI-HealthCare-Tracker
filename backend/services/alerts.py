CRIT_NEEDED = 3
state = {}  # seat_id -> {"crit": int, "alert_id": int | None}

def classify(rr, severity, hr):
    sev = severity if severity in ("warning", "critical") else "normal"
    if sev == "normal" and rr is not None:
        if rr > 28 or rr < 8: sev = "critical"
        elif rr > 22 or rr < 10: sev = "warning"
    if hr is not None:
        if hr > 115 or hr < 50: sev = "critical"
        elif hr > 100 and sev == "normal": sev = "warning"
    return sev

def evaluate(seat_id, sev):
    s = state.setdefault(seat_id, {"crit": 0, "alert_id": None})
    if sev == "critical":
        s["crit"] += 1
    else:
        s["crit"] = 0
        if sev == "normal":
            s["alert_id"] = None
    fire = s["crit"] >= CRIT_NEEDED and s["alert_id"] is None
    return s, fire
