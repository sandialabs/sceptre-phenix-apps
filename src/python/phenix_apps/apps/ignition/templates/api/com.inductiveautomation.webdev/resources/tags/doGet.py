def doGet(request, session):
    def error(status, message):
        request["servletResponse"].setStatus(status)
        return {"json": {"status": "error", "message": message}}

    server = "Ignition OPC UA Server"
    wanted = request["params"].get("device")
    details = request["params"].get("details", "false")
    if details not in ("true", "false"):
        return error(400, "details must be true or false")

    result = {}
    devices = system.device.listDevices()
    names = [
        str(devices.getValueAt(row, "Name"))
        for row in range(devices.getRowCount())
    ]
    if wanted and wanted not in names:
        return error(404, "Unknown device: %s" % wanted)
    for device in names:
        if wanted and device != wanted:
            continue
        # Only real points browse as DATAVARIABLE; skip folder (OBJECT) nodes.
        paths = [
            p.getOpcItemPath()
            for p in system.opc.browse(opcServer=server, device=device)
            if str(p.getType()) == "DATAVARIABLE"
        ]
        values = system.opc.readValues(server, paths) if paths else []
        result[device] = {}
        for i in range(len(paths)):
            qualified = values[i]
            value = qualified.getValue()
            if details == "true":
                value = {
                    "value": value,
                    "quality": str(qualified.getQuality()),
                    "timestamp": qualified.getTimestamp().getTime(),
                }
            result[device][paths[i]] = value
    return {"json": result}
