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

type MirrorHostMetadata struct {
	Interface string   `mapstructure:"interface"`
	VLANs     []string `mapstructure:"vlans"`
	SetupOVS  bool     `mapstructure:"setupOVS"`
}

type MirrorAppStatus struct {
	TapName string                  `json:"tapName" mapstructure:"tapName"`
	Mirrors map[string]MirrorConfig `json:"mirrors" mapstructure:"mirrors"`
}

type MirrorConfig struct {
	MirrorName string   `json:"mirrorName" mapstructure:"mirrorName"`
	IP         string   `json:"ip" mapstructure:"ip"`
	VLANs      []string `json:"vlans" mapstructure:"vlans"`
}
