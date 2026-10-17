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
