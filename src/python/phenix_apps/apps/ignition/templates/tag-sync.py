	# Intentionally indented for inclusion in json
	import re
	logger = system.util.getLogger("phenix.tag-sync")
	history = {
		"historyEnabled": True,
		"historyProvider": history_provider,
		"sampleMode": "OnChange",
		"historicalDeadbandStyle": "Discrete",
		"historicalDeadbandMode": "Absolute",
		"historicalDeadband": 0.0,
		"historyTimeDeadband": 0,
		"historyMaxAge": 0,
	}

	def merge_tags(parent, tags):
		results = system.tag.configure(parent, tags, "m")
		if len(results) != len(tags) or any(not result.isGood() for result in results):
			logger.warn("tag configuration failed at %s: %s" % (parent, results))
			return False
		return True

	def reconcile_history(existing):
		by_parent = {}
		for path, tag in existing.items():
			if (str(tag["tagType"]) != "AtomicTag"
					or str(tag.get("valueSource")) != "opc"
					or str(tag["name"]) == "_TagSync_"):
				continue
			by_parent.setdefault(path.rsplit("/", 1)[0], []).append(path)
		properties = sorted(history)
		for parent, paths in by_parent.items():
			values = system.tag.readBlocking([
				path + "." + prop for path in paths for prop in properties
			])
			if len(values) != len(paths) * len(properties):
				logger.warn("incomplete history property read at %s" % parent)
				continue
			patches = []
			for i, path in enumerate(paths):
				current = values[i * len(properties):(i + 1) * len(properties)]
				if any(not value.quality.isGood() for value in current):
					logger.warn("cannot read history properties for %s; will retry" % path)
					continue
				if any(value.value != history[prop] for prop, value in zip(properties, current)):
					patch = {"name": path.rsplit("/", 1)[-1]}
					patch.update(history)
					patches.append(patch)
			if patches and merge_tags(parent, patches):
				logger.info("enabled history for %d tags at %s" % (len(patches), parent))

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
			if device == "_TagSync_":
				logger.warn("cannot import device using reserved tag name _TagSync_")
				continue
			# the browse also returns folder (OBJECT) nodes; only import real points
			points = [
				p
				for p in system.opc.browse(opcServer="Ignition OPC UA Server", device=device)
				if str(p.getType()) == "DATAVARIABLE"
			]
			if not points and not history_provider:
				continue
			existing = {
				str(tag["fullPath"]): tag
				for tag in system.tag.browse("[default]" + device, {"recursive": True}).getResults()
			}
			if history_provider:
				reconcile_history(existing)
			root = {"name": device, "tagType": "Folder", "tags": []}
			folders = {"": root}
			imported = 0
			for p in points:
				# brackets are illegal in tag names ("[Diagnostics]" -> "_Diagnostics_")
				relative = p.getOpcItemPath().split("]", 1)[-1].replace("[", "_").replace("]", "_")
				parts = relative.split("/")
				path = "[default]" + device + "/" + relative
				if path in existing:
					continue
				at = ""
				for part in parts[:-1]:
					key = at + "/" + part
					found = existing.get("[default]" + device + key)
					if found is not None and str(found["tagType"]) != "Folder":
						logger.warn("cannot import point below non-folder %s" % key)
						break
					if key not in folders:
						sub = {"name": part, "tagType": "Folder", "tags": []}
						folders[at]["tags"].append(sub)
						folders[key] = sub
					at = key
				else:
					cls = re.search(r"(\w+)\W*$", str(p.getDataType())).group(1)
					tag = {
						"name": parts[-1],
						"tagType": "AtomicTag",
						"valueSource": "opc",
						"opcServer": "Ignition OPC UA Server",
						"opcItemPath": p.getOpcItemPath(),
						"dataType": type_map.get(cls, "String"),
					}
					if history_provider and parts[-1] != "_TagSync_":
						tag.update(history)
					folders[at]["tags"].append(tag)
					imported += 1
			if imported and merge_tags("[default]", [root]):
				logger.info("imported %d points for device %s" % (imported, device))
	except Exception as e:
		logger.warn("tag sync failed: %s" % e)
