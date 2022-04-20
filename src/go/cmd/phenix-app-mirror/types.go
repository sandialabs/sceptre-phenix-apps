package main

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

type MirrorHostMetadata struct {
	Interface    string   `mapstructure:"interface"`
	VLANs        []string `mapstructure:"vlans"`
	HIL          []string `mapstructure:"hilInterfaces"`
	SetupOVS     bool     `mapstructure:"setupOVS"`
	MirrorRouted bool     `mapstructure:"forceMirrorRouted"`
}

type MirrorAppStatus struct {
	TapName string                  `json:"tapName" mapstructure:"tapName"`
	Mirrors map[string]MirrorConfig `json:"mirrors" mapstructure:"mirrors"`
}

type MirrorConfig struct {
	MirrorName string `json:"mirrorName" mapstructure:"mirrorName"`
	IP         string `json:"ip" mapstructure:"ip"`
}
