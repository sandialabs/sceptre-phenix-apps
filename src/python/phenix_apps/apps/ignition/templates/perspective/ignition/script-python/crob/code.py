def openPopup(deviceName, index=None):
	params = {"deviceName": deviceName}
	if index is not None:
		params["index"] = index
	system.perspective.openPopup(
		"crob",
		"popups/sendCrob",
		params=params,
		title="Send CROB - " + deviceName,
		modal=True
	)