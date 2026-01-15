package main

import (
	"embed"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"os"
	"phenix-apps/util"
	"phenix/store"
	"phenix/types"
	"phenix/util/mm"
	"regexp"
	"runtime/debug"
	"strconv"
	"strings"

	"github.com/hashicorp/go-multierror"
	"golang.org/x/exp/slog"
	"inet.af/netaddr"

	ifaces "phenix/types/interfaces"
	putil "phenix/util"
)

//go:embed templates/*
var templates embed.FS

//nolint:cyclop,funlen // switch on stage not complex
func main() {
	util.SetupLogging()

	if len(os.Args) != 2 {
		slog.Error("incorrect amount of args provided")
	}

	var (
		stage  = os.Args[1]
		dryrun = util.IsDryRun()
	)

	if stage == "version" {
		info, ok := debug.ReadBuildInfo()
		if !ok {
			slog.Error("unable to read build info")
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
		slog.Error("unable to read JSON from STDIN")
	}

	exp, err := util.DecodeExperiment(body)
	if err != nil {
		slog.Error("decoding experiment", "err", err)
	}

	endpoint := os.Getenv("PHENIX_STORE_ENDPOINT")
	if err := store.Init(store.Endpoint(endpoint)); err != nil {
		slog.Error("initializing store: %w", err)
	}

	switch stage {
	case "configure":
		err := configure(exp)
		if err != nil {
			slog.Error("failed to execute configure stage", "err", err)
		}
	case "pre-start":
		err := preStart(exp, dryrun)
		if err != nil {
			slog.Error("failed to execute pre-start stage", "err", err)
		}
	case "post-start":
		err := postStart(exp, dryrun)
		if err != nil {
			slog.Error("failed to execute post-start stage", "err", err)
		}
	case "cleanup":
		err := cleanup(exp, dryrun)
		if err != nil {
			slog.Error("failed to execute cleanup stage", "err", err)
		}
	default:
		fmt.Print(string(body))

		return
	}

	body, err = json.Marshal(exp)
	if err != nil {
		slog.Error("unable to convert experiment to JSON")
	}

	fmt.Print(string(body))
}

//nolint:cyclop // loop on hosts not complex
func configure(exp *types.Experiment) error {
	app := util.ExtractApp(exp.Spec.Scenario(), "mirror")

	amd, err := extractMetadata(app.Metadata())
	if err != nil {
		return fmt.Errorf("extracting app metadata: %w", err)
	}

	amd.Init()

	if amd.MirrorBridge == "" {
		amd.MirrorBridge = exp.Spec.DefaultBridge()
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
	}

	return nil
}

func preStart(exp *types.Experiment, dryrun bool) error {
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
			return fmt.Errorf("no node found in topology for %s", host.Hostname())
		}

		if strings.EqualFold(node.Hardware().OSType(), "windows") {
			slog.Error("setting up OVS not supported on Windows", "host", host.Hostname())

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

	// no need to try to clean up previous experiments if this is a dry run
	if dryrun {
		return nil
	}

	// The remaining code in this function is essentially the same as the cleanup
	// function, but without logging. We are running the cleanup code here just in
	// case the previous experiment didn't exit cleanly, so we can avoid any
	// post-start errors arising from GRE taps and mirrors already existing on
	// cluster nodes.

	var status MirrorAppStatus

	err := exp.Status.ParseAppStatus("mirror", &status)
	if err != nil {
		//nolint:nilerr // Likely no mirror app data in experiment status, so nothing else to do here.
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

//nolint:cyclop,funlen,gocognit,gocyclo,maintidx,nonamedreturns // should be refactored
func postStart(exp *types.Experiment, dryrun bool) (ferr error) {
	app := util.ExtractApp(exp.Spec.Scenario(), "mirror")

	amd, err := extractMetadata(app.Metadata())
	if err != nil {
		return fmt.Errorf("extracting app metadata: %w", err)
	}

	amd.Init()

	if amd.MirrorBridge == "" {
		amd.MirrorBridge = exp.Spec.DefaultBridge()
	}

	nw, err := mirrorNet(&amd)
	if err != nil {
		return fmt.Errorf("determining mirror network: %w", err)
	}

	cluster := cluster(exp)

	status := MirrorAppStatus{
		// Tap name is random, yet descriptive to the fact that it's a mirror tap.
		TapName: util.RandomString(8) + "-mirror",
		Subnet:  nw.Masked().String(),
		Mirrors: make(map[string]MirrorConfig),
	}

	defer func() {
		// don't do any cleanup if no error is being returned or this is a dry run
		if ferr == nil || dryrun {
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
		slog.Info(
			"creating mirror tap",
			"tap",
			status.TapName,
			"vlan",
			amd.MirrorVLAN,
			"host",
			host,
		)

		addr := fmt.Sprintf("%s/%d", ip, nw.Bits())

		if dryrun {
			slog.Debug("[DRYRUN] using IP %s for tap", "ip", addr)
		} else {
			opts := []mm.TapOption{
				mm.TapHost(host), mm.TapNS(exp.Metadata.Name), mm.TapName(status.TapName),
				mm.TapBridge(amd.MirrorBridge), mm.TapVLANAlias(amd.MirrorVLAN), mm.TapIP(addr),
			}

			err := mm.TapVLAN(opts...)
			if err != nil {
				return fmt.Errorf("creating tap using VLAN %s on host %s: %w", amd.MirrorVLAN, host, err)
			}
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

		slog.Info(
			"setting up mirror",
			"to",
			host.Hostname(),
			"vlans",
			len(hmd.VLANs),
			"mirrored_route",
			hmd.MirrorRouted,
		)

		node := exp.Spec.Topology().FindNodeByName(host.Hostname())

		if node == nil {
			slog.Warn("no node found in topology", "host", host.Hostname())

			continue
		}

		if hmd.Interface == "" {
			slog.Warn("no target interface provided for host", "host", host.Hostname())

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
			slog.Warn("no target interface IP configured for host", "host", host.Hostname())

			continue
		}

		// Limit name to 15 characters since it will be used for an OVS port name
		// (limited to 15 characters by Linux since it will be used as an interface
		// name).
		name := util.RandomString(15)

		cfg := MirrorConfig{MirrorName: name, MirrorBridge: amd.MirrorBridge, IP: ip.String()}
		status.Mirrors[host.Hostname()] = cfg

		for h := range cluster {
			//nolint:nestif // should be refactored
			if amd.ERSPAN.Enabled {
				slog.Info("creating ERSPAN port", "name", name, "to", host.Hostname(), "host", h)

				var cmd string

				switch amd.ERSPAN.Version {
				case 1:
					//nolint:lll // command
					// Create ERSPAN v1 tunnel to target VM
					cmd = fmt.Sprintf(
						`ovs-vsctl add-port %s %s -- set interface %s type=erspan options:remote_ip=%s options:erspan_ver=%d options:erspan_idx=%d`,
						amd.MirrorBridge,
						name,
						name,
						ip,
						amd.ERSPAN.Version,
						amd.ERSPAN.Index,
					)
				case 2:
					//nolint:lll // command
					// Create ERSPAN v2 tunnel to target VM
					cmd = fmt.Sprintf(
						`ovs-vsctl add-port %s %s -- set interface %s type=erspan options:remote_ip=%s options:erspan_ver=%d options:erspan_dir=%d options:erspan_hwid=%d`,
						amd.MirrorBridge,
						name,
						name,
						ip,
						amd.ERSPAN.Version,
						amd.ERSPAN.Direction,
						amd.ERSPAN.HardwareID,
					)
				default:
					return fmt.Errorf(
						"unknown ERSPAN version (%d) configured for %s",
						amd.ERSPAN.Version,
						host.Hostname(),
					)
				}

				if dryrun {
					slog.Debug("[DRYRUN] ERSPAN tunnel command", "cmd", cmd)
				} else {
					err := mm.MeshShell(h, cmd)
					if err != nil {
						return fmt.Errorf("adding ERSPAN tunnel %s from cluster host %s: %w", name, h, err)
					}
				}
			} else {
				slog.Info("creating GRE port", "name", name, "to", host.Hostname(), "host", h)

				// Create GRE tunnel to target VM
				cmd := fmt.Sprintf(
					`ovs-vsctl add-port %s %s -- set interface %s type=gre options:remote_ip=%s`,
					amd.MirrorBridge, name, name, ip,
				)

				if dryrun {
					slog.Debug("[DRYRUN] GRE tunnel command", "cmd", cmd)
				} else {
					err := mm.MeshShell(h, cmd)
					if err != nil {
						return fmt.Errorf("adding GRE tunnel %s from cluster host %s: %w", name, h, err)
					}
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
					if strings.EqualFold(node.Type(), "router") ||
						strings.EqualFold(node.Type(), "firewall") {
						slog.Debug(
							"removing VM from list of VMs to mirror",
							"vm",
							name,
							"type",
							node.Type(),
							"mirrored_to",
							host,
							"vlans",
							len(hmd.VLANs),
							"mirrored_route",
							hmd.MirrorRouted,
						)

						// remove current VM from list of VMs
						vms = append(vms[:i], vms[i+1:]...)
					}
				}
			}

			var command []string

			// only try to build the mirror command if this is not a dry run since
			// building the mirror command uses info about VMs actually deployed
			if !dryrun {
				// Create mirror, using GRE tunnel as the output port
				command = buildMirrorCommand(exp, name, amd.MirrorBridge, name, vms, hmd)

				if command == nil {
					// Likely means no VMs scheduled on this cluster host have interfaces in
					// VLANs being mirrored to the target VM.
					continue
				}
			}

			slog.Info("creating mirror", "name", name, "for", host.Hostname(), "host", h)

			// only create the mirror if this is not a dry run
			if !dryrun {
				err := mm.MeshShell(h, strings.Join(command, " -- "))
				if err != nil {
					return fmt.Errorf(
						"adding ingress-only mirror %s on cluster host %s: %w",
						name,
						h,
						err,
					)
				}
			}
		}
	}

	exp.Status.SetAppStatus("mirror", status)

	return nil
}

func cleanup(exp *types.Experiment, dryrun bool) error {
	// cleanup is not needed if this is a dry run
	if dryrun {
		slog.Debug("[DRYRUN] skipping cleanup code")

		return nil
	}

	app := util.ExtractApp(exp.Spec.Scenario(), "mirror")

	amd, err := extractMetadata(app.Metadata())
	if err != nil {
		return fmt.Errorf("extracting app metadata: %w", err)
	}

	amd.Init()

	if amd.MirrorBridge == "" {
		amd.MirrorBridge = exp.Spec.DefaultBridge()
	}

	cluster := cluster(exp)

	var status MirrorAppStatus
	if err := exp.Status.ParseAppStatus("mirror", &status); err != nil {
		return fmt.Errorf("decoding app status: %w", err)
	}

	for _, cfg := range status.Mirrors {
		err := deleteMirror(cfg.MirrorName, cfg.MirrorBridge, cluster)
		if err != nil {
			slog.Error("removing mirror from cluster", "mirror", cfg.MirrorName, "err", err)
		}
	}

	if err := deleteTap(status.TapName, exp.Metadata.Name, cluster); err != nil {
		slog.Error("deleting tap from cluster", "tap", status.TapName, "err", err)
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
	slog.Info("deleting mirror tap", "mirror", name, "host", host)

	opts := []mm.TapOption{
		mm.TapHost(host), mm.TapNS(exp),
		mm.TapName(name), mm.TapDelete(),
	}

	err := mm.TapVLAN(opts...)
	if err != nil {
		return fmt.Errorf("deleting tap %s on host %s: %w", name, host, err)
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
	slog.Info("deleting mirror", "mirror", mirror, "bridge", bridge, "host", host)

	var errs error

	cmd := fmt.Sprintf(
		`ovs-vsctl -- --id=@m get mirror %s -- remove bridge %s mirrors @m`,
		mirror, bridge,
	)

	err := mm.MeshShell(host, cmd)
	if err != nil {
		errs = multierror.Append(
			errs,
			fmt.Errorf(
				"removing mirror %s from bridge %s on cluster host %s: %w",
				mirror,
				bridge,
				host,
				err,
			),
		)
	}

	cmd = fmt.Sprintf(`ovs-vsctl del-port %s %s`, bridge, mirror)

	err = mm.MeshShell(host, cmd)
	if err != nil {
		errs = multierror.Append(
			errs,
			fmt.Errorf(
				"deleting GRE tunnel %s from bridge %s on cluster host %s: %w",
				mirror,
				bridge,
				host,
				err,
			),
		)
	}

	return errs
}

func mirrorNet(md *MirrorAppMetadataV1) (netaddr.IPPrefix, error) {
	md.Init()

	subnet, err := netaddr.ParseIPPrefix(md.MirrorNet)
	if err != nil {
		return netaddr.IPPrefix{}, fmt.Errorf("parsing mirror net: %w", err)
	}

	running, err := runningExperiments()
	if err != nil {
		// Log the error, but don't escalate it. Instead, just assume there's no
		// other experiments running and let things (potentially) fail
		// spectacularly.
		slog.Error("getting running experiments", "err", err)

		return subnet, nil
	}

	var used []netaddr.IPPrefix

	for _, exp := range running {
		var status MirrorAppStatus

		// Not every experiment uses the mirror app, so don't worry about errors.
		err := exp.Status.ParseAppStatus("mirror", &status)
		if err == nil {
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

func buildMirrorCommand(
	exp *types.Experiment,
	name, bridge, port string,
	vms []string,
	hmd MirrorHostMetadata,
) []string {
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
	slog.Info("adding HIL taps to list of taps to mirror", "taps", hmd.HIL)
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

	command = append(command, "--id=@o get port "+port)
	command = append(
		command,
		fmt.Sprintf(
			`--id=@m create mirror name=%s select-dst-port=%s select-vlan=%s output-port=@o`,
			name,
			strings.Join(ids, ","),
			strings.Join(vlans, ","),
		),
	)
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

	vlanAliasRegex := regexp.MustCompile(`(.*) \((\d*)\)`)

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
					slog.Info("adding tap for VM", "tap", vm.Taps[idx], "vlan", vlanID, "vm", vm)

					taps = append(taps, vm.Taps[idx])

					break
				}
			}
		}
	}

	return taps
}

func runningExperiments() ([]*types.Experiment, error) {
	configs, err := store.List("Experiment")
	if err != nil {
		return nil, fmt.Errorf("getting list of experiment configs from store: %w", err)
	}

	var experiments []*types.Experiment

	for _, c := range configs {
		exp, err := types.DecodeExperimentFromConfig(c)
		if err != nil {
			return nil, fmt.Errorf("decoding experiment %s from config: %w", c.Metadata.Name, err)
		}

		if exp.Running() {
			experiments = append(experiments, exp)
		}
	}

	return experiments, nil
}
