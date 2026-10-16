def doGet(request, session):
    def error(status, message):
        request["servletResponse"].setStatus(status)
        return {"json": {"status": "error", "message": message}}

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
        # Points live in the [default] provider under the device's folder,
        # named after ot-sim devices and variables (or by DNP3 address when
        # they were discovered); keys are the path below that folder.
        folder = "[default]" + device
        paths = [
            str(r["fullPath"])
            for r in system.tag.browse(folder, {"recursive": True}).getResults()
            if not r["hasChildren"]
        ]
        reads = [path + ".OpcItemPath" for path in paths] if details == "true" else []
        values = system.tag.readBlocking(paths + reads) if paths else []
        result[device] = {}
        for i in range(len(paths)):
            qualified = values[i]
            value = qualified.getValue()
            if details == "true":
                value = {
                    "value": value,
                    "quality": str(qualified.getQuality()),
                    "timestamp": qualified.getTimestamp().getTime(),
                    "address": values[len(paths) + i].getValue(),
                }
            result[device][paths[i][len(folder) + 1:]] = value
    return {"json": result}
