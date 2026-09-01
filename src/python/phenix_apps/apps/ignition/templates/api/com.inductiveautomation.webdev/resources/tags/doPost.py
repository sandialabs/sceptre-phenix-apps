def doPost(request, session):
    import math
    import struct

    def error(status, message):
        request['servletResponse'].setStatus(status)
        return {'json': {'status': 'error', 'message': message}}

    def integer(name, value, minimum, maximum):
        if isinstance(value, bool) or not isinstance(value, (int, long)):
            raise ValueError('%s must be an integer' % name)
        if not minimum <= value <= maximum:
            raise ValueError('%s must be between %s and %s' % (name, minimum, maximum))
        return value

    def analog_value(value, variation):
        if isinstance(value, bool) or not isinstance(value, (int, long, float)):
            raise ValueError('value must be a number')
        try:
            number = float(value)
        except OverflowError:
            raise ValueError('value is out of range')
        if math.isnan(number) or math.isinf(number):
            raise ValueError('value must be finite')

        limits = {
            1: (-2147483648, 2147483647),
            2: (-32768, 32767),
            3: (-3.4028234663852886e38, 3.4028234663852886e38),
            4: (-1.7976931348623157e308, 1.7976931348623157e308),
        }
        minimum, maximum = limits[variation]
        # Check the original value, before float coercion can round a large long.
        if isinstance(value, (int, long)):
            minimum, maximum = long(minimum), long(maximum)
        if not minimum <= value <= maximum:
            raise ValueError('value is out of range for variation %s' % variation)
        if variation in (1, 2):
            if value != int(value):
                raise ValueError('value must be integer-valued for variation %s' % variation)
            return int(value)
        if variation == 3:
            encoded = struct.unpack('!f', struct.pack('!f', number))[0]
            if math.isinf(encoded) or (number != 0 and encoded == 0):
                raise ValueError('value cannot be represented as float32')
        return number

    data = request.get('postData')
    try:
        if not isinstance(data, dict):
            raise ValueError('body must be a JSON object')
        deviceName = data.get('deviceName')
        if not isinstance(deviceName, basestring) or not deviceName.strip():
            raise ValueError('deviceName must be a nonblank string')
        pointType = data.get('pointType')
        if not isinstance(pointType, basestring) or pointType not in ('analog', 'binary'):
            raise ValueError('pointType must be analog or binary')
        index = integer('index', data.get('index'), 0, 65535)

        allowed = {'deviceName', 'pointType', 'index'}
        if pointType == 'analog':
            allowed.update(('value', 'variation'))
        else:
            allowed.update(('tcc', 'opType', 'count', 'onTime', 'offTime'))
        if set(data) - allowed:
            raise ValueError('body contains unsupported fields for pointType %s' % pointType)

        if pointType == 'analog':
            variation = integer('variation', data.get('variation', 3), 1, 4)
            value = analog_value(data.get('value'), variation)
        else:
            tcc = integer('tcc', data.get('tcc', 1), 0, 2)
            opType = integer('opType', data.get('opType', 3), 0, 4)
            count = integer('count', data.get('count', 1), 1, 255)
            onTime = integer('onTime', data.get('onTime', 1000), 0, 2147483647)
            offTime = integer('offTime', data.get('offTime', 1000), 0, 2147483647)
    except ValueError as exc:
        return error(400, str(exc))

    devices = system.device.listDevices()
    if not any(
        devices.getValueAt(row, 'Name') == deviceName
        for row in range(devices.getRowCount())
    ):
        return error(404, 'Unknown device: %s' % deviceName)

    result = {'status': 'sent', 'device': deviceName, 'index': index, 'pointType': pointType}
    # These calls return nothing; "sent" is not independent power-model feedback.
    if pointType == 'analog':
        system.dnp.directOperateAnalog(deviceName, variation, index, value)
        result.update({'variation': variation, 'value': value})
    else:
        system.dnp.directOperateBinary(deviceName, index, tcc, opType, count, onTime, offTime)
        result.update({'tcc': tcc, 'opType': opType, 'count': count,
                       'onTime': onTime, 'offTime': offTime})

    return {'json': result}
