package main

import (
	"errors"
	"log/slog"
	"strings"
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

func testMetadata(vlans []string, routed bool) MirrorHostMetadata {
	return MirrorHostMetadata{
		Interface:    "",
		VLANs:        vlans,
		HIL:          nil,
		SetupOVS:     false,
		MirrorRouted: routed,
	}
}

func TestCheckMirrorBudget(t *testing.T) {
	t.Parallel()

	full := "[" + strings.Repeat("uuid, ", ovsMirrorLimit-1) + "uuid]"
	errShell := errors.New("mesh failed")

	tests := []struct {
		name    string
		out     string
		err     error
		wantErr string
	}{
		{name: "empty", out: "[]", err: nil, wantErr: ""},
		{name: "one left", out: strings.Replace(full, "uuid, ", "", 1), err: nil, wantErr: ""},
		{name: "full", out: full, err: nil, wantErr: errMirrorBudget.Error()},
		{name: "unreadable", out: "no row", err: nil, wantErr: errMirrorList.Error()},
		{name: "command fails", out: "", err: errShell, wantErr: errShell.Error()},
	}

	for _, tt := range tests {
		var sent []string

		shell := func(host, cmd string) (string, error) {
			sent = append(sent, host+": "+cmd)

			return tt.out, tt.err
		}

		err := checkMirrorBudget(shell, "phenix", "compute1")

		if tt.wantErr == "" {
			require.NoError(t, err, tt.name)
		} else {
			require.ErrorContains(t, err, tt.wantErr, tt.name)
		}

		assert.Equal(t, []string{"compute1: ovs-vsctl get bridge phenix mirrors"}, sent, tt.name)
	}
}
