import math
import re
import struct

OUTPUT_POINT = re.compile(r"(Binary|Analog)Output/?(\d+)$")

# Group 41 variation -> encodable range
ANALOG_LIMITS = {
	1: (-2147483648, 2147483647),
	2: (-32768, 32767),
	3: (-3.4028234663852886e38, 3.4028234663852886e38),
	4: (-1.7976931348623157e308, 1.7976931348623157e308),
}


def openPopup(deviceName, point=None):
	params = {"deviceName": deviceName, "command": "crob"}
	m = OUTPUT_POINT.search(point or "")
	if m:
		params["index"] = int(m.group(2))
		if m.group(1) == "Analog":
			params["command"] = "analog"
	system.perspective.openPopup(
		"command",
		"popups/sendCommand",
		params=params,
		title="DNP3 Command - " + deviceName,
		modal=True
	)


def analogValue(value, variation):
	"""Validate a setpoint for a Group 41 variation; keep in sync with the api doPost."""
	if variation not in ANALOG_LIMITS:
		raise ValueError("variation must be between 1 and 4")
	if isinstance(value, bool) or not isinstance(value, (int, long, float)):
		raise ValueError("value must be a number")
	try:
		number = float(value)
	except OverflowError:
		raise ValueError("value is out of range")
	if math.isnan(number) or math.isinf(number):
		raise ValueError("value must be finite")

	minimum, maximum = ANALOG_LIMITS[variation]
	# Check the original value, before float coercion can round a large long.
	if isinstance(value, (int, long)):
		minimum, maximum = long(minimum), long(maximum)
	if not minimum <= value <= maximum:
		raise ValueError("value is out of range for variation %s" % variation)
	if variation in (1, 2):
		if value != int(value):
			raise ValueError("value must be integer-valued for variation %s" % variation)
		return int(value)
	if variation == 3:
		encoded = struct.unpack("!f", struct.pack("!f", number))[0]
		if math.isinf(encoded) or (number != 0 and encoded == 0):
			raise ValueError("value cannot be represented as float32")
	return number
