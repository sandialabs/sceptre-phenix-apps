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

func (this *MirrorAppMetadataV1) Upgrade(md MirrorAppMetadata) {
	this.MirrorNet = md.DirectGRE.MirrorNet
	this.MirrorBridge = md.DirectGRE.MirrorBridge
	this.MirrorVLAN = md.DirectGRE.MirrorVLAN
	this.ERSPAN.Enabled = md.DirectGRE.ERSPAN.Enabled
	this.ERSPAN.Version = md.DirectGRE.ERSPAN.Version
	this.ERSPAN.Index = md.DirectGRE.ERSPAN.Index
	this.ERSPAN.Direction = md.DirectGRE.ERSPAN.Direction
	this.ERSPAN.HardwareID = md.DirectGRE.ERSPAN.HardwareID
}

func (this *MirrorAppMetadataV1) Init() {
	// Set some default values if missing from metadata.
	if this.MirrorNet == "" {
		this.MirrorNet = "10.248.171.0/24"
	}

	if !strings.Contains(this.MirrorNet, "/") {
		this.MirrorNet += "/24" // default to class C network
	}

	if this.MirrorVLAN == "" {
		this.MirrorVLAN = "mirror"
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
