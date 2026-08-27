	logger = system.util.getLogger("phenix.tag-sync")
	try:
		devices = system.device.listDevices()
		for row in range(devices.getRowCount()):
			device = str(devices.getValueAt(row, "Name"))
			points = [
				p
				for p in system.opc.browse(opcServer="Ignition OPC UA Server", device=device)
				if p.getDataType() is not None
			]
			if not points:
				continue
			try:
				results = system.tag.browse("[default]" + device, {"recursive": True}).getResults()
				existing = len([r for r in results if not r["hasChildren"]])
			except Exception:
				existing = 0
			if len(points) <= existing:
				continue
			root = {"name": device, "tagType": "Folder", "tags": []}
			folders = {"": root}
			for p in points:
				relative = p.getOpcItemPath().split("]", 1)[-1]
				parts = relative.split("/")
				at = ""
				for part in parts[:-1]:
					key = at + "/" + part
					if key not in folders:
						sub = {"name": part, "tagType": "Folder", "tags": []}
						folders[at]["tags"].append(sub)
						folders[key] = sub
					at = key
				folders[at]["tags"].append({
					"name": parts[-1],
					"tagType": "AtomicTag",
					"valueSource": "opc",
					"opcServer": "Ignition OPC UA Server",
					"opcItemPath": p.getOpcItemPath(),
					"dataType": str(p.getDataType()),
				})
			system.tag.configure("[default]", [root], "m")
			logger.info("imported %d points for device %s" % (len(points), device))
	except Exception as e:
		logger.warn("tag sync failed: %s" % e)
