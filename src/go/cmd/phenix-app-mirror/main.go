package main

import (
	"embed"
	"encoding/json"
	"fmt"
	"io/ioutil"
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
	app := util.ExtractApp(exp.Spec.Scenario(), "mirror")

	amd, err := extractMetadata(app.Metadata())
	if err != nil {
		return fmt.Errorf("extracting app metadata: %w", err)
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
		hmd, err := extractHostMetadata(host.Metadata())
		if err != nil {
			return fmt.Errorf("extracting host metadata for %s: %w", host.Hostname(), err)
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
			iface = node.AddNetworkInterface("ethernet", hmd.Interface, amd.MirrorVLAN)
		}

		// No matter what, set the IP for the configured interface, even if it was
		// already set in the topology.
		iface.SetBridge(amd.MirrorBridge)
		iface.SetProto("static")
		iface.SetAddress(ip.String())
		iface.SetMask(mask)
		iface.SetGateway("") // just in case it was set in the topology...
		iface.SetVLAN(amd.MirrorVLAN)

		// Decrement IP for next target VM.
		ip, _ = nw.PreviousIP(ip)
	}

	return nil
}

func preStart(exp *types.Experiment) error {
	app := util.ExtractApp(exp.Spec.Scenario(), "mirror")
	startupDir := exp.Spec.BaseDir() + "/startup"

	for _, host := range app.Hosts() {
		hmd, err := extractHostMetadata(host.Metadata())
		if err != nil {
			return fmt.Errorf("extracting host metadata for %s: %w", host.Hostname(), err)
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

func postStart(exp *types.Experiment) (ferr error) {
	app := util.ExtractApp(exp.Spec.Scenario(), "mirror")

	amd, err := extractMetadata(app.Metadata())
	if err != nil {
		return fmt.Errorf("extracting app metadata: %w", err)
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
			deleteMirror(mirror.MirrorName, amd.MirrorBridge, cluster)
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
		log.Info("creating mirror tap %s on host %s", status.TapName, host)

		cmd := fmt.Sprintf(
			"tap create %s//%s bridge %s ip %s/%d %s",
			exp.Spec.ExperimentName(), amd.MirrorVLAN, amd.MirrorBridge, ip.String(), mask, status.TapName,
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
		hmd, err := extractHostMetadata(host.Metadata())
		if err != nil {
			return fmt.Errorf("extracting host metadata for %s: %w", host.Hostname(), err)
		}

		log.Info("setting up mirror to %s (VLANs: %d, MirrorRouted: %t)", host.Hostname(), len(hmd.VLANs), hmd.MirrorRouted)

		node := exp.Spec.Topology().FindNodeByName(host.Hostname())

		if node == nil {
			log.Warn("no node found in topology for %s", host.Hostname())
			continue
		}

		if hmd.Interface == "" {
			log.Warn("no target interface provided for %s", host.Hostname())
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
			log.Warn("no target interface IP configured for %s", host.Hostname())
			continue
		}

		// Limit name to 15 characters since it will be used for an OVS port name
		// (limited to 15 characters by Linux since it will be used as an interface
		// name).
		name := util.RandomString(15)

		cfg := MirrorConfig{MirrorName: name, IP: ip.String()}

		status.Mirrors[host.Hostname()] = cfg

		for h := range cluster {
			if amd.ERSPAN.Enabled {
				var cmd string

				switch amd.ERSPAN.Version {
				case 1:
					// Create ERSPAN v1 tunnel to target VM
					cmd = fmt.Sprintf(
						`shell ovs-vsctl add-port %s %s -- set interface %s type=erspan options:remote_ip=%s options:erspan_ver=%d options:erspan_idx=%d`,
						amd.MirrorBridge, name, name, ip, amd.ERSPAN.Version, amd.ERSPAN.Index,
					)
				case 2:
					// Create ERSPAN v2 tunnel to target VM
					cmd = fmt.Sprintf(
						`shell ovs-vsctl add-port %s %s -- set interface %s type=erspan options:remote_ip=%s options:erspan_ver=%d options:erspan_dir=%d options:erspan_hwid=%d`,
						amd.MirrorBridge, name, name, ip, amd.ERSPAN.Version, amd.ERSPAN.Direction, amd.ERSPAN.HardwareID,
					)
				default:
					return fmt.Errorf("unknown ERSPAN version (%d) configured for %s", amd.ERSPAN.Version, host.Hostname())
				}

				if err := meshSend(h, cmd); err != nil {
					return fmt.Errorf("adding ERSPAN tunnel %s from cluster host %s: %w", name, h, err)
				}
			} else {
				log.Info("creating GRE port %s to %s on host %s", name, host.Hostname(), h)

				// Create GRE tunnel to target VM
				cmd := fmt.Sprintf(
					`shell ovs-vsctl add-port %s %s -- set interface %s type=gre options:remote_ip=%s`,
					amd.MirrorBridge, name, name, ip,
				)

				if err := meshSend(h, cmd); err != nil {
					return fmt.Errorf("adding GRE tunnel %s from cluster host %s: %w", name, h, err)
				}
			}

			// list of VMs currently scheduled on this cluster host
			// (we make a copy since we potentially modify it below)
			vms := make([]string, len(cluster[h]))
			copy(vms, cluster[h])

			// If more than one VLAN is being monitored, don't include router/firewall
			// interfaces in the mirror to avoid duplicate packets. By default, we
			// include routers and firewalls since doing so when monitoring a single
			// VLAN allows the capture of packets leaving the VLAN as well.
			if len(hmd.VLANs) > 1 && !hmd.MirrorRouted {
				// Iterate backwards so elements can be removed while iterating.
				for i := len(vms) - 1; i >= 0; i-- {
					name := vms[i]
					node := exp.Spec.Topology().FindNodeByName(name)

					// check to see if this VM is a router or firewall
					if strings.EqualFold(node.Type(), "router") || strings.EqualFold(node.Type(), "firewall") {
						log.Debug(
							"removing VM %s (%s) from list of VMs to mirror to %s (VLANs: %d, MirrorRouted: %t)",
							name, node.Type(), host, len(hmd.VLANs), hmd.MirrorRouted,
						)

						// remove current VM from list of VMs
						vms = append(vms[:i], vms[i+1:]...)
					}
				}
			}

			// Create mirror, using GRE tunnel as the output port
			command := buildMirrorCommand(exp, name, amd.MirrorBridge, name, vms, hmd)

			if command == nil {
				// Likely means no VMs scheduled on this cluster host have interfaces in
				// VLANs being mirrored to the target VM.
				continue
			}

			log.Info("creating mirror %s for %s on host %s", name, host.Hostname(), h)

			if err := meshSend(h, strings.Join(command, " -- ")); err != nil {
				return fmt.Errorf("adding ingress-only mirror %s on cluster host %s: %w", name, h, err)
			}
		}
	}

	exp.Status.SetAppStatus("mirror", status)

	return nil
}

func cleanup(exp *types.Experiment) error {
	app := util.ExtractApp(exp.Spec.Scenario(), "mirror")

	amd, err := extractMetadata(app.Metadata())
	if err != nil {
		return fmt.Errorf("extracting app metadata: %w", err)
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

		if err := deleteMirror(name, amd.MirrorBridge, cluster); err != nil {
			log.Error("removing mirror %s from cluster: %v", name, err)
		}
	}

	if err := deleteTap(status.TapName, cluster); err != nil {
		log.Error("removing tap %s from cluster: %v", status.TapName, err)
	}

	return nil
}

func mirrorNet(md MirrorAppMetadataV1) (iplib.Net, int, error) {
	var nw iplib.Net

	// Set some default values if missing from metadata.
	if md.MirrorNet == "" {
		md.MirrorNet = "172.30.0.0/16"
	}

	if md.MirrorBridge == "" {
		md.MirrorBridge = "phenix"
	}

	if md.MirrorVLAN == "" {
		md.MirrorVLAN = "mirror"
	}

	tokens := strings.Split(md.MirrorNet, "/")

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
					log.Info("adding tap %s (VLAN %s) for VM %s", vmTaps[idx], vlanID, vm)

					taps = append(taps, vmTaps[idx])
					break
				}
			}
		}
	}

	return taps
}

func buildMirrorCommand(exp *types.Experiment, name, bridge, port string, vms []string, hmd MirrorHostMetadata) []string {
	var (
		vlans   []string
		command = []string{"shell ovs-vsctl"}
	)

	// convert VLAN aliases to IDs
	for _, vlan := range hmd.VLANs {
		id, ok := exp.Status.VLANs()[vlan]
		if ok {
			vlans = append(vlans, strconv.Itoa(id))
		}
	}

	taps := vlanTaps(exp.Spec.ExperimentName(), vms, vlans)

	// add HIL interfaces to list of taps to mirror
	log.Info("adding %v HIL taps to list of taps to mirror", hmd.HIL)
	taps = append(taps, hmd.HIL...)

	if len(taps) == 0 {
		return nil
	}

	ids := make([]string, len(taps))

	for i, tap := range taps {
		id := fmt.Sprintf("@i%d", i)

		ids[i] = id
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
	log.Info("deleting tap %s from host %s", tap, host)

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
	log.Info("deleting mirror %s on bridge %s from host %s", mirror, bridge, host)

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
