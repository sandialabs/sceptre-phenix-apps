#!/usr/bin/env python3

"""
Requires:

- Python 3.8.9+
- asyncua ('pip install asyncua') (https://github.com/FreeOpcUa/opcua-asyncio)

asyncio is magic.

Usage:
    python scada_to_elastic.py --help
"""

import argparse
import asyncio
import json
import logging
import platform
import sys
from configparser import ConfigParser
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, List, Set

from asyncua import Client, Node
from asyncua.common.subscription import DataChangeNotif
from elasticsearch import AsyncElasticsearch

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

__version__ = "0.4.0"

INDEX_TYPE_MAPPING = {
    "properties": {
        "@timestamp": {"type": "date"},
        "event": {"properties": {"ingested": {"type": "date"}}},
        "ecs": {"properties": {"version": {"type": "keyword"}}},
        "agent": {
            "properties": {
                "id": {"type": "keyword"},
                "type": {"type": "keyword"},
                "version": {"type": "keyword"},
            }
        },
        "observer": {
            "properties": {
                "geo": {"properties": {"timezone": {"type": "keyword"}}},
                "hostname": {"type": "keyword"},
            }
        },
        "network": {
            "properties": {
                "protocol": {"type": "keyword"},
                "transport": {"type": "keyword"},
            }
        },
        "opc": {
            "properties": {
                "device_name": {"type": "keyword"},  # name of device in OPC
                "tag": {"type": "keyword"},  # tag name
                "type": {"type": "keyword"},  # "binary"/"analog"
                "opc_type": {"type": "keyword"},  # raw data type from OPC
                "opc_name": {"type": "keyword"},
                "direction": {"type": "keyword"},  # "input"/"output"
                "raw_value": {"type": "keyword"},  # raw value as a string
                "binary_value": {"type": "boolean"},  # true/false
                "analog_value": {"type": "double"},  # float
            }
        },
    }
}

INDEX_CACHE = set()  # type: Set[str]


async def index_exists(es_obj: AsyncElasticsearch, index: str) -> bool:
    if index in INDEX_CACHE:
        return True
    elif await es_obj.indices.exists(index=index):
        INDEX_CACHE.add(index)
        return True
    return False


class SubscriptionHandler:
    def __init__(self, es_queue: asyncio.Queue) -> None:
        self.es_queue = es_queue
        self.types_cache: dict[str, str] = {}

    async def datachange_notification(
        self,
        node: Node,
        val: float,
        data: DataChangeNotif
    ) -> None:
        """
        This callback method is called for every data change notification from OPC server.
        """

        # "ChannelDnp3Rtu_11.DeviceRtu_11.BUS16_IA_analog_input_angle"
        var_id = str(node.nodeid.Identifier)
        parts = var_id.split(".")

        # Determine type of data
        # TODO: read_data_type() doesn't do what you think it does,
        # need to figure out how to get the actual Data Type from OPC.
        # data_type = self.types_cache.get(var_id)
        # if not data_type:
        #     data_type = str(await node.read_data_type())
        #     self.types_cache[var_id] = data_type

        # 2:cb_bus_power_analog_output_value
        # 2:ng8_battery_soc_analog_input_value
        # 2:ng8_ats_state_binary_output_value
        # 2:ng8_ats_state_binary_output_value_opset
        # 2:ng8_ats_state_binary_output_value_optype
        var_parts = parts[-1].split("_")

        # Skip optype, shouldn't change but just in case
        if var_parts[-1] == "optype":
            return

        # "opset" => binary write
        offset = -2
        if var_parts[-1] == "opset":
            # ng8_ats_state_binary_output_value_opset => "output"
            offset = -3

        # ng8_ats_state_binary_output_value_opset => "output"
        # ng8_ats_state_binary_output_value => "output"
        direction = var_parts[offset]  # output
        typ = var_parts[offset-1]  # binary
        tag = "_".join(var_parts[:offset-1])  # ng8_ats_state

        es_data = {
            "@timestamp": data.monitored_item.Value.ServerTimestamp,
            "opc": {
                "tag": tag,
                "type": typ,
                # "opc_type": data_type,  # TODO
                "opc_name": parts[-1],
                "direction": direction,
                "raw_value": str(val),
            },
        }

        try:
            es_data["opc"]["device_name"] = parts[1].split("Device")[-1].lower()
        except Exception:
            pass

        try:
            if typ == "binary":
                es_data["opc"]["binary_value"] = bool(val)
            elif typ == "analog":
                es_data["opc"]["analog_value"] = float(val)
        except Exception:
            pass

        # label = var_parts[0]
        # channel = var_parts[1]
        # var_type = var_parts[-1]

        # if label.startswith("PMU") and channel == "ANALOG":
        #     label = f"{var_parts[0]}_{var_parts[1]}_{var_parts[2]}"
        #     channel = label

        # # TODO: real and angle are two separate variables.... :(
        # #   can we subscribe to a chunk of variables in one callback?
        # #   or just do dumb polling?

        # # Save data to Elasticsearch
        # es_data = {
        #     "@timestamp": data.monitored_item.Value.ServerTimestamp,
        #     "pmu": {
        #         "label": label
        #     },
        #     "measurement": {
        #         "channel": channel,
        #         "phasor": {},
        #         "analog": {},
        #     },
        # }

        # if var_type == "real":
        #     es_data["measurement"]["phasor"]["real"] = val
        # elif var_type == "angle":
        #     es_data["measurement"]["phasor"]["angle"] = val
        # else:
        #     es_data["measurement"]["analog"]["value"] = val

        await self.es_queue.put(es_data)


async def setup_logging(verbose: bool = False):
    logging.root.setLevel(logging.DEBUG)

    msgfmt = "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)-16s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt=msgfmt, datefmt=datefmt)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(logging.INFO if not verbose else logging.DEBUG)
    log.addHandler(console)

    log_path = Path(Path(__file__).parent, "scada_to_elastic.log").resolve()
    previous_log_exists = log_path.exists()

    file_handler = RotatingFileHandler(
        filename=log_path.as_posix(),
        encoding="utf-8",
        maxBytes=5000000,  # 5MB for single file
        backupCount=10,  # Max number of log files to save
    )

    if previous_log_exists:
        file_handler.doRollover()

    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logging.root.addHandler(file_handler)
    log.info(f"Saving logs to {log_path}")

    # Suppress extraneous logs from Elasticsearch and urllib
    logging.getLogger("elastic_transport").setLevel(logging.WARNING)
    logging.getLogger("elasticsearch").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

    # Suppress extraneous messages from asyncua
    logging.getLogger("asyncua.client.ua_client.UaClient").setLevel(logging.INFO)
    logging.getLogger("asyncua.client.ua_client.UASocketProtocol").setLevel(logging.INFO)


async def main():
    parser = argparse.ArgumentParser(
        description="Export 'dirty' process data from a SCADA server (OPC) to an Elasticsearch server"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show DEBUG-level output on the console (stdout)"
    )
    parser.add_argument(
        "-u", "--opc-url", type=str,
        default="opc.tcp://control-scada:4840",
        help="URL of OPC server (default: 'opc.tcp://control-scada:4840')"
    )
    parser.add_argument(
        "-f", "--opc-variables", type=str,
        default="/opc_variables.json",
        help="Path to the OPC variables JSON file (default: '/opc_variables.json')"
    )
    parser.add_argument(
        "-e", "--elastic-server", type=str,
        default=None,
        help=(
            "Elasticsearch server to connect to. If unspecified, this "
            "script will attempt to read the URL from 'elastic-host' key in "
            "/power-provider_config.ini. If that file doesn't exist, then it "
            "will default to 'http://172.16.0.254:9200'."
        )
    )

    args = parser.parse_args()

    # --- Setup logging ---
    await setup_logging(verbose=args.verbose)

    # --- Set Elasticsearch URL ---
    elastic_host = args.elastic_server
    if not elastic_host:
        provider_path = Path("/power-provider_config.ini").resolve()
        if provider_path.is_file():
            log.info(f"Reading elastic-host url from provider file '{provider_path}'")
            provider = ConfigParser()
            provider.read(provider_path)
            elastic_host = provider.get("power-solver-service", "elastic-host")
        else:
            elastic_host = "http://172.16.0.254:9200"
            log.info("No provider file found, using default elastic url")
    log.info(f"Elasticsearch url: {elastic_host}")

    es_obj = AsyncElasticsearch(elastic_host)

    # Check connection to Elasticsearch
    es_info = await es_obj.info()
    if not es_info:
        log.critical("Failed to connect to Elasticsearch")
        sys.exit(1)
    log.info(f"Elasticsearch server info: {es_info}")

    # Read OPC variable names and paths to use from JSON file
    vars_file = Path(args.opc_variables).resolve()
    log.info(f"Variables file: {vars_file}")
    if not vars_file.is_file():
        log.error(f"{vars_file} does not exist")
        sys.exit(1)
    with vars_file.open("r", encoding="utf-8") as f:
        device_vars = json.load(f)  # type: Dict[str, List[str]]

    # Queue of documents to push to Elasticsearch
    es_queue = asyncio.Queue()

    # --- Create client and execute commands ---
    # NOTE: by default, timeout is 4 seconds
    async with Client(url=args.opc_url) as client:
        nodes = []
        for device, variables in device_vars.items():
            for var in variables:
                node = await client.nodes.objects.get_child([device, var])
                nodes.append(node)

        handler = SubscriptionHandler(es_queue)

        # first arg is update period, in milliseconds
        subscription = await client.create_subscription(500, handler)

        # We subscribe to data changes for two nodes (variables).
        await subscription.subscribe_data_change(nodes)

        # Only need to create this dict once
        es_additions = {
            "event": {},  # event.ingested
            "ecs": {
                "version": "8.1.0"
            },
            "agent": {
                "type": "scada-to-elastic",
                "version": __version__
            },
            "observer": {
                "hostname": platform.node(),
                "geo": {
                    "timezone": str(datetime.now(timezone.utc).astimezone().tzinfo)
                }
            },
            "network": {
                "protocol": "opc-ua",
                "transport": "tcp",
            },
        }

        # TODO:
        #   Poll for changes every 10 milliseconds. if timestamp is the same, do nothing.
        #   if timestamp incremented, then send updates to elasticsearch.

        while True:
            # This blocks until there's something in queue,
            # so no need to sleep like I do in rtds.py
            # messages = es_queue.get()
            es_data = await es_queue.get()

            ts_now = datetime.now()
            index = f"opc-dirty-{ts_now.strftime('%Y.%m.%d')}"

            # Set event.ingested to current time
            es_additions["event"]["ingested"] = ts_now

            body = {
                **es_additions,
                **es_data,
            }

            # Push pre-defined type mapping when creating index
            if not await index_exists(es_obj, index):
                create_res = await es_obj.indices.create(index=index, mappings=INDEX_TYPE_MAPPING)
                log.info(f"Created index {index} (result: {create_res})")

            # Push to Elasticsearch
            try:
                await es_obj.index(index=index, document=body)
            except Exception as ex:
                log.exception(f"Error indexing to Elastic: {ex}")
                log.error(f"Bad data: {body}")
                await es_obj.close()
                return


if __name__ == "__main__":
    asyncio.run(main())
