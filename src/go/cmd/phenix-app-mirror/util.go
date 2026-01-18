package main

import (
	"fmt"
	"phenix-apps/util"

	"github.com/mitchellh/mapstructure"
)

func extractMetadata(data map[string]any) (MirrorAppMetadataV1, error) {
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

	return hmd, nil
}
