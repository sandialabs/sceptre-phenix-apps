package main

import (
	"log/slog"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestFilterVMs(t *testing.T) {
	t.Parallel()

	var (
		log = slog.Default()
		vms = []string{"vm1", "router1", "vm2", "firewall1"}
	)

	getNodeType := func(name string) string {
		switch name {
		case "router1":
			return "router"
		case "firewall1":
			return "firewall"
		default:
			return "vm"
		}
	}

	tests := []struct {
		name     string
		hmd      MirrorHostMetadata
		expected []string
	}{
		{
			name:     "single vlan",
			hmd:      testMetadata([]string{"100"}, false),
			expected: []string{"vm1", "router1", "vm2", "firewall1"},
		},
		{
			name:     "multiple vlans, no mirror routed",
			hmd:      testMetadata([]string{"100", "101"}, false),
			expected: []string{"vm1", "vm2"},
		},
		{
			name:     "multiple vlans, mirror routed",
			hmd:      testMetadata([]string{"100", "101"}, true),
			expected: []string{"vm1", "router1", "vm2", "firewall1"},
		},
		{
			name:     "empty vms",
			hmd:      testMetadata([]string{"100", "101"}, false),
			expected: []string{},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()

			var inputVMs []string
			if tt.name != "empty vms" {
				inputVMs = make([]string, len(vms))
				copy(inputVMs, vms)
			}

			got := filterVMs(log, inputVMs, tt.hmd, "target", getNodeType)
			assert.Equal(t, tt.expected, got)
		})
	}
}

func TestFilterVMs_CaseInsensitive(t *testing.T) {
	t.Parallel()

	log := slog.Default()
	vms := []string{"ROUTER1"}
	hmd := testMetadata([]string{"1", "2"}, false)

	getNodeType := func(_ string) string {
		return "ROUTER"
	}

	got := filterVMs(log, vms, hmd, "target", getNodeType)
	assert.Empty(t, got, "Should filter out ROUTER (case insensitive)")
}

func TestMirrorTapNameUsesConfiguredNameOrRandomFallback(t *testing.T) {
	t.Parallel()

	var configured MirrorAppMetadataV1
	configured.TapName = "guarded-mirror"
	assert.Equal(t, "guarded-mirror", mirrorTapName(configured))

	generated := mirrorTapName(MirrorAppMetadataV1{}) //nolint:exhaustruct // empty metadata exercises defaults
	require.Regexp(t, `^[A-Za-z0-9]{8}-mirror$`, generated)
}

func testMetadata(vlans []string, routed bool) MirrorHostMetadata {
	return MirrorHostMetadata{
		Interface:    "",
		VLANs:        vlans,
		HIL:          nil,
		SetupOVS:     false,
		MirrorRouted: routed,
	}
}
