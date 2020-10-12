package main

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"math/rand"
	"net"
	"os"
	"regexp"
	"strconv"
	"strings"

	"phenix-apps/util"
	"phenix-apps/util/mmcli"
	"phenix/types"

	"github.com/mitchellh/mapstructure"
)

type MirrorMetadata struct {
	Interface string   `mapstructure:"interface"`
	VLANs     []string `mapstructure:"vlans"`
}

func main() {
	if len(os.Args) != 2 {
		log.Fatal("incorrect amount of args provided")
	}

	body, err := ioutil.ReadAll(os.Stdin)
	if err != nil {
		log.Fatal("unable to read JSON from STDIN")
	}

	stage := os.Args[1]

	if stage != "post-start" && stage != "cleanup" {
		fmt.Print(string(body))
		return
	}

	exp, err := util.DecodeExperiment(body)
	if err != nil {
		log.Fatalf("decoding experiment: %v", err)
	}

	switch stage {
	case "post-start":
		if err := postStart(exp); err != nil {
			log.Fatalf("failed to execute post-start stage: %v", err)
		}
	case "cleanup":
		if err := cleanup(exp); err != nil {
			log.Fatalf("failed to execute cleanup stage: %v", err)
		}
	}

	body, err = json.Marshal(exp)
	if err != nil {
		log.Fatal("unable to convert experiment to JSON")
	}

	fmt.Print(string(body))
}

func postStart(exp *types.Experiment) error {
	app := util.ExtractApp(exp.Spec.Scenario(), "mirror")

	if app == nil {
		// TODO: yell loudly
		return nil
	}

	cluster := cluster(exp)

	var md MirrorMetadata

	for _, host := range app.Hosts() {
		if err := mapstructure.Decode(host.Metadata(), &md); err != nil {
			// TODO: yell loudly
			continue
		}

		node := exp.Spec.Topology().FindNodeByName(host.Hostname())

		if node == nil {
			// TODO: yell loudly
			continue
		}

		if md.Interface == "" {
			// TODO: yell loudly
			continue
		}

		monitorIfaceIdx := -1
		var monitorIfaceBridge string

		for i, iface := range node.Network().Interfaces() {
			if iface.Name() == md.Interface {
				monitorIfaceIdx = i
				monitorIfaceBridge = iface.Bridge()

				break
			}
		}

		if monitorIfaceIdx < 0 {
			// TODO: yell loudly
			continue
		}

		taps := vmTaps(exp.Spec.ExperimentName(), host.Hostname())

		if len(taps) <= monitorIfaceIdx {
			// TODO: yell loudly
			continue
		}

		monitorTap := taps[monitorIfaceIdx]

		var vlans []string

		for _, vlan := range md.VLANs {
			id, ok := exp.Status.VLANs()[vlan]
			if ok {
				vlans = append(vlans, strconv.Itoa(id))
			}
		}

		scheduled := exp.Status.Schedules()[host.Hostname()]

		if scheduled == "" {
			// TODO: yell loudly
			continue
		}

		ips, _ := net.LookupIP(scheduled)

		if len(ips) < 1 {
			// TODO: yell loudly
			continue
		}

		remote := ips[0].String()

		if len(cluster) == 0 {
			// TODO: yell loudly
			continue
		}

		if _, ok := cluster[scheduled]; !ok {
			// TODO: yell loudly
			continue
		}

		key := rand.Uint32()

		// We only need to worry about GRE tunnels if more than one cluster host is
		// involved in this experiment.
		if len(cluster) > 1 {
			cmd := fmt.Sprintf(`shell ovs-vsctl set bridge %s rstp-enable=true`, monitorIfaceBridge)

			if err := meshSend(scheduled, cmd); err != nil {
				return fmt.Errorf("enabling RSTP for bridge on cluster host %s: %w", scheduled, err)
			}

			cmd = fmt.Sprintf(
				`shell ovs-vsctl add-port %s %s -- set interface %s type=gre options:remote_ip=flow options:key=%v`,
				monitorIfaceBridge, host.Hostname(), host.Hostname(), key,
			)

			if err := meshSend(scheduled, cmd); err != nil {
				return fmt.Errorf("adding GRE flow tunnel %s on cluster host %s: %w", host.Hostname(), scheduled, err)
			}

			cmd = fmt.Sprintf(
				`shell ovs-ofctl add-flow %s "in_port=%s actions=output:%s"`,
				monitorIfaceBridge, host.Hostname(), monitorTap,
			)

			if err := meshSend(scheduled, cmd); err != nil {
				return fmt.Errorf("adding OpenFlow flow rule for %s on cluster host %s: %w", host.Hostname(), scheduled, err)
			}

			for h := range cluster {
				if h == scheduled {
					continue
				}

				cmd := fmt.Sprintf(`shell ovs-vsctl set bridge %s rstp-enable=true`, monitorIfaceBridge)

				if err := meshSend(h, cmd); err != nil {
					return fmt.Errorf("enabling RSTP for bridge on cluster host %s: %w", h, err)
				}

				cmd = fmt.Sprintf(
					`shell ovs-vsctl add-port %s %s -- set interface %s type=gre options:remote_ip=%s options:key=%v`,
					monitorIfaceBridge, host.Hostname(), host.Hostname(), remote, key,
				)

				if err := meshSend(h, cmd); err != nil {
					return fmt.Errorf("adding GRE tunnel %s from cluster host %s: %w", host.Hostname(), h, err)
				}

				command := buildMirrorCommand(exp.Spec.ExperimentName(), host.Hostname(), monitorIfaceBridge, host.Hostname(), cluster[h], vlans)

				if err := meshSend(h, strings.Join(command, " -- ")); err != nil {
					return fmt.Errorf("adding ingress-only mirror %s on cluster host %s: %w", host.Hostname(), h, err)
				}
			}
		}

		command := buildMirrorCommand(exp.Spec.ExperimentName(), host.Hostname(), monitorIfaceBridge, monitorTap, cluster[scheduled], vlans)

		if err := meshSend(scheduled, strings.Join(command, " -- ")); err != nil {
			return fmt.Errorf("adding ingress-only mirror %s on cluster host %s: %w", host.Hostname(), scheduled, err)
		}
	}

	return nil
}

func cleanup(exp *types.Experiment) error {
	app := util.ExtractApp(exp.Spec.Scenario(), "mirror")

	if app == nil {
		// TODO: yell loudly
		return nil
	}

	cluster := cluster(exp)

	var md MirrorMetadata

	for _, host := range app.Hosts() {
		if err := mapstructure.Decode(host.Metadata(), &md); err != nil {
			// TODO: yell loudly
			continue
		}

		node := exp.Spec.Topology().FindNodeByName(host.Hostname())

		if node == nil {
			// TODO: yell loudly
			continue
		}

		if md.Interface == "" {
			// TODO: yell loudly
			continue
		}

		var monitorIfaceBridge string

		for _, iface := range node.Network().Interfaces() {
			if iface.Name() == md.Interface {
				monitorIfaceBridge = iface.Bridge()
				break
			}
		}

		if monitorIfaceBridge == "" {
			// TODO: yell loudly
			continue
		}

		cmd := fmt.Sprintf(
			`shell ovs-vsctl -- --id=@m get mirror %s -- remove bridge %s mirrors @m`,
			host.Hostname(), monitorIfaceBridge,
		)

		if err := meshSend("all", cmd); err != nil {
			log.Printf("removing mirror %s on all cluster hosts: %v", host.Hostname(), err)
		}

		// We only need to worry about GRE tunnels if more than one cluster host is
		// involved in this experiment.
		if len(cluster) > 1 {
			scheduled := exp.Status.Schedules()[host.Hostname()]

			cmd = fmt.Sprintf(`shell ovs-ofctl del-flows %s in_port=%s`, monitorIfaceBridge, host.Hostname())

			if err := meshSend(scheduled, cmd); err != nil {
				log.Printf("deleting OpenFlow flow rule for %s on cluster host %s: %v", host.Hostname(), scheduled, err)
			}

			cmd = fmt.Sprintf(`shell ovs-vsctl del-port %s %s`, monitorIfaceBridge, host.Hostname())

			if err := meshSend("all", cmd); err != nil {
				log.Printf("deleting GRE tunnel %s on all cluster hosts: %v", host.Hostname(), err)
			}
		}
	}

	return nil
}

func cluster(exp *types.Experiment) map[string][]string {
	cluster := make(map[string][]string)

	for vm, host := range exp.Status.Schedules() {
		node := exp.Spec.Topology().FindNodeByName(vm)

		// We don't want to mirror router/firewall interfaces in an effort to avoid
		// duplicate packets.
		if node == nil || strings.EqualFold(node.Type(), "Router") || strings.EqualFold(node.Type(), "Firewall") {
			continue
		}

		cluster[host] = append(cluster[host], vm)
	}

	return cluster
}

func vmTaps(ns, vm string) []string {
	cmd := mmcli.NewCommand(mmcli.Namespace(ns))
	cmd.Command = "vm info"
	cmd.Filters = []string{"name=" + vm}

	rows := mmcli.RunTabular(cmd)

	if len(rows) == 0 {
		return nil
	}

	taps := rows[0]["tap"]

	taps = strings.TrimPrefix(taps, "[")
	taps = strings.TrimSuffix(taps, "]")
	taps = strings.TrimSpace(taps)

	if taps != "" {
		return strings.Split(taps, ", ")
	}

	return nil
}

func vlanTaps(ns string, vms, vlans []string) []string {
	var (
		vmSet = make(map[string]struct{})
		taps  []string
	)

	for _, vm := range vms {
		vmSet[vm] = struct{}{}
	}

	var vlanAliasRegex = regexp.MustCompile(`(.*) \((\d*)\)`)

	cmd := mmcli.NewCommand(mmcli.Namespace(ns))
	cmd.Command = "vm info"

	for _, row := range mmcli.RunTabular(cmd) {
		vm := row["name"]

		if _, ok := vmSet[vm]; !ok {
			continue
		}

		s := row["vlan"]

		s = strings.TrimPrefix(s, "[")
		s = strings.TrimSuffix(s, "]")
		s = strings.TrimSpace(s)

		var vmVLANs []string

		if s != "" {
			vmVLANs = strings.Split(s, ", ")
		}

		s = row["tap"]

		s = strings.TrimPrefix(s, "[")
		s = strings.TrimSuffix(s, "]")
		s = strings.TrimSpace(s)

		var vmTaps []string

		if s != "" {
			vmTaps = strings.Split(s, ", ")
		}

		// `vmVLANs` will be a slice of VLAN aliases (ie. EXP_1 (101), EXP_2 (102))
		for idx, alias := range vmVLANs {
			if match := vlanAliasRegex.FindStringSubmatch(alias); match != nil {
				// `vlans` will be a slice of VLAN IDs (ie. 101, 102)
				for _, id := range vlans {
					if match[2] == id {
						taps = append(taps, vmTaps[idx])
						break
					}
				}
			}
		}
	}

	return taps
}

func buildMirrorCommand(ns, name, bridge, port string, vms, vlans []string) []string {
	var (
		ids     []string
		command = []string{"shell ovs-vsctl"}
	)

	taps := vlanTaps(ns, vms, vlans)

	for idx, tap := range taps {
		id := fmt.Sprintf("@i%d", idx)

		ids = append(ids, id)
		command = append(command, fmt.Sprintf(`--id=%s get port %s`, id, tap))
	}

	command = append(command, fmt.Sprintf(`--id=@o get port %s`, port))
	command = append(command, fmt.Sprintf(`--id=@m create mirror name=%s select-dst-port=%s select-vlan=%s output-port=@o`, name, strings.Join(ids, ","), strings.Join(vlans, ",")))
	command = append(command, fmt.Sprintf(`set bridge %s mirrors=@m`, bridge))

	return command
}

func meshSend(host, command string) error {
	cmd := mmcli.NewCommand()

	if util.IsHeadnode(host) {
		cmd.Command = command
	} else {
		cmd.Command = fmt.Sprintf("mesh send %s %s", host, command)
	}

	if err := mmcli.ErrorResponse(mmcli.Run(cmd)); err != nil {
		return fmt.Errorf("executing mesh send (%s): %w", cmd.Command, err)
	}

	return nil
}
