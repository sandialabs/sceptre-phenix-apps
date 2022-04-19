package main

import (
	"embed"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"math/rand"
	"net"
	"os"
	"regexp"
	"runtime/debug"
	"strconv"
	"strings"

	"phenix-apps/util"
	"phenix-apps/util/mmcli"
	"phenix/types"
	ifaces "phenix/types/interfaces"

	log "github.com/activeshadow/libminimega/minilog"
	"github.com/c-robinson/iplib"
	"github.com/hashicorp/go-multierror"
	"github.com/mitchellh/mapstructure"
)

//go:embed templates/*
var templates embed.FS

func main() {
	util.SetupLogging()

	if len(os.Args) != 2 {
		log.Fatal("incorrect amount of args provided")
	}

	stage := os.Args[1]

	if stage == "version" {
		info, ok := debug.ReadBuildInfo()
		if !ok {
			log.Fatal("unable to read build info")
		}

		var (
			rev string
			ts  string
		)

		for _, setting := range info.Settings {
			switch setting.Key {
			case "vcs.revision":
				rev = setting.Value[0:8]
			case "vcs.time":
				ts = setting.Value
			}
		}

		fmt.Printf("%s (%s)\n", rev, ts)
		return
	}

	body, err := ioutil.ReadAll(os.Stdin)
	if err != nil {
		log.Fatal("unable to read JSON from STDIN")
	}

	exp, err := util.DecodeExperiment(body)
	if err != nil {
		log.Fatal("decoding experiment: %v", err)
	}

	switch stage {
	case "configure":
		if err := configure(exp); err != nil {
			log.Fatal("failed to execute configure stage: %v", err)
		}
	case "pre-start":
		if err := preStart(exp); err != nil {
			log.Fatal("failed to execute pre-start stage: %v", err)
		}
	case "post-start":
		if err := postStart(exp); err != nil {
			log.Fatal("failed to execute post-start stage: %v", err)
		}
	case "cleanup":
		if err := cleanup(exp); err != nil {
			log.Fatal("failed to execute cleanup stage: %v", err)
		}
	default:
		fmt.Print(string(body))
		return
	}

	body, err = json.Marshal(exp)
	if err != nil {
		log.Fatal("unable to convert experiment to JSON")
	}

	fmt.Print(string(body))
}

func configure(exp *types.Experiment) error {
	var (
		app = util.ExtractApp(exp.Spec.Scenario(), "mirror")
		amd MirrorAppMetadata
	)

	if err := mapstructure.Decode(app.Metadata(), &amd); err != nil {
		return fmt.Errorf("decoding app metadata: %w", err)
	}

	if !amd.DirectGRE.Enabled {
		return nil
	}

	nw, mask, err := mirrorNet(amd)
	if err != nil {
		return fmt.Errorf("determining mirror network: %w", err)
	}

	// For configurations where multiple hosts are configured to receive mirrored
	// traffic, we'll start addressing them at the end of the network range and
	// work our way backwards, and the cluster hosts will be addressed at the
	// beginning of the network range forward.
	ip := nw.LastAddress()

	for _, host := range app.Hosts() {
		var hmd MirrorHostMetadata

		if err := mapstructure.Decode(host.Metadata(), &hmd); err != nil {
			return fmt.Errorf("decoding metadata for host %s: %w", host.Hostname(), err)
		}

		if hmd.Interface == "" {
			return fmt.Errorf("no interface specified for host %s", host.Hostname())
		}

		node := exp.Spec.Topology().FindNodeByName(host.Hostname())

		if node == nil {
			return fmt.Errorf("no host by the name of %s found in topology", host.Hostname())
		}

		var iface ifaces.NodeNetworkInterface

		for _, i := range node.Network().Interfaces() {
			if i.Name() == hmd.Interface {
				iface = i
				break
			}
		}

		// If the configured interface isn't present in the topology, create it.
		if iface == nil {
			iface = node.AddNetworkInterface("ethernet", hmd.Interface, amd.DirectGRE.MirrorVLAN)
		}

		// No matter what, set the IP for the configured interface, even if it was
		// already set in the topology.
		iface.SetBridge(amd.DirectGRE.MirrorBridge)
		iface.SetProto("static")
		iface.SetAddress(ip.String())
		iface.SetMask(mask)
		iface.SetGateway("") // just in case it was set in the topology...
		iface.SetVLAN(amd.DirectGRE.MirrorVLAN)

		// Decrement IP for next target VM.
		ip, _ = nw.PreviousIP(ip)
	}

	return nil
}

func preStart(exp *types.Experiment) error {
	var (
		app = util.ExtractApp(exp.Spec.Scenario(), "mirror")
		amd MirrorAppMetadata
	)

	if err := mapstructure.Decode(app.Metadata(), &amd); err != nil {
		return fmt.Errorf("decoding app metadata: %w", err)
	}

	if !amd.DirectGRE.Enabled {
		return nil
	}

	startupDir := exp.Spec.BaseDir() + "/startup"

	for _, host := range app.Hosts() {
		var hmd MirrorHostMetadata

		if err := mapstructure.Decode(host.Metadata(), &hmd); err != nil {
			log.Error("decoding host metadata for %s: %w", host.Hostname(), err)
			continue
		}

		if !hmd.SetupOVS {
			continue
		}

		node := exp.Spec.Topology().FindNodeByName(host.Hostname())
		if node == nil {
			log.Error("no node found in topology for %s", host.Hostname())
			continue
		}

		if strings.EqualFold(node.Hardware().OSType(), "windows") {
			log.Error("setting up OVS not currently supported on Windows (%s)", host.Hostname())
			continue
		}

		setupFile := startupDir + "/" + host.Hostname() + "-setup-ovs.sh"

		node.AddInject(
			setupFile,
			"/etc/phenix/startup/99-setup-ovs.sh",
			"0755", "",
		)

		if err := util.RestoreAsset(templates, setupFile, "templates/setup-ovs.tmpl"); err != nil {
			return fmt.Errorf("writing OVS setup script to file: %w", err)
		}
	}

	return nil
}

func postStartGRE(exp *types.Experiment) (ferr error) {
	var (
		app = util.ExtractApp(exp.Spec.Scenario(), "mirror")
		amd MirrorAppMetadata
	)

	if err := mapstructure.Decode(app.Metadata(), &amd); err != nil {
		return fmt.Errorf("decoding app metadata: %w", err)
	}

	if !amd.DirectGRE.Enabled {
		return nil
	}

	nw, mask, err := mirrorNet(amd)
	if err != nil {
		return fmt.Errorf("determining mirror network: %w", err)
	}

	cluster := cluster(exp)

	status := MirrorAppStatus{
		// Tap name is random, yet descriptive to the fact that it's a mirror tap.
		TapName: fmt.Sprintf("%s-mirror", util.RandomString(8)),
		Mirrors: make(map[string]MirrorConfig),
	}

	defer func() {
		// don't do any cleanup if no error is being returned
		if ferr == nil {
			return
		}

		// clean up any taps already created for this mirror
		deleteTap(status.TapName, cluster)

		// clean up any mirrors already created for this mirror
		for _, mirror := range status.Mirrors {
			deleteMirror(mirror.MirrorName, amd.DirectGRE.MirrorBridge, cluster)
		}
	}()

	// Cluster hosts will be addressed at the beginning of the mirror network
	// going forward (target VMs to receive mirrored data are addressed from the
	// end of the mirror network backwards).
	ip := nw.FirstAddress()

	// For each cluster host, create tap on mirror VLAN with IP in mirror network.
	// The tap's name will be something like `foobar-mirror`, assuming `foobar` is
	// the name of the experiment. The maximum length of the name is dictated by
	// the maximum length of a Linux interface name, which is 15 characters. As
	// such, the experiment name will be truncated to 8 characters before adding
	// `-mirror` to the end of it.
	for host := range cluster {
		cmd := fmt.Sprintf(
			"tap create %s//%s bridge %s ip %s/%d %s",
			exp.Spec.ExperimentName(), amd.DirectGRE.MirrorVLAN, amd.DirectGRE.MirrorBridge, ip.String(), mask, status.TapName,
		)

		if err := meshSend(host, cmd); err != nil {
			return fmt.Errorf("creating tap on cluster host %s: %w", host, err)
		}

		// Increment IP for next cluster host.
		ip, _ = nw.NextIP(ip)
	}

	// For each target VM specified in the app config, create a GRE tunnel from
	// each host to the VM (mirror network IP was configured for VM in configure
	// stage) and create a mirror on each host using the GRE tunnel as the
	// mirror's output port.
	for _, host := range app.Hosts() {
		var hmd MirrorHostMetadata

		if err := mapstructure.Decode(host.Metadata(), &hmd); err != nil {
			log.Error("decoding host metadata for %s: %w", host.Hostname(), err)
			continue
		}

		node := exp.Spec.Topology().FindNodeByName(host.Hostname())

		if node == nil {
			log.Error("no node found in topology for %s", host.Hostname())
			continue
		}

		if hmd.Interface == "" {
			log.Error("no target interface provided for %s", host.Hostname())
			continue
		}

		// Track IP to mirror packets to via GRE
		var ip net.IP

		// Get IP to mirror packets to via GRE
		for _, iface := range node.Network().Interfaces() {
			if iface.Name() == hmd.Interface {
				ip = net.ParseIP(iface.Address())
				break
			}
		}

		if ip == nil {
			log.Error("no target interface IP configured for %s", host.Hostname())
			continue
		}

		var vlans []string

		// convert VLAN aliases to IDs
		for _, vlan := range hmd.VLANs {
			id, ok := exp.Status.VLANs()[vlan]
			if ok {
				vlans = append(vlans, strconv.Itoa(id))
			}
		}

		// Limit name to 15 characters since it will be used for an OVS port name
		// (limited to 15 characters by Linux since it will be used as an interface
		// name).
		name := util.RandomString(15)

		cfg := MirrorConfig{
			MirrorName: name,
			IP:         ip.String(),
			VLANs:      vlans,
		}

		status.Mirrors[host.Hostname()] = cfg

		for h := range cluster {
			if amd.DirectGRE.ERSPAN.Enabled {
				var cmd string

				switch amd.DirectGRE.ERSPAN.Version {
				case 1:
					// Create ERSPAN v1 tunnel to target VM
					cmd = fmt.Sprintf(
						`shell ovs-vsctl add-port %s %s -- set interface %s type=erspan options:remote_ip=%s options:erspan_ver=%d options:erspan_idx=%d`,
						amd.DirectGRE.MirrorBridge, name, name, ip, amd.DirectGRE.ERSPAN.Version, amd.DirectGRE.ERSPAN.Index,
					)
				case 2:
					// Create ERSPAN v2 tunnel to target VM
					cmd = fmt.Sprintf(
						`shell ovs-vsctl add-port %s %s -- set interface %s type=erspan options:remote_ip=%s options:erspan_ver=%d options:erspan_dir=%d options:erspan_hwid=%d`,
						amd.DirectGRE.MirrorBridge, name, name, ip, amd.DirectGRE.ERSPAN.Version, amd.DirectGRE.ERSPAN.Direction, amd.DirectGRE.ERSPAN.HardwareID,
					)
				default:
					return fmt.Errorf("unknown ERSPAN version (%d) configured for %s", amd.DirectGRE.ERSPAN.Version, host.Hostname())
				}

				if err := meshSend(h, cmd); err != nil {
					return fmt.Errorf("adding ERSPAN tunnel %s from cluster host %s: %w", name, h, err)
				}
			} else {
				// Create GRE tunnel to target VM
				cmd := fmt.Sprintf(
					`shell ovs-vsctl add-port %s %s -- set interface %s type=gre options:remote_ip=%s`,
					amd.DirectGRE.MirrorBridge, name, name, ip,
				)

				if err := meshSend(h, cmd); err != nil {
					return fmt.Errorf("adding GRE tunnel %s from cluster host %s: %w", name, h, err)
				}
			}

			// list of VMs currently scheduled on this cluster host
			vms := cluster[h]

			// If more than one VLAN is being monitored, don't include router/firewall
			// interfaces in the mirror to avoid duplicate packets. By default, we
			// include routers and firewalls since doing so when monitoring a single
			// VLAN allows the capture of packets leaving the VLAN as well.
			if len(vlans) > 1 {
				// Iterate backwards so elements can be removed while iterating.
				for i := len(vms) - 1; i >= 0; i-- {
					name := vms[i]
					node := exp.Spec.Topology().FindNodeByName(name)

					// check to see if this VM is a router or firewall
					if strings.EqualFold(node.Type(), "router") || strings.EqualFold(node.Type(), "firewall") {
						// remove current VM from list of VMs
						vms = append(vms[:i], vms[i+1:]...)
					}
				}
			}

			// Create mirror, using GRE tunnel as the output port
			command := buildMirrorCommand(exp.Spec.ExperimentName(), name, amd.DirectGRE.MirrorBridge, name, vms, vlans)

			if command == nil {
				// Likely means no VMs scheduled on this cluster host have interfaces in
				// VMs being mirrored to the target VM.
				log.Info("no VMs scheduled on cluster host %s with interfaces in VLANs %v", h, hmd.VLANs)
				continue
			}

			if err := meshSend(h, strings.Join(command, " -- ")); err != nil {
				log.Error("adding ingress-only mirror %s on cluster host %s: %v", name, h, err)
				// return fmt.Errorf("adding ingress-only mirror %s on cluster host %s: %w", name, h, err)
			}
		}
	}

	exp.Status.SetAppStatus("mirror", status)

	return nil
}

func postStart(exp *types.Experiment) error {
	var (
		app = util.ExtractApp(exp.Spec.Scenario(), "mirror")
		amd MirrorAppMetadata
	)

	if err := mapstructure.Decode(app.Metadata(), &amd); err != nil {
		return fmt.Errorf("decoding app metadata: %w", err)
	}

	if amd.DirectGRE.Enabled {
		return postStartGRE(exp)
	}

	cluster := cluster(exp)

	for _, host := range app.Hosts() {
		var hmd MirrorHostMetadata

		if err := mapstructure.Decode(host.Metadata(), &hmd); err != nil {
			log.Error("decoding host metadata for %s: %w", host.Hostname(), err)
			continue
		}

		node := exp.Spec.Topology().FindNodeByName(host.Hostname())

		if node == nil {
			log.Error("no node found in topology for %s", host.Hostname())
			continue
		}

		if hmd.Interface == "" {
			log.Error("no target interface provided for %s", host.Hostname())
			continue
		}

		var (
			monitorIfaceIdx    = -1
			monitorIfaceBridge string
		)

		for i, iface := range node.Network().Interfaces() {
			if iface.Name() == hmd.Interface {
				monitorIfaceIdx = i
				monitorIfaceBridge = iface.Bridge()

				break
			}
		}

		if monitorIfaceIdx < 0 {
			log.Error("target interface not found for %s", host.Hostname())
			continue
		}

		taps := vmTaps(exp.Spec.ExperimentName(), host.Hostname())

		if len(taps) <= monitorIfaceIdx {
			log.Error("target interface not configured for %s", host.Hostname())
			continue
		}

		monitorTap := taps[monitorIfaceIdx]

		var vlans []string

		for _, vlan := range hmd.VLANs {
			id, ok := exp.Status.VLANs()[vlan]
			if ok {
				vlans = append(vlans, strconv.Itoa(id))
			}
		}

		scheduled := exp.Status.Schedules()[host.Hostname()]

		if scheduled == "" {
			log.Error("%s is not scheduled in the experiment", host.Hostname())
			continue
		}

		ips, _ := net.LookupIP(scheduled)

		if len(ips) < 1 {
			return fmt.Errorf("cannot determine IP for cluster host %s", scheduled)
		}

		var (
			remote = ips[0].String()
			key    = rand.Uint32()
		)

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

func cleanupGRE(exp *types.Experiment) error {
	var (
		app = util.ExtractApp(exp.Spec.Scenario(), "mirror")
		amd MirrorAppMetadata
	)

	if err := mapstructure.Decode(app.Metadata(), &amd); err != nil {
		return fmt.Errorf("decoding app metadata: %w", err)
	}

	if !amd.DirectGRE.Enabled {
		return nil
	}

	cluster := cluster(exp)

	var status MirrorAppStatus

	if app, ok := exp.Status.AppStatus()["mirror"]; ok {
		if err := mapstructure.Decode(app, &status); err != nil {
			return fmt.Errorf("decoding app status: %w", err)
		}
	}

	for _, host := range app.Hosts() {
		cfg, ok := status.Mirrors[host.Hostname()]
		if !ok {
			log.Error("missing mirror config for %s in experiment status", host.Hostname())
			continue
		}

		name := cfg.MirrorName

		if err := deleteMirror(name, amd.DirectGRE.MirrorBridge, cluster); err != nil {
			log.Error("removing mirror %s from cluster: %v", name, err)
		}
	}

	if err := deleteTap(status.TapName, cluster); err != nil {
		log.Error("removing tap %s from cluster: %v", status.TapName, err)
	}

	return nil
}

func cleanup(exp *types.Experiment) error {
	var (
		app = util.ExtractApp(exp.Spec.Scenario(), "mirror")
		amd MirrorAppMetadata
	)

	if err := mapstructure.Decode(app.Metadata(), &amd); err != nil {
		return fmt.Errorf("decoding app metadata: %w", err)
	}

	if amd.DirectGRE.Enabled {
		return cleanupGRE(exp)
	}

	cluster := cluster(exp)

	for _, host := range app.Hosts() {
		var hmd MirrorHostMetadata

		if err := mapstructure.Decode(host.Metadata(), &hmd); err != nil {
			log.Error("decoding host metadata for %s: %w", host.Hostname(), err)
			continue
		}

		node := exp.Spec.Topology().FindNodeByName(host.Hostname())

		if node == nil {
			log.Error("no node found in topology for %s", host.Hostname())
			continue
		}

		if hmd.Interface == "" {
			log.Error("no target interface provided for %s", host.Hostname())
			continue
		}

		var monitorIfaceBridge string

		for _, iface := range node.Network().Interfaces() {
			if iface.Name() == hmd.Interface {
				monitorIfaceBridge = iface.Bridge()
				break
			}
		}

		if monitorIfaceBridge == "" {
			log.Error("target interface not found for %s", host.Hostname())
			continue
		}

		cmd := fmt.Sprintf(
			`shell ovs-vsctl -- --id=@m get mirror %s -- remove bridge %s mirrors @m`,
			host.Hostname(), monitorIfaceBridge,
		)

		if err := meshSend("all", cmd); err != nil {
			log.Error("removing mirror %s on all cluster hosts: %v", host.Hostname(), err)
		}

		// We only need to worry about GRE tunnels if more than one cluster host is
		// involved in this experiment.
		if len(cluster) > 1 {
			scheduled := exp.Status.Schedules()[host.Hostname()]

			cmd = fmt.Sprintf(`shell ovs-ofctl del-flows %s in_port=%s`, monitorIfaceBridge, host.Hostname())

			if err := meshSend(scheduled, cmd); err != nil {
				log.Error("deleting OpenFlow flow rule for %s on cluster host %s: %v", host.Hostname(), scheduled, err)
			}

			cmd = fmt.Sprintf(`shell ovs-vsctl del-port %s %s`, monitorIfaceBridge, host.Hostname())

			if err := meshSend("all", cmd); err != nil {
				log.Error("deleting GRE tunnel %s on all cluster hosts: %v", host.Hostname(), err)
			}
		}
	}

	return nil
}

func mirrorNet(md MirrorAppMetadata) (iplib.Net, int, error) {
	var nw iplib.Net

	// Set some default values if missing from metadata.
	if md.DirectGRE.MirrorNet == "" {
		md.DirectGRE.MirrorNet = "172.30.0.0/16"
	}

	if md.DirectGRE.MirrorBridge == "" {
		md.DirectGRE.MirrorBridge = "phenix"
	}

	if md.DirectGRE.MirrorVLAN == "" {
		md.DirectGRE.MirrorVLAN = "mirror"
	}

	tokens := strings.Split(md.DirectGRE.MirrorNet, "/")

	var (
		ip   = net.ParseIP(tokens[0])
		mask = 16 // default mirror network mask if missing from metadata
	)

	if ip == nil {
		return nw, 0, fmt.Errorf("invalid network address provided for mirror network: %s", tokens[0])
	}

	if len(tokens) == 2 {
		var err error

		if mask, err = strconv.Atoi(tokens[1]); err != nil {
			return nw, 0, fmt.Errorf("invalid network mask provided for mirror network: %s", tokens[1])
		}
	}

	nw = iplib.NewNet(ip, mask)

	return nw, mask, nil
}

// Returns a map of cluster hosts, each referencing a slice of names of VMs
// scheduled on the host.
func cluster(exp *types.Experiment) map[string][]string {
	cluster := make(map[string][]string)

	for vm, host := range exp.Status.Schedules() {
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

		for idx, alias := range vmVLANs {
			// assume by default that `alias` is the actual VLAN ID
			vlanID := alias

			// check to see if `alias` is indeed a VLAN alias (e.g., EXP_1 (101), EXP_2 (102))
			if match := vlanAliasRegex.FindStringSubmatch(alias); match != nil {
				// `match` will be a slice of regex matches (e.g., EXP_1 (101), EXP_1, 101)
				vlanID = match[2]
			}

			// `vlans` will be a slice of VLAN IDs (e.g., 101, 102)
			for _, id := range vlans {
				if id == vlanID {
					taps = append(taps, vmTaps[idx])
					break
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

	if len(taps) == 0 {
		return nil
	}

	for idx, tap := range taps {
		id := fmt.Sprintf("@i%d", idx)

		ids = append(ids, id)
		command = append(command, fmt.Sprintf(`--id=%s get port %s`, id, tap))
	}

	command = append(command, fmt.Sprintf(`--id=@o get port %s`, port))
	command = append(command, fmt.Sprintf(`--id=@m create mirror name=%s select-dst-port=%s select-vlan=%s output-port=@o`, name, strings.Join(ids, ","), strings.Join(vlans, ",")))
	command = append(command, fmt.Sprintf(`add bridge %s mirrors @m`, bridge))

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

func deleteTap(tap string, cluster map[string][]string) error {
	var err error

	for host := range cluster {
		multierror.Append(err, deleteTapFromHost(tap, host))
	}

	return err
}

func deleteTapFromHost(tap, host string) error {
	cmd := fmt.Sprintf("tap delete %s", tap)

	if err := meshSend(host, cmd); err != nil {
		return fmt.Errorf("deleting tap %s on cluster host %s: %w", tap, host, err)
	}

	return nil
}

func deleteMirror(mirror, bridge string, cluster map[string][]string) error {
	var err error

	for host := range cluster {
		multierror.Append(err, deleteMirrorFromHost(mirror, bridge, host))
	}

	return err
}

func deleteMirrorFromHost(mirror, bridge, host string) error {
	var err error

	cmd := fmt.Sprintf(
		`shell ovs-vsctl -- --id=@m get mirror %s -- remove bridge %s mirrors @m`,
		mirror, bridge,
	)

	if err := meshSend(host, cmd); err != nil {
		multierror.Append(err, fmt.Errorf("removing mirror %s from bridge %s on cluster host %s: %v", mirror, bridge, host, err))
	}

	cmd = fmt.Sprintf(`shell ovs-vsctl del-port %s %s`, bridge, mirror)

	if err := meshSend(host, cmd); err != nil {
		multierror.Append(fmt.Errorf("deleting GRE tunnel %s from bridge %s on cluster host %s: %v", mirror, bridge, host, err))
	}

	return err
}
