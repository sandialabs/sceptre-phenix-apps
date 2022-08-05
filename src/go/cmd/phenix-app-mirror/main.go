package main

import (
	"embed"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"os"
	"regexp"
	"runtime/debug"
	"strconv"
	"strings"

	"phenix-apps/util"
	"phenix/store"
	"phenix/types"
	"phenix/util/mm"

	"github.com/hashicorp/go-multierror"
	"inet.af/netaddr"

	ifaces "phenix/types/interfaces"
	putil "phenix/util"

	log "github.com/activeshadow/libminimega/minilog"
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

	endpoint := os.Getenv("PHENIX_STORE_ENDPOINT")
	if err := store.Init(store.Endpoint(endpoint)); err != nil {
		log.Fatal("initializing store: %w", err)
	}

	switch stage {
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

func preStart(exp *types.Experiment) error {
	app := util.ExtractApp(exp.Spec.Scenario(), "mirror")
	startupDir := exp.Spec.BaseDir() + "/startup"

	amd, err := extractMetadata(app.Metadata())
	if err != nil {
		return fmt.Errorf("extracting app metadata: %w", err)
	}

	nw, err := mirrorNet(&amd)
	if err != nil {
		return fmt.Errorf("determining mirror network: %w", err)
	}

	// For configurations where multiple hosts are configured to receive mirrored
	// traffic, we'll start addressing them at the end of the network range and
	// work our way backwards, and the cluster hosts will be addressed at the
	// beginning of the network range forward.
	ip := nw.Range().To().Prior()

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
			return fmt.Errorf("no node found in topology for %s", host.Hostname())
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
		iface.SetMask(int(nw.Bits()))
		iface.SetGateway("") // just in case it was set in the topology...
		iface.SetVLAN(amd.MirrorVLAN)

		// Decrement IP for next target VM.
		ip = ip.Prior()

		if !hmd.SetupOVS {
			continue
		}

		if strings.EqualFold(node.Hardware().OSType(), "windows") {
			log.Error("setting up OVS not supported on Windows (%s)", host.Hostname())
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

	// The remaining code in this function is essentially the same as the cleanup
	// function, but without logging. We are running the cleanup code here just in
	// case the previous experiment didn't exit cleanly, so we can avoid any
	// post-start errors arising from GRE taps and mirrors already existing on
	// cluster nodes.

	var status MirrorAppStatus
	if err := exp.Status.ParseAppStatus("mirror", &status); err != nil {
		// Likely no mirror app data in experiment status, so nothing else to do here.
		return nil
	}

	cluster := cluster(exp)

	for _, cfg := range status.Mirrors {
		// Ignoring errors here since in most cases all the mirrors would have
		// already been removed when the previous experiment was stopped.
		deleteMirror(cfg.MirrorName, cfg.MirrorBridge, cluster)
	}

	// Ignoring errors here since in most cases all the taps would have already
	// been removed when the previous experiment was stopped.
	deleteTap(status.TapName, exp.Metadata.Name, cluster)

	return nil
}

func postStart(exp *types.Experiment) (ferr error) {
	app := util.ExtractApp(exp.Spec.Scenario(), "mirror")

	amd, err := extractMetadata(app.Metadata())
	if err != nil {
		return fmt.Errorf("extracting app metadata: %w", err)
	}

	nw, err := mirrorNet(&amd)
	if err != nil {
		return fmt.Errorf("determining mirror network: %w", err)
	}

	cluster := cluster(exp)

	status := MirrorAppStatus{
		// Tap name is random, yet descriptive to the fact that it's a mirror tap.
		TapName: fmt.Sprintf("%s-mirror", util.RandomString(8)),
		Subnet:  nw.Masked().String(),
		Mirrors: make(map[string]MirrorConfig),
	}

	defer func() {
		// don't do any cleanup if no error is being returned
		if ferr == nil {
			return
		}

		// clean up any taps already created for this mirror
		deleteTap(status.TapName, exp.Metadata.Name, cluster)

		// clean up any mirrors already created for this mirror
		for _, mirror := range status.Mirrors {
			deleteMirror(mirror.MirrorName, mirror.MirrorBridge, cluster)
		}
	}()

	// Cluster hosts will be addressed at the beginning of the mirror network
	// going forward (target VMs to receive mirrored data are addressed from the
	// end of the mirror network backwards).
	ip := nw.Range().From().Next()

	// For each cluster host, create tap on mirror VLAN with IP in mirror network.
	// The tap's name will be something like `<random 8 character string>-mirror`.
	// The maximum length of the name is dictated by the maximum length of a Linux
	// interface name, which is 15 characters. Once created, move the tap into a
	// network namespace on the cluster host so it doesn't interfere with other
	// experiments on the same cluster hosts that might be using the same mirror
	// network.
	for host := range cluster {
		log.Info("creating mirror tap %s on host %s", status.TapName, host)

		addr := fmt.Sprintf("%s/%d", ip, nw.Bits())

		opts := []mm.TapOption{
			mm.TapHost(host), mm.TapNS(exp.Metadata.Name), mm.TapName(status.TapName),
			mm.TapBridge(amd.MirrorBridge), mm.TapVLANAlias(amd.MirrorVLAN), mm.TapIP(addr),
		}

		if err := mm.TapVLAN(opts...); err != nil {
			return fmt.Errorf("creating tap on host %s: %w", host, err)
		}

		// Increment IP for next cluster host.
		ip = ip.Next()
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
		var ip netaddr.IP

		// Get IP to mirror packets to via GRE
		for _, iface := range node.Network().Interfaces() {
			if iface.Name() == hmd.Interface {
				ip = netaddr.MustParseIP(iface.Address())
				break
			}
		}

		if ip.IsZero() {
			log.Warn("no target interface IP configured for %s", host.Hostname())
			continue
		}

		// Limit name to 15 characters since it will be used for an OVS port name
		// (limited to 15 characters by Linux since it will be used as an interface
		// name).
		name := util.RandomString(15)

		cfg := MirrorConfig{MirrorName: name, MirrorBridge: amd.MirrorBridge, IP: ip.String()}

		status.Mirrors[host.Hostname()] = cfg

		for h := range cluster {
			if amd.ERSPAN.Enabled {
				var cmd string

				switch amd.ERSPAN.Version {
				case 1:
					// Create ERSPAN v1 tunnel to target VM
					cmd = fmt.Sprintf(
						`ovs-vsctl add-port %s %s -- set interface %s type=erspan options:remote_ip=%s options:erspan_ver=%d options:erspan_idx=%d`,
						amd.MirrorBridge, name, name, ip, amd.ERSPAN.Version, amd.ERSPAN.Index,
					)
				case 2:
					// Create ERSPAN v2 tunnel to target VM
					cmd = fmt.Sprintf(
						`ovs-vsctl add-port %s %s -- set interface %s type=erspan options:remote_ip=%s options:erspan_ver=%d options:erspan_dir=%d options:erspan_hwid=%d`,
						amd.MirrorBridge, name, name, ip, amd.ERSPAN.Version, amd.ERSPAN.Direction, amd.ERSPAN.HardwareID,
					)
				default:
					return fmt.Errorf("unknown ERSPAN version (%d) configured for %s", amd.ERSPAN.Version, host.Hostname())
				}

				if err := mm.MeshShell(h, cmd); err != nil {
					return fmt.Errorf("adding ERSPAN tunnel %s from cluster host %s: %w", name, h, err)
				}
			} else {
				log.Info("creating GRE port %s to %s on host %s", name, host.Hostname(), h)

				// Create GRE tunnel to target VM
				cmd := fmt.Sprintf(
					`ovs-vsctl add-port %s %s -- set interface %s type=gre options:remote_ip=%s`,
					amd.MirrorBridge, name, name, ip,
				)

				if err := mm.MeshShell(h, cmd); err != nil {
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

			if err := mm.MeshShell(h, strings.Join(command, " -- ")); err != nil {
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

	amd.Init()

	cluster := cluster(exp)

	var status MirrorAppStatus
	if err := exp.Status.ParseAppStatus("mirror", &status); err != nil {
		return fmt.Errorf("decoding app status: %w", err)
	}

	for _, cfg := range status.Mirrors {
		if err := deleteMirror(cfg.MirrorName, cfg.MirrorBridge, cluster); err != nil {
			log.Error("removing mirror %s from cluster: %v", cfg.MirrorName, err)
		}
	}

	if err := deleteTap(status.TapName, exp.Metadata.Name, cluster); err != nil {
		log.Error("deleting tap %s from cluster: %v", status.TapName, err)
	}

	return nil
}

func deleteTap(name, exp string, cluster map[string][]string) error {
	var errs error

	for host := range cluster {
		errs = multierror.Append(errs, deleteTapFromHost(name, exp, host))
	}

	return errs
}

func deleteTapFromHost(name, exp, host string) error {
	opts := []mm.TapOption{
		mm.TapHost(host), mm.TapNS(exp),
		mm.TapName(name), mm.TapNetNS(name),
		mm.TapDelete(),
	}

	if err := mm.TapVLAN(opts...); err != nil {
		return fmt.Errorf("deleting tap on host %s: %w", host, err)
	}

	return nil
}

func deleteMirror(mirror, bridge string, cluster map[string][]string) error {
	var errs error

	for host := range cluster {
		errs = multierror.Append(errs, deleteMirrorFromHost(mirror, bridge, host))
	}

	return errs
}

func deleteMirrorFromHost(mirror, bridge, host string) error {
	log.Info("deleting mirror %s on bridge %s from host %s", mirror, bridge, host)

	var errs error

	cmd := fmt.Sprintf(
		`ovs-vsctl -- --id=@m get mirror %s -- remove bridge %s mirrors @m`,
		mirror, bridge,
	)

	if err := mm.MeshShell(host, cmd); err != nil {
		errs = multierror.Append(errs, fmt.Errorf("removing mirror %s from bridge %s on cluster host %s: %v", mirror, bridge, host, err))
	}

	cmd = fmt.Sprintf(`ovs-vsctl del-port %s %s`, bridge, mirror)

	if err := mm.MeshShell(host, cmd); err != nil {
		errs = multierror.Append(errs, fmt.Errorf("deleting GRE tunnel %s from bridge %s on cluster host %s: %v", mirror, bridge, host, err))
	}

	return errs
}

func mirrorNet(md *MirrorAppMetadataV1) (netaddr.IPPrefix, error) {
	md.Init()

	subnet, err := netaddr.ParseIPPrefix(md.MirrorNet)
	if err != nil {
		return netaddr.IPPrefix{}, fmt.Errorf("parsing mirror net: %w", err)
	}

	running, err := types.RunningExperiments()
	if err != nil {
		// Log the error, but don't escalate it. Instead, just assume there's no
		// other experiments running and let things (potentially) fail
		// spectacularly.
		log.Error("getting running experiments: %v", err)
		return subnet, nil
	}

	var used []netaddr.IPPrefix

	for _, exp := range running {
		var status MirrorAppStatus

		// Not every experiment uses the mirror app, so don't worry about errors.
		if err := exp.Status.ParseAppStatus("mirror", &status); err == nil {
			used = append(used, netaddr.MustParseIPPrefix(status.Subnet))
		}
	}

	subnet, err = putil.UnusedSubnet(subnet, used)
	if err != nil {
		return netaddr.IPPrefix{}, fmt.Errorf("searching for unused subnet for mirror net: %w", err)
	}

	return subnet, nil
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

func buildMirrorCommand(exp *types.Experiment, name, bridge, port string, vms []string, hmd MirrorHostMetadata) []string {
	var (
		vlans   []string
		command = []string{"ovs-vsctl"}
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

func vlanTaps(ns string, vms, vlans []string) []string {
	var (
		vmSet = make(map[string]struct{})
		taps  []string
	)

	for _, vm := range vms {
		vmSet[vm] = struct{}{}
	}

	var vlanAliasRegex = regexp.MustCompile(`(.*) \((\d*)\)`)

	for _, vm := range mm.GetVMInfo(mm.NS(ns)) {
		if _, ok := vmSet[vm.Name]; !ok {
			continue
		}

		for idx, alias := range vm.Networks {
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
					log.Info("adding tap %s (VLAN %s) for VM %s", vm.Taps[idx], vlanID, vm)

					taps = append(taps, vm.Taps[idx])
					break
				}
			}
		}
	}

	return taps
}
