package main

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestValidateOVSToken(t *testing.T) {
	t.Parallel()

	for _, value := range []string{"phenix", "br-0", "eth1.100", "mirror", "a_b", "abcdefghijklmno"} {
		require.NoError(t, validateOVSToken("field", value), value)
	}

	for _, value := range []string{"", "--", "two words", "tab\there", "new\nline", "br0;reboot", "abcdefghijklmnop", "$(id)"} {
		require.Error(t, validateOVSToken("field", value), value)
	}
}

func TestExtractMetadataRejectsUnsafeTokens(t *testing.T) {
	t.Parallel()

	_, err := extractMetadata(map[string]any{"version": "v1", "mirrorBridge": "phenix -- del-br phenix"}, "phenix")
	require.Error(t, err)

	_, err = extractMetadata(map[string]any{"version": "v1", "mirrorVLAN": "mirror;id"}, "phenix")
	require.Error(t, err)

	amd, err := extractMetadata(map[string]any{"version": "v1", "mirrorBridge": "phenix", "mirrorVLAN": "mirror"}, "")
	require.NoError(t, err)
	assert.Equal(t, "phenix", amd.MirrorBridge)

	// VLAN aliases are phenix names, not OVS interface names: no 15-character cap.
	amd, err = extractMetadata(map[string]any{"version": "v1", "mirrorVLAN": "mirror_capture_net"}, "phenix")
	require.NoError(t, err)
	assert.Equal(t, "mirror_capture_net", amd.MirrorVLAN)

	// Defaults are applied before validation, so a bad default bridge is caught.
	amd, err = extractMetadata(map[string]any{"version": "v1"}, "phenix")
	require.NoError(t, err)
	assert.Equal(t, "phenix", amd.MirrorBridge)
	assert.Equal(t, "mirror", amd.MirrorVLAN)

	_, err = extractMetadata(map[string]any{"version": "v1"}, "br0 -- del-br br0")
	require.Error(t, err)

	_, err = extractHostMetadata(map[string]any{"hilInterfaces": []any{"eth1", "eth2 eth3"}})
	require.Error(t, err)
}

func TestCountMirrors(t *testing.T) {
	t.Parallel()

	tests := map[string]int{
		"[]":                       0,
		" [] \n":                   0,
		"[1b2c]":                   1,
		"[1b2c, 3d4e]":             2,
		"[1b2c,3d4e,5f60]":         3,
		"[1b2c, 3d4e, 5f60, 7182]": 4,
	}

	for out, want := range tests {
		got, err := countMirrors(out)
		require.NoError(t, err, out)
		assert.Equal(t, want, got, out)
	}

	for _, out := range []string{"", "ovs-vsctl: no row", "1b2c, 3d4e"} {
		_, err := countMirrors(out)
		require.ErrorIs(t, err, errMirrorList, out)
	}
}

func TestCreateMirrorArgTagsTheMirror(t *testing.T) {
	t.Parallel()

	arg, err := createMirrorArg("abc123", "exp1", []string{"@i0", "@i1"}, []string{"101", "102"})
	require.NoError(t, err)

	assert.Equal(
		t,
		"--id=@m create mirror name=abc123 select-dst-port=@i0,@i1 select-vlan=101,102 output-port=@o "+
			"external_ids:minimega-namespace=exp1 external_ids:minimega-kind=app-mirror",
		arg,
	)
}

func TestCreateMirrorArgRejectsUnsafeExperimentName(t *testing.T) {
	t.Parallel()

	for _, name := range []string{"", "exp 1", "exp1 -- del-br phenix", "$(id)", "--"} {
		_, err := createMirrorArg("abc123", name, []string{"@i0"}, []string{"101"})
		require.Error(t, err, name)
	}
}
