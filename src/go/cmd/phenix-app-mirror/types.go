package main

import "strings"

type MirrorAppMetadata struct {
	DirectGRE struct {
		Enabled      bool   `mapstructure:"enabled"`
		MirrorNet    string `mapstructure:"mirrorNet"`
		MirrorBridge string `mapstructure:"mirrorBridge"`
		MirrorVLAN   string `mapstructure:"mirrorVLAN"`
		ERSPAN       struct {
			Enabled    bool `mapstructure:"enabled"`
			Version    int  `mapstructure:"version"`
			Index      int  `mapstructure:"index"`
			Direction  int  `mapstructure:"direction"`
			HardwareID int  `mapstructure:"hwid"`
		} `mapstructure:"erspan"`
	} `mapstructure:"directGRE"`
}

type MirrorAppMetadataV1 struct {
	MirrorNet    string `mapstructure:"mirrorNet"`
	MirrorBridge string `mapstructure:"mirrorBridge"`
	MirrorVLAN   string `mapstructure:"mirrorVLAN"`
	ERSPAN       struct {
		Enabled    bool `mapstructure:"enabled"`
		Version    int  `mapstructure:"version"`
		Index      int  `mapstructure:"index"`
		Direction  int  `mapstructure:"direction"`
		HardwareID int  `mapstructure:"hwid"`
	} `mapstructure:"erspan"`
}

func (md *MirrorAppMetadataV1) Upgrade(old MirrorAppMetadata) {
	md.MirrorNet = old.DirectGRE.MirrorNet
	md.MirrorBridge = old.DirectGRE.MirrorBridge
	md.MirrorVLAN = old.DirectGRE.MirrorVLAN
	md.ERSPAN.Enabled = old.DirectGRE.ERSPAN.Enabled
	md.ERSPAN.Version = old.DirectGRE.ERSPAN.Version
	md.ERSPAN.Index = old.DirectGRE.ERSPAN.Index
	md.ERSPAN.Direction = old.DirectGRE.ERSPAN.Direction
	md.ERSPAN.HardwareID = old.DirectGRE.ERSPAN.HardwareID
}

func (md *MirrorAppMetadataV1) Init() {
	// Set some default values if missing from metadata.
	if md.MirrorNet == "" {
		md.MirrorNet = "10.248.171.0/24"
	}

	if !strings.Contains(md.MirrorNet, "/") {
		md.MirrorNet += "/24" // default to class C network
	}

	if md.MirrorVLAN == "" {
		md.MirrorVLAN = "mirror"
	}
}

type MirrorHostMetadata struct {
	Interface    string   `mapstructure:"interface"`
	VLANs        []string `mapstructure:"vlans"`
	HIL          []string `mapstructure:"hilInterfaces"`
	SetupOVS     bool     `mapstructure:"setupOVS"`
	MirrorRouted bool     `mapstructure:"forceMirrorRouted"`
}

type MirrorAppStatus struct {
	TapName string                  `mapstructure:"tapName" structs:"tapName"`
	Subnet  string                  `mapstructure:"subnet"  structs:"subnet"`
	Mirrors map[string]MirrorConfig `mapstructure:"mirrors" structs:"mirrors"`
}

type MirrorConfig struct {
	MirrorName   string `mapstructure:"mirrorName"   structs:"mirrorName"`
	MirrorBridge string `mapstructure:"mirrorBridge" structs:"mirrorBridge"`
	IP           string `mapstructure:"ip"           structs:"ip"`
}
