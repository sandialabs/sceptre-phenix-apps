package util

import (
	"phenix/types"
	ifaces "phenix/types/interfaces"
)

func ExtractVersion(md map[string]interface{}) string {
	val, ok := md["version"]
	if ok {
		version, ok := val.(string)
		if ok {
			return version
		}
	}

	return "v0"
}

func ExtractApp(scenario ifaces.ScenarioSpec, name string) ifaces.ScenarioApp {
	if scenario == nil || scenario.Apps() == nil {
		return nil
	}

	for _, app := range scenario.Apps() {
		if app.Name() == name {
			return app
		}
	}

	return nil
}

func ExtractNode(topo ifaces.TopologySpec, hostname string) ifaces.NodeSpec {
	for _, node := range topo.Nodes() {
		if node.General().Hostname() == hostname {
			return node
		}
	}

	return nil
}

func ExtractNodesTopologyType(topo ifaces.TopologySpec, types ...string) []ifaces.NodeSpec {
	var nodes []ifaces.NodeSpec

	for _, node := range topo.Nodes() {
		for _, typ := range types {
			if node.Type() == typ {
				nodes = append(nodes, node)
				break
			}
		}
	}

	return nodes
}

func ExtractNodesType(scenario ifaces.ScenarioSpec, name string, types ...string) []ifaces.ScenarioAppHost {
	app := ExtractApp(scenario, name)

	var hosts []ifaces.ScenarioAppHost

	for _, host := range app.Hosts() {
		if t, ok := host.Metadata()["type"].(string); ok {
			if StringSliceContains(types, t) {
				hosts = append(hosts, host)
			}
		}
	}

	return hosts
}

func ExtractNodesLabel(scenario ifaces.ScenarioSpec, name string, labels ...string) []ifaces.ScenarioAppHost {
	app := ExtractApp(scenario, name)

	var hosts []ifaces.ScenarioAppHost

	for _, host := range app.Hosts() {
		if l, ok := host.Metadata()["labels"].([]string); ok {
			if StringSliceContains(labels, l...) {
				hosts = append(hosts, host)
			}
		}
	}

	return hosts
}

func ExtractAssetDir(scenario ifaces.ScenarioSpec, name string) string {
	if scenario.Apps() == nil {
		return ""
	}

	for _, app := range scenario.Apps() {
		if app.Name() == name {
			return app.AssetDir()
		}
	}

	return ""
}

func IsFullyScheduled(exp types.Experiment) bool {
	schedules := exp.Spec.Schedules()

	for _, node := range exp.Spec.Topology().Nodes() {
		if _, ok := schedules[node.General().Hostname()]; !ok {
			return false
		}
	}

	return true
}

func GetAnnotation(exp types.Experiment, key string) string {
	if exp.Metadata.Annotations == nil {
		return ""
	}

	return exp.Metadata.Annotations[key]
}
