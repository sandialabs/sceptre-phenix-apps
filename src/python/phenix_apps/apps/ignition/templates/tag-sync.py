	import re
	logger = system.util.getLogger("phenix.tag-sync")
	# OPC browse reports java classes; tag JSON needs Ignition type names
	type_map = {
		"Boolean": "Boolean",
		"Byte": "Int1",
		"Short": "Int2",
		"Integer": "Int4",
		"Long": "Int8",
		"UByte": "Int2",
		"UShort": "Int4",
		"UInteger": "Int8",
		"ULong": "Int8",
		"Float": "Float4",
		"Double": "Float8",
		"String": "String",
		"DateTime": "DateTime",
	}
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
				# brackets are illegal in tag names ("[Diagnostics]" -> "_Diagnostics_")
				relative = p.getOpcItemPath().split("]", 1)[-1].replace("[", "_").replace("]", "_")
				parts = relative.split("/")
				at = ""
				for part in parts[:-1]:
					key = at + "/" + part
					if key not in folders:
						sub = {"name": part, "tagType": "Folder", "tags": []}
						folders[at]["tags"].append(sub)
						folders[key] = sub
					at = key
				cls = re.search(r"(\w+)\W*$", str(p.getDataType())).group(1)
				data_type = type_map.get(cls)
				if data_type is None and cls in type_map.values():
					data_type = cls
				if data_type is None:
					leaf = parts[-1]
					if leaf.startswith("Analog"):
						data_type = "Float8"
					elif leaf.startswith("Binary"):
						data_type = "Boolean"
					else:
						data_type = "String"
				folders[at]["tags"].append({
					"name": parts[-1],
					"tagType": "AtomicTag",
					"valueSource": "opc",
					"opcServer": "Ignition OPC UA Server",
					"opcItemPath": p.getOpcItemPath(),
					"dataType": data_type,
				})
			system.tag.configure("[default]", [root], "m")
			logger.info("imported %d points for device %s" % (len(points), device))
	except Exception as e:
		logger.warn("tag sync failed: %s" % e)
