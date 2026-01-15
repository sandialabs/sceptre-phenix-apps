import lxml.etree as ET


class Config:
    def __init__(self, md={}):
        if "message-bus" in md:
            self.default_pull = md["message-bus"].get(
                "pull-endpoint", "tcp://127.0.0.1:1234"
            )
            self.default_pub = md["message-bus"].get(
                "pub-endpoint", "tcp://127.0.0.1:5678"
            )
        else:
            self.default_pull = "tcp://127.0.0.1:1234"
            self.default_pub = "tcp://127.0.0.1:5678"

        self.default_api = {}

        if "cpu-module" in md:
            if "api" in md["cpu-module"]:
                self.default_api["endpoint"] = md["cpu-module"]["api"].get(
                    "endpoint", "0.0.0.0:9101"
                )
                self.default_api["tls-key"] = md["cpu-module"]["api"].get("tls-key")
                self.default_api["tls-cert"] = md["cpu-module"]["api"].get(
                    "tls-certificate"
                )
                self.default_api["ca-cert"] = md["cpu-module"]["api"].get(
                    "ca-certificate"
                )
            else:
                endpoint = md["cpu-module"].get("api-endpoint", "0.0.0.0:9101")

                if endpoint:
                    self.default_api["endpoint"] = endpoint
                else:  # allow disablement of API endpoint if `api-endpoint` is null
                    self.default_api = None
        else:
            self.default_api["endpoint"] = "0.0.0.0:9101"

        if "logs" in md:
            self.logs = {}

            if "elastic" in md["logs"]:
                if "endpoint" in md["logs"]["elastic"]:
                    self.logs["elastic"] = {
                        "default_endpoint": md["logs"]["elastic"].get(
                            "endpoint", "http://localhost:9200"
                        ),
                        "default_index": md["logs"]["elastic"].get(
                            "index", "ot-sim-logs"
                        ),
                    }
            elif "loki" in md["logs"]:
                self.logs["loki"] = {"default_endpoint": md["logs"]["loki"]}
            else:
                self.logs = None
        else:
            self.logs = None

        if "ground-truth-module" in md:
            self.ground_truth = {}

            if "elastic" in md["ground-truth-module"]:
                self.ground_truth["elastic"] = {
                    "default_endpoint": md["ground-truth-module"]["elastic"].get(
                        "endpoint", "http://localhost:9200"
                    ),
                    "default_index_base_name": md["ground-truth-module"]["elastic"].get(
                        "index-base-name", "ot-sim"
                    ),
                }
            else:
                self.ground_truth = None
        else:
            self.ground_truth = None

    def init_xml_root(self, md={}):
        self.root = ET.Element("ot-sim")

        injects = []

        msgbus = ET.SubElement(self.root, "message-bus")
        pull = ET.SubElement(msgbus, "pull-endpoint")
        pub = ET.SubElement(msgbus, "pub-endpoint")

        if "message-bus" in md:
            pull.text = md["message-bus"].get("pull-endpoint", self.default_pull)
            pub.text = md["message-bus"].get("pub-endpoint", self.default_pub)
        else:
            pull.text = self.default_pull
            pub.text = self.default_pub

        self.cpu = ET.SubElement(self.root, "cpu")

        if "cpu-module" in md:
            if "api" in md["cpu-module"]:
                api = ET.SubElement(self.cpu, "api")

                endpoint = ET.SubElement(api, "endpoint")
                endpoint.text = md["cpu-module"]["api"].get(
                    "endpoint", self.default_api["endpoint"]
                )

                if (
                    "tls-key" in md["cpu-module"]["api"]
                    and "tls-certificate" in md["cpu-module"]["api"]
                ):
                    tlskey = ET.SubElement(api, "tls-key")
                    tlskey.text = "/etc/ot-sim/certs/api.key"

                    injects.append(
                        {
                            "src": md["cpu-module"]["api"]["tls-key"],
                            "dst": "/etc/ot-sim/certs/api.key",
                        }
                    )

                    tlscert = ET.SubElement(api, "tls-certificate")
                    tlscert.text = "/etc/ot-sim/certs/api.crt"

                    injects.append(
                        {
                            "src": md["cpu-module"]["api"]["tls-certificate"],
                            "dst": "/etc/ot-sim/certs/api.crt",
                        }
                    )

                if "ca-certificate" in md["cpu-module"]["api"]:
                    cacert = ET.SubElement(api, "ca-certificate")
                    cacert.text = "/etc/ot-sim/certs/api.ca.crt"

                    injects.append(
                        {
                            "src": md["cpu-module"]["api"]["ca-certificate"],
                            "dst": "/etc/ot-sim/certs/api.ca.crt",
                        }
                    )
            else:
                endpoint = md["cpu-module"].get(
                    "api-endpoint", self.default_api["endpoint"]
                )

                if (
                    endpoint
                ):  # allow disablement of API endpoint if `api-endpoint` is null
                    api = ET.SubElement(self.cpu, "api")

                    apiendpoint = ET.SubElement(api, "endpoint")
                    apiendpoint.text = endpoint
        elif self.default_api:
            api = ET.SubElement(self.cpu, "api")

            apiendpoint = ET.SubElement(api, "endpoint")
            apiendpoint.text = self.default_api["endpoint"]

            if "tls-key" in self.default_api and "tls-cert" in self.default_api:
                tlskey = ET.SubElement(api, "tls-key")
                tlskey.text = "/etc/ot-sim/certs/api.key"

                injects.append(
                    {
                        "src": self.default_api["tls-key"],
                        "dst": "/etc/ot-sim/certs/api.key",
                    }
                )

                tlscert = ET.SubElement(api, "tls-certificate")
                tlscert.text = "/etc/ot-sim/certs/api.crt"

                injects.append(
                    {
                        "src": self.default_api["tls-cert"],
                        "dst": "/etc/ot-sim/certs/api.crt",
                    }
                )

            if "ca-cert" in self.default_api:
                cacert = ET.SubElement(api, "ca-certificate")
                cacert.text = "/etc/ot-sim/certs/api.ca.crt"

                injects.append(
                    {
                        "src": self.default_api["ca-cert"],
                        "dst": "/etc/ot-sim/certs/api.ca.crt",
                    }
                )

        if "logs" in md:
            if "elastic" in md["logs"]:
                if "endpoint" in md["logs"]["elastic"]:
                    index = md["logs"]["elastic"].get("index")

                    if not index:
                        try:
                            index = self.logs["elastic"]["default_index"]
                        except:
                            index = None

                    logs = ET.SubElement(self.cpu, "logs")

                    if index:
                        es = ET.SubElement(logs, "elastic", {"index": index})
                    else:
                        es = ET.SubElement(logs, "elastic")

                    es.text = md["logs"]["elastic"]["endpoint"]
            elif self.logs and "elastic" in self.logs:
                es = ET.SubElement(
                    logs, "elastic", {"index": self.logs["elastic"]["default_index"]}
                )
                es.text = self.logs["elastic"]["default_endpoint"]

            if "loki" in md["logs"]:
                logs = ET.SubElement(self.cpu, "logs")
                loki = ET.SubElement(logs, "loki")

                loki.text = md["logs"]["loki"]
            elif self.logs and "loki" in self.logs:
                loki = ET.SubElement(logs, "loki")
                loki.text = self.logs["loki"]["default_endpoint"]
        elif self.logs:
            logs = ET.SubElement(self.cpu, "logs")

            if "elastic" in self.logs:
                es = ET.SubElement(
                    logs, "elastic", {"index": self.logs["elastic"]["default_index"]}
                )
                es.text = self.logs["elastic"]["default_endpoint"]

            if "loki" in self.logs:
                loki = ET.SubElement(logs, "loki")
                loki.text = self.logs["loki"]["default_endpoint"]

        backplane = ET.SubElement(self.cpu, "module", {"name": "backplane"})
        backplane.text = "ot-sim-message-bus {{config_file}}"

        # Might be null in config, which means disable it for this particular device
        # even though it's enabled globally.
        if (
            "ground-truth-module" in md
            and md["ground-truth-module"]
            and "elastic" in md["ground-truth-module"]
        ):
            gt = ET.SubElement(self.root, "ground-truth")
            es = ET.SubElement(gt, "elastic")
            ep = ET.SubElement(es, "endpoint")
            idx = ET.SubElement(es, "index-base-name")

            ep.text = md["ground-truth-module"]["elastic"].get(
                "endpoint", self.ground_truth["elastic"]["default_endpoint"]
            )
            idx.text = md["ground-truth-module"]["elastic"].get(
                "index-base-name",
                self.ground_truth["elastic"]["default_index_base_name"],
            )

            for name, value in (
                md["ground-truth-module"]["elastic"].get("labels", {}).items()
            ):
                ET.SubElement(es, "label", {"name": name}).text = value

            ET.SubElement(
                self.cpu, "module", {"name": "ground-truth"}
            ).text = "ot-sim-ground-truth-module {{config_file}}"
        elif self.ground_truth and "elastic" in self.ground_truth:
            gt = ET.SubElement(self.root, "ground-truth")
            es = ET.SubElement(gt, "elastic")
            ep = ET.SubElement(es, "endpoint")
            idx = ET.SubElement(es, "index-base-name")

            ep.text = self.ground_truth["elastic"]["default_endpoint"]
            idx.text = self.ground_truth["elastic"]["default_index_base_name"]

            ET.SubElement(
                self.cpu, "module", {"name": "ground-truth"}
            ).text = "ot-sim-ground-truth-module {{config_file}}"

        return injects

    def append_to_root(self, child):
        self.root.append(child)

    def append_to_cpu(self, child):
        self.cpu.append(child)

    def to_file(self, path):
        with open(path, "w") as f:
            f.write(ET.tostring(self.root, pretty_print=True).decode())
