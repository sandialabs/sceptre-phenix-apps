package main

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"phenix-apps/util"
	"phenix/store"
	"phenix/types"
)

// mirrorExperiment returns an experiment with one mirror host, monitor, whose
// mirror interface IF0 has the given address ("" leaves it unset), and an
// optional mirror status subnet.
func mirrorExperiment(t *testing.T, name, address, statusSubnet string) *types.Experiment {
	t.Helper()

	iface := map[string]any{"name": "IF0", "vlan": "mirror", "type": "ethernet"}
	if address != "" {
		iface["address"] = address
		iface["mask"] = 24
		iface["proto"] = "static"
	}

	status := map[string]any{}
	if statusSubnet != "" {
		status["apps"] = map[string]any{
			"mirror": map[string]any{"tapName": "abcdefgh-mirror", "subnet": statusSubnet},
		}
	}

	doc := map[string]any{
		"metadata": map[string]any{"name": name},
		"spec": map[string]any{
			"experimentName": name,
			"baseDir":        t.TempDir(),
			"defaultBridge":  "phenix",
			"topology": map[string]any{
				"nodes": []any{
					map[string]any{
						"type":     "VirtualMachine",
						"general":  map[string]any{"hostname": "monitor"},
						"hardware": map[string]any{"os_type": "linux"},
						"network":  map[string]any{"interfaces": []any{iface}},
					},
				},
			},
			"scenario": map[string]any{
				"apps": []any{
					map[string]any{
						"name":     "mirror",
						"metadata": map[string]any{"version": "v1"},
						"hosts": []any{
							map[string]any{
								"hostname": "monitor",
								"metadata": map[string]any{"interface": "IF0", "vlans": []any{"EXP_1"}},
							},
						},
					},
				},
			},
		},
		"status": status,
	}

	body, err := json.Marshal(doc)
	require.NoError(t, err)

	exp, err := util.DecodeExperiment(body)
	require.NoError(t, err)

	return exp
}

func monitorAddress(t *testing.T, exp *types.Experiment) string {
	t.Helper()

	node := exp.Spec.Topology().FindNodeByName("monitor")
	require.NotNil(t, node)

	for _, iface := range node.Network().Interfaces() {
		if iface.Name() == "IF0" {
			return fmt.Sprintf("%s/%d", iface.Address(), iface.Mask())
		}
	}

	t.Fatal("monitor has no IF0 interface")

	return ""
}

func storeExperiment(t *testing.T, exp *types.Experiment) {
	t.Helper()

	body, err := json.Marshal(exp)
	require.NoError(t, err)

	var doc map[string]any
	require.NoError(t, json.Unmarshal(body, &doc))

	spec, ok := doc["spec"].(map[string]any)
	require.True(t, ok)

	cfg, err := store.NewConfig("experiment/" + exp.Metadata.Name)
	require.NoError(t, err)

	cfg.Spec = spec

	if status, isMap := doc["status"].(map[string]any); isMap {
		cfg.Status = status
	}

	require.NoError(t, store.Create(cfg))
}

func TestSensorSubnet(t *testing.T) {
	t.Parallel()

	subnet, ok := sensorSubnet(mirrorExperiment(t, "exp1", "10.248.172.254", ""))
	require.True(t, ok)
	assert.Equal(t, "10.248.172.0/24", subnet.String())

	_, ok = sensorSubnet(mirrorExperiment(t, "exp2", "", ""))
	assert.False(t, ok, "no address assigned yet")
}

func TestUsedSubnets(t *testing.T) {
	t.Parallel()

	exps := []*types.Experiment{
		mirrorExperiment(t, "created", "10.248.171.254", ""),
		mirrorExperiment(t, "running", "10.248.172.254", "10.248.172.0/24"),
		mirrorExperiment(t, "self", "10.248.173.254", ""),
	}

	used := usedSubnets(exps, "self")
	got := make([]string, 0, len(used))

	for _, subnet := range used {
		got = append(got, subnet.String())
	}

	assert.Equal(t, []string{"10.248.171.0/24", "10.248.172.0/24", "10.248.172.0/24"}, got)
}

func TestUsedSubnetsSkipsInvalidStatus(t *testing.T) {
	t.Parallel()

	exp := mirrorExperiment(t, "bad", "", "")
	exp.Status.SetAppStatus("mirror", map[string]any{"tapName": "x"})

	assert.Empty(t, usedSubnets([]*types.Experiment{exp}, "self"))
}

// Experiments created before any of them is started must each get their own
// mirror network (issue #224). The experiments are configured one after
// another; two configures running at the same moment can still pick the same
// subnet. Not parallel: it uses the global store.
func TestConfigureExperimentsCreatedBeforeStart(t *testing.T) {
	endpoint := "bolt://" + filepath.Join(t.TempDir(), "phenix.bdb")
	require.NoError(t, store.Init(store.Endpoint(endpoint)))

	log := slog.Default()

	var got []string

	for i := 1; i <= 4; i++ {
		exp := mirrorExperiment(t, fmt.Sprintf("exp%d", i), "", "")

		handled, err := runStage(log, "configure", exp, true)
		require.NoError(t, err)
		require.True(t, handled)

		got = append(got, monitorAddress(t, exp))

		storeExperiment(t, exp)
	}

	assert.Equal(t, []string{
		"10.248.171.254/24",
		"10.248.172.254/24",
		"10.248.173.254/24",
		"10.248.174.254/24",
	}, got)

	// Configuring an experiment again keeps its own subnet available to it.
	exp := mirrorExperiment(t, "exp1", "", "")

	_, err := runStage(log, "configure", exp, true)
	require.NoError(t, err)
	assert.Equal(t, "10.248.171.254/24", monitorAddress(t, exp))
}

func TestPostStartUsesConfiguredSubnet(t *testing.T) {
	t.Parallel()

	exp := mirrorExperiment(t, "exp3", "10.248.173.254", "")

	handled, err := runStage(slog.Default(), "post-start", exp, true)
	require.NoError(t, err)
	require.True(t, handled)

	var status MirrorAppStatus
	require.NoError(t, exp.Status.ParseAppStatus("mirror", &status))
	assert.Equal(t, "10.248.173.0/24", status.Subnet)
}

func TestRunStageReturnsStageError(t *testing.T) {
	t.Parallel()

	exp := mirrorExperiment(t, "exp1", "", "")
	exp.Spec.Scenario().Apps()[0].Hosts()[0].Metadata()["hilInterfaces"] = []any{"eth1 eth2"}

	handled, err := runStage(slog.Default(), "pre-start", exp, true)
	require.Error(t, err)
	assert.True(t, handled)
	assert.Contains(t, err.Error(), "executing pre-start stage")

	handled, err = runStage(slog.Default(), "running", exp, true)
	require.NoError(t, err)
	assert.False(t, handled)
}

func TestCleanupWithoutStatus(t *testing.T) {
	t.Parallel()

	exp := mirrorExperiment(t, "exp1", "10.248.171.254", "")

	handled, err := runStage(slog.Default(), "cleanup", exp, false)
	require.NoError(t, err)
	assert.True(t, handled)
}
