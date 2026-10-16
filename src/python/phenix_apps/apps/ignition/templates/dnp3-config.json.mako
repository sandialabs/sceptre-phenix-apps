{
  "profile": {
    "type": "com.inductiveautomation.Dnp3DeviceType"
  },
  "settings": {
    "advanced": {
      "appLayerDebugLogging": false,
      "autoTimeSync": false,
      "octetStringsAreStrings": false,
      "physLayerDebugLogging": false
    },
    "analogOperation": {
      "commandMode": "DIRECT_OPERATE",
      "readAfterOperate": false,
      "readAfterOperateDelay": 0
    },
    "binaryOperation": {
      "commandMode": "DIRECT_OPERATE",
      "count": 1,
      "offTime": 0,
      "onTime": 0,
      "ot": "LATCH",
      "readAfterOperate": false,
      "readAfterOperateDelay": 0,
      "tcc": "NUL"
    },
    "connectivity": {
      "destinationAddress": ${device["destination_address"]},
      "hostname": "${device["ip"]}",
      "keepAliveTimeout": 3600000,
      "port": ${device["port"]},
      "responseTimeout": 5000,
      "sourceAddress": ${device["source_address"]}
    },
    "dataAcquisition": {
      "class1PollPeriod": ${device["polling"]["class1"]},
      "class2PollPeriod": ${device["polling"]["class2"]},
      "class3PollPeriod": ${device["polling"]["class3"]},
      "integrityPollPeriod": ${device["polling"]["integrity"]},
      "unsolicitedEventClasses": {
        "class1": false,
        "class2": false,
        "class3": false
      }
    }
  }
}
