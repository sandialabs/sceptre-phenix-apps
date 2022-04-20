package main

import (
	"fmt"
	"phenix-apps/util"

	"github.com/mitchellh/mapstructure"
)

func extractMetadata(data map[string]interface{}) (MirrorAppMetadataV1, error) {
	var (
		amd     MirrorAppMetadataV1
		version = util.ExtractVersion(data)
	)

	switch version {
	case "v0":
		var md MirrorAppMetadata

		if err := mapstructure.Decode(data, &md); err != nil {
			return amd, fmt.Errorf("decoding app metadata: %w", err)
		}

		amd.Upgrade(md)
	case "v1":
		if err := mapstructure.Decode(data, &amd); err != nil {
			return amd, fmt.Errorf("decoding app metadata: %w", err)
		}
	}

	return amd, nil
}

func extractHostMetadata(data map[string]interface{}) (MirrorHostMetadata, error) {
	var (
		hmd     MirrorHostMetadata
		version = util.ExtractVersion(data)
	)

	switch version {
	case "v0":
		if err := mapstructure.Decode(data, &hmd); err != nil {
			return hmd, fmt.Errorf("decoding host metadata: %w", err)
		}
	}

	return hmd, nil
}
