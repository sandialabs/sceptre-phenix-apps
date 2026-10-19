package main

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/mitchellh/mapstructure"

	"phenix-apps/util"
)

// ovsTokenRegex matches a single safe token for interpolation into ovs-vsctl
// commands run on cluster hosts. Bridge and interface names are capped at 15
// characters (IFNAMSIZ); VLAN aliases are phenix names with no such cap.
var (
	ovsTokenRegex  = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,15}$`)
	vlanAliasRegex = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
)

// validateOVSToken ensures a metadata-provided value is a single, safe token
// before it gets interpolated into an ovs-vsctl command. It explicitly rejects
// whitespace and the `--` command separator on top of the allowlist regex.
func validateOVSToken(field, value string) error {
	return validateToken(field, value, ovsTokenRegex)
}

func validateToken(field, value string, re *regexp.Regexp) error {
	if value == "--" || strings.ContainsAny(value, " \t\r\n") || !re.MatchString(value) {
		return fmt.Errorf(
			"invalid %s %q in mirror app metadata: must match %s and must not be `--`",
			field,
			value,
			re,
		)
	}

	return nil
}

// extractMetadata decodes the app metadata, applies defaults (defaultBridge is
// the experiment's default bridge) and validates the result, so a defaulted
// value is checked like one from the scenario.
func extractMetadata(data map[string]any, defaultBridge string) (MirrorAppMetadataV1, error) {
	var (
		amd     MirrorAppMetadataV1
		version = util.ExtractVersion(data)
	)

	switch version {
	case "v0":
		var md MirrorAppMetadata

		err := mapstructure.Decode(data, &md)
		if err != nil {
			return amd, fmt.Errorf("decoding app metadata: %w", err)
		}

		amd.Upgrade(md)
	case "v1":
		err := mapstructure.Decode(data, &amd)
		if err != nil {
			return amd, fmt.Errorf("decoding app metadata: %w", err)
		}
	}

	amd.Init()

	if amd.MirrorBridge == "" {
		amd.MirrorBridge = defaultBridge
	}

	err := validateOVSToken("mirrorBridge", amd.MirrorBridge)
	if err != nil {
		return amd, err
	}

	err = validateToken("mirrorVLAN", amd.MirrorVLAN, vlanAliasRegex)
	if err != nil {
		return amd, err
	}

	return amd, nil
}

func extractHostMetadata(data map[string]any) (MirrorHostMetadata, error) {
	var (
		hmd     MirrorHostMetadata
		version = util.ExtractVersion(data)
	)

	//nolint:gocritic // switch for future versions
	switch version {
	case "v0":
		err := mapstructure.Decode(data, &hmd)
		if err != nil {
			return hmd, fmt.Errorf("decoding host metadata: %w", err)
		}
	}

	for _, hil := range hmd.HIL {
		err := validateOVSToken("hilInterfaces entry", hil)
		if err != nil {
			return hmd, err
		}
	}

	return hmd, nil
}
